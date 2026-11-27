"""Optional uploads to community services, straight from this computer: EDDN, EDSM, EDAstro and Inara.

Each is off until switched on for a commander in the Integrations tab. Each service keeps a mark per commander:
the place in the journals of the last event it accepted. Everything after the mark goes, whether it is read live
or from the history import at start, so play while the client was closed, offline or paused is filled in. The
mark moves only when the service accepts (or permanently refuses) a batch; switching a service off forgets it.

A service with no mark yet (just switched on, or first run) catches up once, without assuming any other app ran
before: EDSM from the last position EDSM itself holds; EDDN and EDAstro from the start of the current session
when it began within a day; Inara with the commander's current state only, never older log entries. Then the
mark is set and it goes on from there.
"""
import calendar
import gzip
import json
import logging
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import NAME, VERSION, capi, eddn, inara, journal, paths

log = logging.getLogger('edcmdr')

TIMEOUT = 30
HOLD_WAIT = 300.0
CAPI_DELAY = 5.0
SESSION_WINDOW = 24 * 3600
INARA_WINDOW = 30 * 24 * 3600
INARA_STATE = inara.SNAPSHOT | {'setCommanderShip', 'setCommanderShipLoadout', 'addCommanderShip', 'delCommanderShip',
                                'setCommanderRankEngineer', 'setCommanderReputationMinorFaction',
                                'setCommanderSuitLoadout', 'updateCommanderSuitLoadout', 'delCommanderSuitLoadout'}

EDSM_URL = 'https://www.edsm.net/api-journal-v1'
EDSM_DISCARD_URL = 'https://www.edsm.net/api-journal-v1/discard'
EDSM_POSITION_URL = 'https://www.edsm.net/api-logs-v1/get-position'
EDSM_SKIP = frozenset({'Fileheader', 'continued', 'Shutdown', 'ShutDown'})

EDASTRO_URL = 'https://edastro.com/api/journal'
EDASTRO_INTEREST_URL = 'https://edastro.com/api/journal/interested'
EDASTRO_CARRIER = frozenset({'CarrierStatus', 'CarrierJumpRequest'})
EDASTRO_FALLBACK = frozenset({
    'Scan', 'SAAScanComplete', 'SAASignalsFound', 'FSSBodySignals', 'FSSDiscoveryScan', 'FSSSignalDiscovered',
    'NavBeaconScan', 'CodexEntry', 'ScanOrganic', 'SellOrganicData', 'FSDJump', 'CarrierJump', 'Location',
    'Docked', 'Undocked', 'MarketBuy', 'MarketSell', 'MissionAccepted', 'MissionCompleted', 'MissionFailed',
    'MissionAbandoned', 'Bounty', 'RedeemVoucher', 'Rank', 'Progress', 'Promotion', 'Powerplay',
    'PowerplaySalary', 'PowerplayCollect', 'EngineerProgress', 'MaterialCollected', 'MaterialTrade',
    'MiningRefined', 'ProspectedAsteroid', 'ShipyardBuy', 'ShipyardSell', 'ModuleBuy', 'ModuleSell', 'Loadout',
    'CommunityGoal', 'CommunityGoalJoin', 'CommunityGoalReward', 'CarrierStats', 'CarrierJumpCancelled',
    'CarrierStatus', 'CarrierJumpRequest'})

SERVICES = {
    'eddn': {'label': 'EDDN', 'keys': {'enabled': False}},
    'edsm': {'label': 'EDSM', 'keys': {'enabled': False, 'api_key': ''}},
    'edastro': {'label': 'EDAstro', 'keys': {'enabled': False, 'carrier': False}},
    'inara': {'label': 'Inara', 'keys': {'enabled': False, 'api_key': ''}},
    'capi': {'label': 'Frontier CAPI', 'keys': {'enabled': False}},
}


def beta(gameversion: str) -> bool:
    g = (gameversion or '').lower()
    return 'beta' in g or g.startswith('3.')


