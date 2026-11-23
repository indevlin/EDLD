"""The engine: reads journals, keeps per-commander state, pushes what is shared.

Runs on its own thread. The tray and settings window call its methods and
listen through on_change; nothing here imports Qt.
"""
import hashlib
import json
import logging
import random
import secrets
import threading
import time
from typing import Callable

from . import NAME, VERSION, journal, keys
from .single import PublisherLock
from .config import SPEC, Settings
from .proto import Client, ProtoError
from .state import EVENTS, Commander

log = logging.getLogger('edcmdr')

TICK = 1.0
DEBOUNCE = 60
PRESENCE_EVERY = 300
HELLO_EVERY = 6 * 3600
VERIFY_POLL = 4
TRANSIENT = ('net', 'reply', 'rate', 'maintenance', 'clock', 'server', 'replay')
VERIFY_NOTE = 600
BACKOFF_MIN, BACKOFF_MAX = 30, 900


def digest(v) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class Runtime:
    """What the engine knows about one commander's link to EDCMDR."""

    def __init__(self):
        self.enrolled = False
        self.verified = False
        self.pub_id: str | None = None
        self.blocked: str | None = None
        self.blocked_until = 0.0
        self.prefs_sent: str | None = None
        self.sent: dict[str, str] = {}
        self.next_ok: dict[str, float] = {}
        self.presence_sent: tuple[str, float] = ('', 0.0)
        self.last_push = 0.0
        self.error: str | None = None
        self.verify_until = 0.0
        self.verify_next = 0.0
        self.verifier: str | None = None
        self.vtoken: str | None = None
        self.verify_note: tuple[str, float] | None = None
        self.leader_of: int | None = None

    def note(self, j: dict) -> dict:
        """Take verified and leader_of from a reply that carries them."""
        if 'verified' in j:
            self.verified = bool(j['verified'])
        if 'leader_of' in j:
            self.leader_of = j['leader_of'] if isinstance(j['leader_of'], int) else None
        return j


