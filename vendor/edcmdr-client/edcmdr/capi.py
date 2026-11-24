"""Frontier's Companion API (CAPI) from this computer, with the sign-in kept here and nowhere else.

The tokens come from Verify with Frontier when Frontier CAPI is switched on for that commander; they live in
capi/<FID>.json in the config folder (owner-only), are refreshed at Frontier's token endpoint from this
computer, and are deleted when the switch goes off or Frontier refuses the refresh.
"""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import NAME, VERSION, paths

BASE = 'https://companion.orerve.net'
TIMEOUT = 20
MARGIN = 60
COOLDOWN = {'profile': 30, 'market': 60, 'shipyard': 60, 'fleetcarrier': 120}


class SignInNeeded(Exception):
    """No usable sign-in: switch CAPI on and verify with Frontier again."""


class Store:
    """One commander's tokens on disk."""

    def __init__(self, fid: str, root: Path | None = None):
        self.path = (root or paths.config_dir() / 'capi') / f'{fid}.json'
        self.lock = threading.Lock()

    def load(self) -> dict:
        try:
            d = json.loads(self.path.read_text())
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self, d: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump(d, f)
        os.replace(tmp, self.path)

    def keep(self, tokens: dict, token_url: str, client_id: str, redirect_uri: str) -> None:
        """Save the answer of Frontier's token endpoint, as Verify with Frontier received it."""
        if not tokens.get('access_token'):
            return
        self.save({'access_token': tokens['access_token'], 'refresh_token': tokens.get('refresh_token'),
                   'expiry': time.time() + int(tokens.get('expires_in') or 7200), 'token_url': token_url,
                   'client_id': client_id, 'redirect_uri': redirect_uri})

    def forget(self) -> None:
        self.path.unlink(missing_ok=True)

    def signed_in(self) -> bool:
        return bool(self.load().get('refresh_token') or self.load().get('access_token'))


def safe(url: str) -> bool:
    """https, or http to this computer (tests)."""
    u = urllib.parse.urlsplit(url)
    return u.scheme == 'https' or (u.scheme == 'http' and u.hostname in ('127.0.0.1', 'localhost', '::1'))


def _post(url: str, form: dict) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(form).encode(), method='POST', headers={
        'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json',
        'User-Agent': f'{NAME}/{VERSION}'})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, {}


class Client:
    """CAPI for one commander: a valid token (refreshed when near expiry) and paced endpoint reads."""

    def __init__(self, store: Store, base: str = BASE):
        self.store = store
        self.base = base.rstrip('/')
        self.last: dict[str, float] = {}

    def token(self) -> str:
        with self.store.lock:
            t = self.store.load()
            if not t.get('access_token'):
                raise SignInNeeded('not signed in')
            if time.time() < t.get('expiry', 0) - MARGIN:
                return t['access_token']
            if not t.get('refresh_token') or not safe(str(t.get('token_url', ''))):
                raise SignInNeeded('the sign-in expired')
            status, j = _post(t['token_url'], {'grant_type': 'refresh_token', 'client_id': t.get('client_id', ''),
                                               'redirect_uri': t.get('redirect_uri', ''),
                                               'refresh_token': t['refresh_token']})
            if status in (400, 401) or (status == 200 and not j.get('access_token')):
                self.store.forget()
                raise SignInNeeded('Frontier ended the sign-in')
            if status != 200:
                raise OSError(f'Frontier token endpoint: HTTP {status}')
            t.update(access_token=j['access_token'], refresh_token=j.get('refresh_token', t['refresh_token']),
                     expiry=time.time() + int(j.get('expires_in') or 7200))
            self.store.save(t)
            return t['access_token']

    def get(self, endpoint: str, force: bool = False):
        """An endpoint's JSON, or None while it is still cooling down since the last read."""
        if not force and time.time() - self.last.get(endpoint, 0) < COOLDOWN.get(endpoint, 60):
            return None
        self.last[endpoint] = time.time()
        req = urllib.request.Request(f'{self.base}/{endpoint}', headers={
            'Authorization': f'Bearer {self.token()}', 'User-Agent': f'{NAME}/{VERSION}', 'Accept': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read() or b'null')
        except urllib.error.HTTPError as e:
            if e.code in (401, 422):
                with self.store.lock:
                    t = self.store.load()
                    t['expiry'] = 0
                    self.store.save(t)
            raise OSError(f'CAPI /{endpoint}: HTTP {e.code}') from e


def fcmaterials(market: dict, docked_id, timestamp: str) -> dict | None:
    """The fcmaterials_capi/1 message from a fleet carrier's /market answer, when docked there."""
    if not isinstance(market, dict):
        return None
    micro = (market.get('orders') or {}).get('onfootmicroresources')
    if micro is None or not isinstance(market.get('id'), int) or market['id'] != docked_id:
        return None

    def strip(obj):
        if isinstance(obj, list):
            return [{k: v for k, v in i.items() if k != 'locName'} for i in obj if isinstance(i, dict)]
        if isinstance(obj, dict):
            return {k: ({kk: vv for kk, vv in v.items() if kk != 'locName'} if isinstance(v, dict) else v)
                    for k, v in obj.items()}
        return obj

    return {'timestamp': timestamp, 'event': 'FCMaterials', 'MarketID': market['id'], 'CarrierID': str(market.get('name', '')),
            'Items': {'purchases': strip(micro.get('purchases', [])), 'sales': strip(micro.get('sales', []))}}