class Tracker:
    """Where a commander is, as EDSM wants each event annotated, and the game version."""

    def __init__(self):
        self.system = self.address = self.pos = self.market = self.station = self.ship = None
        self.gameversion = self.build = ''

    def update(self, ev: dict) -> None:
        e = ev.get('event')
        if e in ('Fileheader', 'LoadGame'):
            self.gameversion = ev.get('gameversion') or self.gameversion
            self.build = ev.get('build') or self.build
        if e in ('FSDJump', 'CarrierJump', 'Location', 'Docked'):
            self.system = ev.get('StarSystem') or self.system
            self.address = ev.get('SystemAddress') or self.address
            self.pos = ev.get('StarPos') or self.pos
        if e in ('FSDJump', 'CarrierJump', 'Undocked'):
            self.market = self.station = None
        if e in ('Docked', 'Location') and ev.get('Docked', e == 'Docked'):
            self.market = ev.get('MarketID') or self.market
            self.station = ev.get('StationName') or self.station
        if e in ('LoadGame', 'Loadout', 'ShipyardSwap', 'ShipyardBuy') and isinstance(ev.get('ShipID'), int):
            self.ship = ev['ShipID']

    def annotate(self, ev: dict) -> dict:
        out = dict(ev)
        for k, v in (('_systemName', self.system), ('_systemAddress', self.address), ('_systemCoordinates', self.pos),
                     ('_marketId', self.market), ('_stationName', self.station), ('_shipId', self.ship)):
            if v is not None:
                out.setdefault(k, v)
        return out


def _epoch(ts: str) -> float | None:
    """Seconds since 1970 from a journal timestamp or an EDSM date (both UTC)."""
    try:
        return calendar.timegm(time.strptime(ts.replace('T', ' ').rstrip('Z')[:19], '%Y-%m-%d %H:%M:%S'))
    except (AttributeError, ValueError, OverflowError):
        return None


def _before(cursor: str) -> str:
    """The mark that lets cursor itself through."""
    head, _, off = cursor.rpartition('|')
    return f'{head}|{max(int(off) - 1, 0):012d}' if int(off) else f'{head}|'


class Marks:
    """Per service and commander, the journal cursor of the last event the service accepted."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        try:
            d = json.loads(path.read_text(encoding='utf-8'))
            self.d = {s: {f: c for f, c in v.items() if isinstance(c, str)} for s, v in d.items() if isinstance(v, dict)}
        except (OSError, ValueError, AttributeError):
            self.d = {}

    def get(self, service: str, fid: str) -> str | None:
        with self.lock:
            return self.d.get(service, {}).get(fid)

    def set(self, service: str, fid: str, cursor: str) -> None:
        with self.lock:
            m = self.d.setdefault(service, {})
            if cursor <= m.get(fid, ''):
                return
            m[fid] = cursor
            self._save()

    def arm(self, service: str, fid: str, cursor: str) -> None:
        with self.lock:
            self.d.setdefault(service, {})[fid] = cursor
            self._save()

    def drop(self, service: str, fid: str) -> None:
        with self.lock:
            if self.d.get(service, {}).pop(fid, None) is not None:
                self._save()

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(self.d, indent=1, sort_keys=True), encoding='utf-8')
            tmp.replace(self.path)
        except OSError as e:
            log.warning('could not keep integration marks: %s', e)


class Sender:
    """One service: a queue of (fid, group, event, cursor), sent in batches on its own thread."""

    name = ''
    batch_max = 30
    gap = 10.0
    retry_wait = 60.0

    def __init__(self, hub: 'Hub'):
        self.hub = hub
        self.q: list = []
        self.cv = threading.Condition()
        self.stop = self.woken = False
        self.last_send = 0.0
        self.status = 'Idle'
        self.sent = 0
        self.thread = threading.Thread(target=self._run, name=f'edcmdr-{self.name}', daemon=True)
        self.thread.start()

    def push(self, fid: str, group: tuple, ev: dict, cursor: str | None = None) -> None:
        with self.cv:
            self.q.append((fid, list(group), ev, cursor))
            self.cv.notify()

    def wake(self) -> None:
        with self.cv:
            self.woken = True
            self.cv.notify_all()

    def shutdown(self) -> None:
        with self.cv:
            self.stop = True
            self.cv.notify_all()
        self.thread.join(5)

    def pending(self) -> int:
        with self.cv:
            return len(self.q)

    def _take(self) -> tuple[str, list, list[dict], list]:
        """The first commander's events in one group, in journal order, up to batch_max."""
        fid, group = self.q[0][0], self.q[0][1]
        out, rest, cursors, blocked = [], [], [], False
        for it in self.q:
            if it[0] != fid or blocked:
                rest.append(it)
            elif it[1] == group and len(out) < self.batch_max:
                out.append(it[2])
                cursors.append(it[3])
            else:
                blocked = True
                rest.append(it)
        self.q = rest
        return fid, group, out, cursors

    def _back(self, fid, group, batch, cursors) -> None:
        self.q[:0] = [(fid, group, ev, c) for ev, c in zip(batch, cursors)]

    def _run(self) -> None:
        while True:
            with self.cv:
                while (not self.q or self.hub.paused) and not self.stop:
                    self.cv.wait(5)
                if self.stop:
                    return
                wait = self.gap - (time.monotonic() - self.last_send)
            if wait > 0:
                time.sleep(min(wait, 1.0))
                continue
            with self.cv:
                fid, group, batch, cursors = self._take()
            if not self.hub.config(self.hub.settings, fid, self.name)['enabled']:
                continue
            self.last_send = time.monotonic()
            done = [c for c in cursors if c]
            try:
                self.send(fid, group, batch)
                self.sent += len(batch)
                self.status = f'Sent {self.sent} events this session' + (f', {self.pending()} waiting' if self.q else '')
            except Hold as e:
                self.status = f'Waiting: {e}'
                with self.cv:
                    self._back(fid, group, batch, cursors)
                    self.woken = False
                    self.cv.wait_for(lambda: self.stop or self.woken, HOLD_WAIT)
                continue
            except Retry as e:
                self.status = f'Will retry: {e}'
                with self.cv:
                    self._back(fid, group, batch, cursors)
                    self.cv.wait_for(lambda: self.stop, self.retry_wait)
                continue
            except Exception as e:  # noqa: BLE001
                self.status = f'Refused: {e}'
                log.warning('%s refused %d events: %s', self.name, len(batch), e)
            if done:
                self.hub.marks.set(self.name, fid, max(done))

    def send(self, fid: str, group: list, batch: list[dict]) -> None:
        raise NotImplementedError

    @staticmethod
    def post(url: str, body: bytes, headers: dict) -> bytes:
        req = urllib.request.Request(url, data=body, method='POST',
                                     headers={'User-Agent': f'{NAME}/{VERSION}', **headers})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (408, 429) or e.code >= 500:
                raise Retry(f'HTTP {e.code}') from e
            raise RuntimeError(f'HTTP {e.code}') from e
        except (urllib.error.URLError, OSError) as e:
            raise Retry(str(e)) from e