class Engine:
    def __init__(self, settings: Settings, client: Client | None = None):
        self.settings = settings
        self.client = client or Client()
        self.cmdrs: dict[str, Commander] = {}
        self.rt: dict[str, Runtime] = {}
        self.watcher = journal.Watcher(settings.journal_dirs, self._event, EVENTS)
        self.state = 'paused' if settings.data.get('start_paused') else 'running'
        self.status = 'Starting'
        self.server: dict | None = None
        self.hello_at = 0.0
        self.backoff = 0.0
        self.backoff_step = BACKOFF_MIN
        self.force = False
        self.lock = threading.RLock()
        self.listeners: list[Callable[[], None]] = []
        self._stop = threading.Event()
        self._wake = threading.Event()
        self.thread: threading.Thread | None = None
        self.publisher = PublisherLock()
        self.standby_at = 0.0

    # ── control ─────────────────────────────────────────────────────────────
    def start(self) -> None:
        self.thread = threading.Thread(target=self.run, name='edcmdr-engine', daemon=True)
        self.thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        self._wake.set()
        if self.thread:
            self.thread.join(5)
        self.publisher.release()

    def pause(self) -> None:
        self._set_state('paused')

    def halt(self) -> None:
        self._set_state('stopped')

    def resume(self) -> None:
        self._set_state('running')

    def push_now(self) -> None:
        with self.lock:
            self.force = True
            self.backoff = 0
            for r in self.rt.values():
                r.blocked_until = 0
        self._wake.set()

    def _set_state(self, s: str) -> None:
        with self.lock:
            self.state = s
        self._notify()
        self._wake.set()

    def set_dirs(self, dirs: list[str]) -> None:
        self.settings.set_journal_dirs(dirs)
        with self.lock:
            self.watcher.set_dirs(self.settings.journal_dirs)
        self._wake.set()

    def set_prefs(self, fid: str, prefs: dict) -> None:
        self.settings.set_prefs(fid, prefs)
        with self.lock:
            r = self._rt(fid)
            r.sent.clear()
            r.next_ok.clear()
            r.presence_sent = ('', 0.0)
        self._wake.set()

    def verify_start(self, fid: str) -> dict:
        """Ask the server for a verification link; the engine then finishes it once the browser is back.

        The PKCE verifier is made and kept here, in memory; the server gets only its challenge."""
        with self.lock:
            c = self.cmdrs.get(fid)
            name = c.name if c else self.settings.commander(fid).get('name', '')
        verifier = keys.b64u(secrets.token_bytes(48))
        challenge = keys.b64u(hashlib.sha256(verifier.encode()).digest())
        j = self.client.push(keys.commander_key(fid), fid, 'verify-start', {'name': name, 'challenge': challenge})
        with self.lock:
            r = self._rt(fid)
            r.blocked, r.blocked_until = None, 0.0
            r.verifier, r.vtoken = verifier, None
            r.verify_note = ("Verifying: sign in on Frontier's site", time.time() + VERIFY_NOTE)
            r.verify_until = float(j.get('expires') or time.time() + 600)
            r.verify_next = time.time() + VERIFY_POLL
        self._wake.set()
        return {'url': j.get('url', ''), 'code': j.get('code', '')}

    def _verify_step(self, fid: str, c: Commander, r: Runtime) -> None:
        """Poll for Frontier's code, exchange it here, hand the token to the server once."""
        key = keys.commander_key(fid)
        try:
            if r.vtoken is None:
                p = self.client.push(key, fid, 'verify-poll', {})
                st = p.get('state')
                if st == 'waiting':
                    return
                if st != 'ready':
                    self._verify_end(r, {'cancelled': "it was cancelled on Frontier's site.",
                                         'expired': 'the link expired; press Verify again.'}.get(
                                             st, 'press Verify again.'))
                    return
                r.verify_note = ('Verifying: finishing with Frontier', time.time() + VERIFY_NOTE)
                r.vtoken = self.client.frontier_token(str(p.get('token_url', '')), {
                    'grant_type': 'authorization_code', 'client_id': p.get('client_id', ''), 'code': p.get('code', ''),
                    'code_verifier': r.verifier, 'redirect_uri': p.get('redirect_uri', '')})
            j = self.client.push(key, fid, 'verify-finish', {'access_token': r.vtoken})
        except ProtoError as e:
            if e.code == 'upstream':
                r.verify_note = (f'Verifying: {e} Retrying.', time.time() + VERIFY_NOTE)
                return
            if e.code in TRANSIENT:
                raise
            self._verify_end(r, str(e))
            return
        self._verify_end(r, None)
        r.enrolled, r.verified = True, True
        r.pub_id = j.get('pub_id') or r.pub_id
        r.blocked, r.blocked_until = None, 0.0
        r.prefs_sent = None
        r.sent.clear()
        self.settings.set_commander(fid, pub_id=r.pub_id, name=c.name)

    @staticmethod
    def _verify_end(r: Runtime, why: str | None) -> None:
        r.verify_until, r.verifier, r.vtoken = 0.0, None, None
        r.verify_note = (f'Verification failed: {why}', time.time() + VERIFY_NOTE) if why else None

    def _ensure_enrolled(self, fid: str) -> None:
        """Enroll and send prefs now, ahead of a one-off push from the UI."""
        key = keys.commander_key(fid)
        r = self._rt(fid)
        name = self.cmdrs[fid].name if fid in self.cmdrs else self.settings.commander(fid).get('name', '')
        if not r.enrolled:
            j = self.client.push(key, fid, 'enroll', {'name': name})
            r.enrolled, r.verified = True, bool(j.get('verified'))
            r.pub_id = j.get('pub_id') or r.pub_id
        prefs = self.settings.prefs(fid)
        if r.prefs_sent != digest(prefs):
            r.note(self.client.push(key, fid, 'prefs', prefs))
            r.prefs_sent = digest(prefs)

    def push_portrait(self, fid: str, jpeg: bytes) -> str:
        """Send a Codex screenshot (already JPEG); returns the portrait's path on the site."""
        import base64
        with self.lock:
            self._ensure_enrolled(fid)
            r = self._rt(fid)
            j = r.note(self.client.push(keys.commander_key(fid), fid, 'portrait',
                                        {'image': base64.b64encode(jpeg).decode()}))
        if j.get('refused'):
            raise ProtoError('refused', 'Portrait sharing is switched off for this commander.')
        self._notify()
        return str(j.get('portrait', ''))

    def save_squadron(self, fid: str, details: dict) -> None:
        with self.lock:
            self._ensure_enrolled(fid)
            r = self._rt(fid)
            r.note(self.client.push(keys.commander_key(fid), fid, 'squadron', details))
        self.settings.set_commander(fid, squadron_details=details)

    def forget(self, fid: str) -> str | None:
        """Ask the server to delete this commander; on success drop the local key and settings."""
        with self.lock:
            r = self._rt(fid)
            if not r.enrolled:
                keys.drop_commander_key(fid)
                self.settings.forget_commander(fid)
                return None
        try:
            self.client.push(keys.commander_key(fid), fid, 'forget', {})
        except ProtoError as e:
            return str(e)
        keys.drop_commander_key(fid)
        self.settings.forget_commander(fid)
        with self.lock:
            self.rt[fid] = Runtime()
            self.rt[fid].blocked = 'Forgotten. Turn sharing back on to publish again.'
            self.rt[fid].blocked_until = float('inf')
        self._notify()
        return None

    def on_change(self, fn: Callable[[], None]) -> None:
        self.listeners.append(fn)

    def _notify(self) -> None:
        for fn in self.listeners:
            try:
                fn()
            except Exception:
                log.exception('listener failed')

    # ── views for the UI ────────────────────────────────────────────────────
    def snapshot(self) -> dict:
        with self.lock:
            cm = []
            for fid, c in sorted(self.cmdrs.items(), key=lambda kv: kv[1].name):
                r = self._rt(fid)
                cm.append({'fid': fid, 'name': c.name, 'enrolled': r.enrolled, 'verified': r.verified,
                           'leader_of': r.leader_of,
                           'pub_id': r.pub_id, 'blocked': r.blocked, 'error': r.error, 'last_push': r.last_push,
                           'verify': r.verify_note[0] if r.verify_note and r.verify_note[1] > time.time() else None,
                           'in_game': c.presence()['in_game']})
            return {'state': self.state, 'status': self.status, 'official': self.client.official,
                    'server': self.client.base, 'commanders': cm, 'update': self.update_available()}

    # ── loop ────────────────────────────────────────────────────────────────
    def _rt(self, fid: str) -> Runtime:
        return self.rt.setdefault(fid, Runtime())

    def _event(self, fid: str, ev: dict) -> None:
        c = self.cmdrs.get(fid)
        if c is None:
            c = self.cmdrs[fid] = Commander(fid)
        c.handle(ev)

    def run(self) -> None:
        while not self._stop.is_set():
            if not self.publisher.acquire():
                if time.time() - self.standby_at > 30:
                    self.standby_at = time.time()
                    self.status = 'Standing by: another EDCMDR publisher is running on this computer'
                    self._notify()
                self._wake.wait(30)
                self._wake.clear()
                continue
            try:
                self.tick()
            except Exception:
                log.exception('engine tick failed')
            self._wake.wait(TICK)
            self._wake.clear()

    def tick(self) -> None:
        with self.lock:
            state = self.state
            if state != 'stopped':
                first = not self.watcher.imported
                self.watcher.poll()
                if first:
                    for c in self.cmdrs.values():
                        c.loaded = True
        if state != 'running':
            self.status = {'paused': 'Paused', 'stopped': 'Stopped'}[state]
            self._notify()
            return
        now = time.time()
        if now < self.backoff:
            return
        try:
            if now - self.hello_at > HELLO_EVERY or self.server is None:
                self._hello()
            for fid in list(self.cmdrs):
                self._sync(fid, now)
            self.backoff_step = BACKOFF_MIN
            self.force = False
            if self.status not in ('Update required', 'Unofficial build'):
                self.status = 'Connected'
        except ProtoError as e:
            self._fail(e)
        self._notify()

    def update_available(self) -> str:
        """The newer client build the server announces, or ''. Hosts (EDLD) carry their own version."""
        if NAME != 'EDCMDR-client':
            return ''
        latest = str((self.server or {}).get('latest_client', ''))
        return latest if latest.isdigit() and len(latest) == 8 and latest > VERSION else ''

    def _hello(self) -> None:
        j = self.client.hello()
        self.server = j
        self.hello_at = time.time()
        if SPEC['protocol'] not in j.get('protocols', []):
            self.status = 'Update required'
            raise ProtoError('version', 'This client is too old for the server; update it.')
        if not self.client.official:
            self.status = 'Unofficial build'

    def _fail(self, e: ProtoError) -> None:
        if e.code in ('rate', 'maintenance') and isinstance(e.extra.get('retry_after'), int):
            wait = e.extra['retry_after'] + random.randint(5, 60)
        else:
            wait = self.backoff_step
            self.backoff_step = min(BACKOFF_MAX, self.backoff_step * 2)
        self.backoff = time.time() + wait
        if e.code == 'build':
            self.status = 'Unofficial build'
            self.backoff = time.time() + 3600
        elif e.code == 'version':
            self.status = 'Update required'
            self.backoff = time.time() + 3600
        elif e.code == 'maintenance':
            self.status = f'Server maintenance; retrying in {int(wait)} s'
        else:
            self.status = f'Retrying in {int(wait)} s: {e}'
        log.warning('push failed: %s (%s)', e, e.code)

    def _sync(self, fid: str, now: float) -> None:
        c = self.cmdrs[fid]
        r = self._rt(fid)
        if not c.name:
            return
        if r.verifier and now > r.verify_until:
            self._verify_end(r, 'the link expired; press Verify again.')
        elif r.verifier and now >= r.verify_next:
            r.verify_next = now + VERIFY_POLL
            self._verify_step(fid, c, r)
        if r.blocked and now < r.blocked_until:
            return
        prefs = self.settings.prefs(fid)
        if not any(prefs['share'].values()) and not prefs['presence'] and not r.enrolled:
            r.blocked = None
            return
        key = keys.commander_key(fid)
        try:
            if not r.enrolled:
                j = self.client.push(key, fid, 'enroll', {'name': c.name})
                r.enrolled, r.verified = True, bool(j.get('verified'))
                r.pub_id = j.get('pub_id') or self.settings.commander(fid).get('pub_id')
                self.settings.set_commander(fid, pub_id=r.pub_id, name=c.name)
                r.blocked = None
            pd = digest(prefs)
            if r.prefs_sent != pd:
                r.note(self.client.push(key, fid, 'prefs', prefs))
                r.prefs_sent = pd
            self._snapshot(c, r, key, prefs, now)
            self._presence(c, r, key, prefs, now)
            r.error = None
        except ProtoError as e:
            if e.code in ('claimed', 'not-enrolled'):
                r.blocked = e.args[0]
                r.blocked_until = now + (15 if r.verify_until > now else 3600)
                r.enrolled = False
                return
            if e.code in ('implausible', 'body'):
                r.error = f'{e} ({e.extra.get("field") or e.extra.get("category") or ""})'.strip()
                return
            raise

    def _snapshot(self, c: Commander, r: Runtime, key, prefs: dict, now: float) -> None:
        cats = {}
        for cat, data in c.categories().items():
            if cat not in SPEC['snapshot_categories']:
                continue
            if cat not in SPEC['always_shared'] and not prefs['share'].get(cat):
                continue
            d = digest(data)
            if r.sent.get(cat) == d:
                continue
            if not self.force and now < r.next_ok.get(cat, 0):
                continue
            cats[cat] = (data, d)
        if not cats:
            return
        j = r.note(self.client.push(key, c.fid, 'snapshot', {'categories': {k: v[0] for k, v in cats.items()}}))
        for cat in j.get('accepted', []):
            if cat in cats:
                r.sent[cat] = cats[cat][1]
                r.next_ok[cat] = now + DEBOUNCE
        for cat in j.get('refused', []):
            if cat in cats:
                r.sent[cat] = cats[cat][1]
        r.last_push = now

    def _presence(self, c: Commander, r: Runtime, key, prefs: dict, now: float) -> None:
        if not prefs['presence']:
            return
        p = c.presence()
        d = digest(p)
        last_d, last_t = r.presence_sent
        if d == last_d and (not p['in_game'] or now - last_t < PRESENCE_EVERY) and not self.force:
            return
        r.note(self.client.push(key, c.fid, 'presence', p))
        r.presence_sent = (d, now)
        r.last_push = now