class Hold(Exception):
    """Not sendable until the settings change: no API key, or the key refused. The mark stays."""


class Retry(Exception):
    """A failure worth retrying: network, timeout, rate limit, server error."""


def fetch_json(url: str):
    req = urllib.request.Request(url, headers={'User-Agent': f'{NAME}/{VERSION}'})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read())


class EDSM(Sender):
    name = 'edsm'
    batch_max = 50
    gap = 12.0
    url = EDSM_URL
    refused_key = frozenset({201, 202, 203})

    def __init__(self, hub: 'Hub'):
        self.discard: frozenset[str] = frozenset()
        self.ready = threading.Event()
        super().__init__(hub)
        threading.Thread(target=self._discard, daemon=True, name='edcmdr-edsm-discard').start()

    def _discard(self) -> None:
        try:
            d = fetch_json(EDSM_DISCARD_URL)
            if isinstance(d, list):
                self.discard = frozenset(x for x in d if isinstance(x, str))
        except Exception as e:  # noqa: BLE001
            log.info('EDSM discard list unavailable (%s); EDSM drops what it does not take', e)
        self.ready.set()

    def wants(self, ev: dict) -> bool:
        return ev.get('event') not in EDSM_SKIP and ev.get('event') not in self.discard

    def send(self, fid: str, group: list, batch: list[dict]) -> None:
        self.ready.wait(TIMEOUT)
        batch = [ev for ev in batch if self.wants(ev)]
        if not batch:
            return
        cmdr, gv, build = group
        key = self.hub.key(fid, 'edsm')
        if not key:
            raise Hold('no EDSM API key')
        form = {'commanderName': cmdr, 'apiKey': key, 'fromSoftware': NAME, 'fromSoftwareVersion': VERSION,
                'fromGameVersion': gv, 'fromGameBuild': build,
                'message': json.dumps(batch, separators=(',', ':'))}
        body = self.post(self.url, urllib.parse.urlencode(form).encode(),
                         {'Content-Type': 'application/x-www-form-urlencoded'})
        try:
            j = json.loads(body)
        except ValueError as e:
            raise Retry('unreadable reply') from e
        if j.get('msgnum') in self.refused_key:
            raise Hold(f"EDSM refused the commander or key ({j.get('msg', '')})")
        if j.get('msgnum') != 100:
            raise RuntimeError(f"{j.get('msgnum')} {j.get('msg', '')}".strip())


class EDAstro(Sender):
    name = 'edastro'
    batch_max = 30
    gap = 10.0
    url = EDASTRO_URL

    def __init__(self, hub: 'Hub'):
        self.interest = EDASTRO_FALLBACK
        self.ready = threading.Event()
        super().__init__(hub)
        threading.Thread(target=self._interest, daemon=True, name='edcmdr-edastro-interest').start()

    def _interest(self) -> None:
        try:
            d = fetch_json(EDASTRO_INTEREST_URL)
            if isinstance(d, list) and d:
                self.interest = frozenset(x for x in d if isinstance(x, str))
        except Exception as e:  # noqa: BLE001
            log.info('EDAstro interest list unavailable (%s); using the built-in list', e)
        self.ready.set()

    def wants(self, ev: dict, carrier: bool) -> bool:
        e = ev.get('event')
        return e in self.interest and (carrier or e not in EDASTRO_CARRIER)

    def send(self, fid: str, group: list, batch: list[dict]) -> None:
        self.ready.wait(TIMEOUT)
        carrier = bool(self.hub.config(self.hub.settings, fid, 'edastro')['carrier'])
        batch = [ev for ev in batch if self.wants(ev, carrier)]
        if batch:
            self.post(self.url, gzip.compress(json.dumps(batch, separators=(',', ':')).encode()),
                      {'Content-Type': 'application/json', 'Content-Encoding': 'gzip'})


class EDDN(Sender):
    name = 'eddn'
    batch_max = 1
    gap = 0.2
    url = eddn.ENDPOINT

    def send(self, fid: str, group: list, batch: list[dict]) -> None:
        for env in batch:
            self.post(self.url, gzip.compress(json.dumps(env, separators=(',', ':')).encode()),
                      {'Content-Type': 'application/json', 'Content-Encoding': 'gzip'})


class Inara(Sender):
    name = 'inara'
    batch_max = 100
    gap = 30.0
    url = inara.URL
    hold = 3660.0

    @staticmethod
    def coalesce(batch: list[dict]) -> list[dict]:
        """Of each whole-state event in a batch only the last counts; the others are dropped."""
        last = {e['eventName']: i for i, e in enumerate(batch) if e['eventName'] in inara.SNAPSHOT}
        return [e for i, e in enumerate(batch) if e['eventName'] not in inara.SNAPSHOT or last[e['eventName']] == i]

    def send(self, fid: str, group: list, batch: list[dict]) -> None:
        (cmdr,) = group
        batch = self.coalesce(batch)
        key = self.hub.key(fid, 'inara')
        if not key:
            raise Hold('no Inara API key')
        header = {'appName': NAME, 'appVersion': VERSION, 'isBeingDeveloped': False, 'APIkey': key,
                  'commanderName': cmdr, 'commanderFrontierID': fid}
        body = self.post(self.url, json.dumps({'header': header, 'events': batch}, separators=(',', ':')).encode(),
                         {'Content-Type': 'application/json'})
        try:
            j = json.loads(body)
            h = j.get('header', {})
        except (ValueError, AttributeError) as e:
            raise Retry('unreadable reply') from e
        status, text = h.get('eventStatus', 200), h.get('eventStatusText', '')
        if inara.throttled(status, text):
            self.retry_wait = self.hold
            raise Retry(f'Inara asks to wait an hour: {text}')
        self.retry_wait = Sender.retry_wait
        if inara.refused_key(status, text):
            raise Hold(f'Inara refused the key: {text}')
        if status not in (200, 204):
            raise RuntimeError(f'{status} {text}'.strip())
        for sent, got in zip(batch, j.get('events') or []):
            if isinstance(got, dict) and got.get('eventStatus', 200) not in (200, 204):
                log.info('Inara %s: %s %s', sent.get('eventName'), got.get('eventStatus'), got.get('eventStatusText', ''))


SENDERS = {'eddn': EDDN, 'edsm': EDSM, 'edastro': EDAstro, 'inara': Inara}


class Hub:
    """Routes journal events past each service's mark to the services each commander has switched on."""

    def __init__(self, settings, state_dir: Path | None = None, journal_dirs=None):
        self.settings = settings
        self.journal_dirs = journal_dirs or (lambda: list(settings.journal_dirs))
        self.pending: set[tuple[str, str]] = set()
        self.feed_lock = threading.RLock()
        self.state_dir = state_dir or paths.config_dir()
        self.marks = Marks(self.state_dir / 'integrations.json')
        shutil.rmtree(self.state_dir / 'queue', ignore_errors=True)
        self.paused = False
        self.trackers: dict[str, Tracker] = {}
        self.names: dict[str, str] = {}
        self.latest: dict[str, str] = {}
        self.senders: dict[str, Sender] = {}
        self.builders: dict[str, eddn.Builder] = {}
        self.inara: dict[str, inara.Builder] = {}
        self.capi: dict[str, capi.Client] = {}
        self.capi_seen: dict[str, str] = {}
        self.capi_base = capi.BASE
        self.capi_root: Path | None = None
        self.lock = threading.Lock()

    @staticmethod
    def config(settings, fid: str, service: str) -> dict:
        c = settings.commander(fid).get('integrations', {}).get(service, {})
        return {**SERVICES[service]['keys'], **(c if isinstance(c, dict) else {})}

    def key(self, fid: str, service: str) -> str:
        return str(self.config(self.settings, fid, service).get('api_key') or '').strip()

    def any_on(self) -> bool:
        return any(self.config(self.settings, fid, s)['enabled']
                   for fid in self.settings.data.get('commanders', {}) for s in SERVICES)

    def _sender(self, service: str) -> Sender:
        with self.lock:
            if service not in self.senders:
                self.senders[service] = SENDERS[service](self)
            return self.senders[service]

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        self.wake()

    def wake(self) -> None:
        """Settings changed: held senders try again now."""
        for s in list(self.senders.values()):
            s.wake()

    def _due(self, service: str, fid: str, cursor: str | None, live: bool) -> bool:
        """Switched on and after the mark. With no mark yet, a catch-up starts and covers this event."""
        if not self.config(self.settings, fid, service)['enabled']:
            self.marks.drop(service, fid)
            return False
        if cursor is None:
            return live
        if (service, fid) in self.pending:
            return False
        mark = self.marks.get(service, fid)
        if mark is None:
            if live:
                self._catch_up(service, fid)
            return False
        return cursor > mark

    def imported(self) -> None:
        """The history import is done: services switched on without a mark catch up."""
        for fid in list(self.settings.data.get('commanders', {})):
            for s in SENDERS:
                if not self.config(self.settings, fid, s)['enabled']:
                    self.marks.drop(s, fid)
                elif self.marks.get(s, fid) is None:
                    self._catch_up(s, fid)

    # ── catching up a service with no mark ─────────────────────────────────────────────────────

    def _catch_up(self, service: str, fid: str) -> None:
        with self.lock:
            if (service, fid) in self.pending:
                return
            self.pending.add((service, fid))
        threading.Thread(target=self._catch_up_run, args=(service, fid), daemon=True,
                         name=f'edcmdr-catchup-{service}').start()

    def _read(self, fid: str, on_event) -> journal.Watcher:
        w = journal.Watcher(self.journal_dirs(), lambda f, e: on_event(e) if f == fid else None)
        w.poll()
        return w

    def _catch_up_run(self, service: str, fid: str) -> None:
        try:
            idx: list[tuple[str, str, str, str | None]] = []

            def index(e):
                if e['event'] in ('Commander', 'LoadGame') and (e.get('Name') or e.get('Commander')):
                    self.names.setdefault(fid, e.get('Name') or e.get('Commander'))
                if e['event'] in ('LoadGame', 'FSDJump', 'CarrierJump', 'Location'):
                    idx.append((e['_cursor'], e.get('timestamp', ''), e['event'], e.get('StarSystem')))

            self._read(fid, index)
            anchor = self._anchor(service, fid, idx, self.names.get(fid)) if idx else None
            self._replay(service, fid, anchor)
        except Exception:  # noqa: BLE001
            log.exception('%s catch-up failed; starting from now', service)
            with self.feed_lock:
                self._arm(service, fid, self.latest.get(fid, ''))

    def _session(self, idx) -> str | None:
        """The mark before the newest session, when it began within SESSION_WINDOW."""
        start = next((i for i in reversed(idx) if i[2] == 'LoadGame'), None)
        t = _epoch(start[1]) if start else None
        return _before(start[0]) if t is not None and time.time() - t <= SESSION_WINDOW else None

    def _anchor(self, service: str, fid: str, idx, name: str | None) -> str | None:
        """Where the catch-up starts: events after this cursor go. None: nothing before now."""
        if service == 'inara':
            return None
        if service == 'edsm':
            at = self._edsm_position(fid, name)
            if at is not None:
                system, t = at
                hit = [i for i in idx if i[2] in ('FSDJump', 'CarrierJump', 'Location') and i[3] == system
                       and (_epoch(i[1]) or 0) <= t + 1]
                if hit:
                    return hit[-1][0]
                older = [i for i in idx if (_epoch(i[1]) or 0) <= t]
                if older:
                    return older[-1][0]
        return self._session(idx)

    def _edsm_position(self, fid: str, name: str | None) -> tuple[str, float] | None:
        key = self.key(fid, 'edsm')
        if not key or not name:
            return None
        try:
            d = fetch_json(EDSM_POSITION_URL + '?' + urllib.parse.urlencode({'commanderName': name, 'apiKey': key}))
        except Exception as e:  # noqa: BLE001
            log.info('EDSM position unavailable (%s); catching up from the session', e)
            return None
        t = _epoch(str(d.get('date') or '')) if isinstance(d, dict) and d.get('msgnum') == 100 else None
        return (str(d['system']), t) if t is not None and d.get('system') else None

    def _replay(self, service: str, fid: str, anchor: str | None) -> None:
        """Read the journals again for this service alone and send what comes after anchor."""
        t, b, ib = Tracker(), eddn.Builder(), inara.Builder()
        state: dict = {}
        horizon = time.time() - INARA_WINDOW

        def one(ev):
            cur = ev['_cursor']
            tr = self._track_names(fid, ev, t)
            clean = {k: v for k, v in ev.items() if not k.startswith('_')}
            try:
                if beta(tr.gameversion):
                    return
                if service == 'inara':
                    if (_epoch(ev.get('timestamp', '')) or 0) >= horizon:
                        for i, (n, data) in enumerate(ib.events(clean)):
                            if n in INARA_STATE:
                                self._keep_state(state, n, data, ev.get('timestamp', ''), (cur, i))
                elif anchor is not None and cur > anchor:
                    self._send(fid, clean, tr, b, ib, None, {service}, cur)
            finally:
                b.track(ev)
                ib.track(ev)

        w = self._read(fid, one)
        with self.feed_lock:
            w.poll()
            last = self.latest.get(fid, '')
            if service == 'inara':
                self._send_state(fid, state, t)
            self._arm(service, fid, anchor if anchor is not None else last)

    def _track_names(self, fid: str, ev: dict, t: Tracker) -> Tracker:
        t.update(ev)
        if ev.get('event') in ('Commander', 'LoadGame') and (ev.get('Name') or ev.get('Commander')):
            self.names.setdefault(fid, ev.get('Name') or ev.get('Commander'))
        cur = ev.get('_cursor')
        if cur and cur > self.latest.get(fid, ''):
            self.latest[fid] = cur
        return t

    @staticmethod
    def _keep_state(state: dict, name: str, data, ts: str, order) -> None:
        """The newest value of each piece of state: per ship, suit loadout, engineer and faction, else per event."""
        if name in ('setCommanderShip', 'addCommanderShip', 'delCommanderShip') and isinstance(data, dict):
            sid = data.get('shipGameID')
            prev = state.get(('ship', sid))
            if name == 'delCommanderShip':
                state[('ship', sid)] = (order, name, data, ts)
                state.pop(('loadout', sid), None)
            elif name == 'setCommanderShip' or prev is None or prev[1] == 'delCommanderShip':
                merged = {**(prev[2] if prev and prev[1] == 'setCommanderShip' else {}), **data}
                state[('ship', sid)] = (order, 'setCommanderShip', merged, ts)
        elif name == 'setCommanderShipLoadout' and isinstance(data, dict):
            state[('loadout', data.get('shipGameID'))] = (order, name, data, ts)
        elif name in ('setCommanderSuitLoadout', 'updateCommanderSuitLoadout', 'delCommanderSuitLoadout'):
            lid = data.get('loadoutGameID')
            prev = state.get(('suit', lid))
            if name == 'updateCommanderSuitLoadout' and prev and prev[1] == 'setCommanderSuitLoadout':
                state[('suit', lid)] = (order, prev[1], {**prev[2], **data}, ts)
            elif name != 'updateCommanderSuitLoadout' or prev is None:
                state[('suit', lid)] = (order, name, data, ts)
        elif name in ('setCommanderRankEngineer', 'setCommanderReputationMinorFaction'):
            k = 'engineerName' if name == 'setCommanderRankEngineer' else 'minorfactionName'
            for x in data if isinstance(data, list) else [data]:
                if isinstance(x, dict) and x.get(k):
                    state[(name, x[k])] = (order, name, x, ts)
        else:
            state[name] = (order, name, data, ts)

    def _send_state(self, fid: str, state: dict, t: Tracker) -> None:
        name = self.names.get(fid)
        if not name or not state:
            return
        out, groups = [], {}
        for key, (order, n, data, ts) in state.items():
            if isinstance(key, tuple) and key[0] in ('setCommanderRankEngineer', 'setCommanderReputationMinorFaction'):
                g = groups.setdefault(n, [order, [], ts])
                g[0], g[2] = max(g[0], order), max(g[2], ts)
                g[1].append(data)
            else:
                out.append((order, n, data, ts))
        out += [(o, n, items, ts) for n, (o, items, ts) in groups.items()]
        out.sort(key=lambda x: x[0])
        if t.system and out:
            loc = {'starsystemName': t.system}
            if t.pos:
                loc['starsystemCoords'] = t.pos
            if t.station:
                loc['stationName'] = t.station
            if isinstance(t.market, int):
                loc['marketID'] = t.market
            out.append((out[-1][0], 'setCommanderTravelLocation', loc, out[-1][3]))
        s = self._sender('inara')
        for i, (order, n, data, ts) in enumerate(out):
            s.push(fid, (name,), {'eventName': n, 'eventTimestamp': ts, 'eventData': data},
                   order[0] if i == len(out) - 1 else None)

    def _arm(self, service: str, fid: str, mark: str) -> None:
        """Inara's mark goes to mark even past what it has accepted: its catch-up is state, not the log."""
        if self.config(self.settings, fid, service)['enabled']:
            if self.marks.get(service, fid) is None:
                self.marks.arm(service, fid, mark)
            elif service == 'inara':
                self.marks.set(service, fid, mark)
        with self.lock:
            self.pending.discard((service, fid))

    def _track(self, fid: str, ev: dict) -> Tracker:
        t = self.trackers.setdefault(fid, Tracker())
        t.update(ev)
        if ev.get('event') in ('Commander', 'LoadGame'):
            name = ev.get('Name') or ev.get('Commander')
            if name:
                self.names[fid] = name
        return t

    def observe(self, fid: str, ev: dict) -> None:
        """An event from the history import: tracked, and sent to services whose mark it is past."""
        self.feed(fid, ev, None, live=False)

    def live(self, fid: str, ev: dict, journal_dir: Path | None = None) -> None:
        """An event read after the history import."""
        self.feed(fid, ev, journal_dir, live=True)

    def feed(self, fid: str, ev: dict, journal_dir: Path | None, live: bool) -> None:
        with self.feed_lock:
            self._feed(fid, ev, journal_dir, live)

    def _feed(self, fid: str, ev: dict, journal_dir: Path | None, live: bool) -> None:
        t = self._track(fid, ev)
        b = self.builders.setdefault(fid, eddn.Builder())
        ib = self.inara.setdefault(fid, inara.Builder())
        cur = ev.get('_cursor') if isinstance(ev.get('_cursor'), str) else None
        try:
            if not beta(t.gameversion):
                due = {s for s in SENDERS if self._due(s, fid, cur, live)}
                if due:
                    clean = {k: v for k, v in ev.items() if not k.startswith('_')}
                    self._send(fid, clean, t, b, ib, journal_dir if live else None, due, cur)
                if live:
                    self._capi(fid, ev, t)
        finally:
            b.track(ev)
            ib.track(ev)
            if cur and cur > self.latest.get(fid, ''):
                self.latest[fid] = cur

    def _capi(self, fid: str, ev: dict, t: Tracker) -> None:
        """Docked: the station's market, outfitting and shipyard from CAPI, and a fleet carrier's bartender, to EDDN."""
        if ev.get('event') != 'Docked' or beta(t.gameversion) or not isinstance(ev.get('MarketID'), int):
            return
        if not (self.config(self.settings, fid, 'capi')['enabled'] and self.config(self.settings, fid, 'eddn')['enabled']
                and self.names.get(fid)):
            return
        c = self.capi.get(fid)
        if c is None:
            c = self.capi[fid] = capi.Client(capi.Store(fid, self.capi_root), self.capi_base)
        if not c.store.signed_in():
            return
        services = {str(x).lower() for x in ev.get('StationServices') or []}
        want = {'market': 'commodities' in services or ev.get('StationType') == 'FleetCarrier',
                'shipyard': bool(services & {'outfitting', 'shipyard'})}
        threading.Thread(target=self._station, args=(fid, c, ev['MarketID'], ev.get('StationType'), want),
                         daemon=True, name='edcmdr-capi').start()

    def _station(self, fid: str, c: 'capi.Client', mid: int, kind, want: dict) -> None:
        time.sleep(CAPI_DELAY)
        got = {}
        for ep, on in want.items():
            if not on:
                continue
            try:
                got[ep] = c.get(ep)
            except (capi.SignInNeeded, OSError, ValueError) as e:
                log.info('CAPI %s for %s: %s', ep, fid, e)
        b = self.builders.get(fid)
        name = self.names.get(fid)
        if b is None or not name or b.docked_id != mid:
            return
        when = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        s = self._sender('eddn')
        for ref, msg, gv in b.capi(got.get('market'), got.get('shipyard'), mid, when):
            s.push(fid, ('',), {'$schemaRef': ref, 'header': self._capi_header(name, gv), 'message': msg})
        if kind == 'FleetCarrier' and got.get('market') is not None:
            msg = capi.fcmaterials(got['market'], mid, when)
            if msg is None:
                return
            h = eddn.digest(msg['Items'])
            if self.capi_seen.get(fid) == f'{mid}:{h}':
                return
            self.capi_seen[fid] = f'{mid}:{h}'
            s.push(fid, ('',), {'$schemaRef': eddn.schema('fcmaterials_capi', 1),
                                'header': self._capi_header(name, 'CAPI-Live-market'), 'message': b._flags(msg)})

    @staticmethod
    def _capi_header(name: str, gv: str) -> dict:
        return {'uploaderID': name, 'softwareName': NAME, 'softwareVersion': VERSION, 'gameversion': gv, 'gamebuild': ''}

    def _send(self, fid: str, ev: dict, t: Tracker, b: eddn.Builder, ib: inara.Builder, journal_dir: Path | None,
              due: set[str], cur: str | None) -> None:
        name = self.names.get(fid)
        if 'eddn' in due and name and t.gameversion:
            msgs = b.messages(ev, journal_dir)
            if msgs:
                s = self._sender('eddn')
                header = {'uploaderID': name, 'softwareName': NAME, 'softwareVersion': VERSION,
                          'gameversion': t.gameversion, 'gamebuild': t.build}
                for i, (ref, msg) in enumerate(msgs):
                    s.push(fid, ('',), {'$schemaRef': ref, 'header': header, 'message': msg},
                           cur if i == len(msgs) - 1 else None)
        if 'edsm' in due and name and t.gameversion and ev.get('event') not in EDSM_SKIP:
            self._sender('edsm').push(fid, (name, t.gameversion, t.build), t.annotate(ev), cur)
        if 'edastro' in due and ev.get('event') in EDASTRO_FALLBACK | self._sender('edastro').interest:
            self._sender('edastro').push(fid, ('',), ev, cur)
        if 'inara' in due and name:
            evs = ib.events(ev, journal_dir)
            s = self._sender('inara')
            for i, (n, data) in enumerate(evs):
                s.push(fid, (name,), {'eventName': n, 'eventTimestamp': ev.get('timestamp', ''), 'eventData': data},
                       cur if i == len(evs) - 1 else None)

    def status(self) -> dict[str, str]:
        return {k: s.status for k, s in self.senders.items()}

    def shutdown(self) -> None:
        for s in list(self.senders.values()):
            s.shutdown()
