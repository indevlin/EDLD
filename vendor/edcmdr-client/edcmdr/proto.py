"""Signed pushes to EDCMDR and verification of its signed replies."""
import hashlib
import ipaddress
import json
import os
import platform
import secrets
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from . import NAME, VERSION, keys
from .config import SPEC

DEFAULT_SERVER = 'https://edcmdr.com'
TIMEOUT = 20


class ProtoError(Exception):
    """A refusal from the server (code, message) or a transport failure (code 'net' / 'reply')."""

    def __init__(self, code: str, message: str, status: int = 0, extra: dict | None = None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.extra = extra or {}


def server_url() -> str:
    return os.environ.get('EDCMDR_SERVER', DEFAULT_SERVER).rstrip('/')


def _loopback(host: str) -> bool:
    try:
        return all(ipaddress.ip_address(a[4][0]).is_loopback for a in socket.getaddrinfo(host, None))
    except (OSError, ValueError):
        return False


def _check_url(url: str) -> None:
    u = urllib.parse.urlsplit(url)
    if u.scheme == 'https':
        return
    if u.scheme == 'http' and u.hostname and _loopback(u.hostname):
        return
    raise ProtoError('net', 'The server address must use https.')


class Client:
    def __init__(self, base: str | None = None):
        self.base = base or server_url()
        _check_url(self.base)
        self.build = keys.build_key()
        self.server_keys = keys.server_keys()
        self.clock_offset = 0
        self.last_seq = 0
        self.ctx = ssl.create_default_context()
        self._lock = threading.Lock()

    @property
    def official(self) -> bool:
        return self.build is not None

    def _open(self, req: urllib.request.Request) -> tuple[int, bytes, dict]:
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=self.ctx))
        if not req.has_header('User-agent'):
            req.add_header('User-Agent', f'{NAME}/{VERSION}')
        try:
            with opener.open(req, timeout=TIMEOUT) as r:
                return r.status, r.read(1 << 20), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(1 << 20), dict(e.headers)
        except (urllib.error.URLError, OSError) as e:
            raise ProtoError('net', f'Cannot reach EDCMDR: {getattr(e, "reason", e)}') from e

    def _verify(self, body: bytes, headers: dict, status: int = 0) -> dict:
        h = {k.lower(): v for k, v in headers.items()}
        kid = h.get('x-edcmdr-server', '')
        if not kid:
            via = h.get('server', '') or 'unknown'
            raise ProtoError('reply', f'The reply did not come from EDCMDR (HTTP {status} from {via}, unsigned).')
        pub = self.server_keys.get(kid)
        if pub is None:
            known = ', '.join(self.server_keys) or 'none: this build has no pinned server key'
            raise ProtoError('reply', f'The reply was signed by key {kid}, which this build does not know (known: {known}).')
        try:
            pub.verify(keys.unb64u(h.get('x-edcmdr-reply-sig', '')), body)
        except (InvalidSignature, ValueError) as e:
            raise ProtoError('reply', 'The reply signature does not match.') from e
        try:
            j = json.loads(body)
        except ValueError as e:
            raise ProtoError('reply', 'The reply is not JSON.') from e
        if not isinstance(j, dict):
            raise ProtoError('reply', 'The reply is not an object.')
        return j

    def frontier_token(self, url: str, form: dict) -> str:
        """Exchange Frontier's one-time code at its token endpoint, from this computer. Returns the access token."""
        _check_url(url)
        req = urllib.request.Request(url, data=urllib.parse.urlencode(form).encode(), method='POST', headers={
            'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'})
        status, body, _ = self._open(req)
        try:
            j = json.loads(body)
        except ValueError:
            j = None
        j = j if isinstance(j, dict) else {}
        tok = j.get('access_token')
        if status != 200 or not isinstance(tok, str) or not tok:
            why = j.get('error_description') or j.get('error') or f'HTTP {status}'
            raise ProtoError('frontier', f'Frontier refused the sign-in ({why}).', status)
        return tok

    def hello(self) -> dict:
        n = keys.b64u(secrets.token_bytes(18))
        status, body, headers = self._open(urllib.request.Request(f'{self.base}/api/v1/hello?n={n}'))
        j = self._verify(body, headers, status)
        if j.get('n') != n:
            raise ProtoError('reply', 'The reply does not answer this request.')
        if isinstance(j.get('time'), int):
            self.clock_offset = j['time'] - int(time.time())
        return j

    def _seq(self) -> int:
        self.last_seq = max(self.last_seq + 1, int(time.time() * 1000))
        return self.last_seq

    def push(self, key: Ed25519PrivateKey, fid: str, kind: str, body: dict) -> dict:
        with self._lock:
            return self._push(key, fid, kind, body)

    def _push(self, key: Ed25519PrivateKey, fid: str, kind: str, body: dict) -> dict:
        if self.build is None:
            raise ProtoError('build', 'This is not an official build; it cannot publish to EDCMDR.')
        env = {'v': SPEC['protocol'], 'kind': kind, 'key': keys.b64u(keys.raw_pub(key)), 'fid': fid,
               'ts': int(time.time()) + self.clock_offset, 'seq': self._seq(),
               'client': {'name': NAME, 'version': VERSION, 'os': platform.system().lower()}, 'body': body}
        raw = json.dumps(env, separators=(',', ':'), ensure_ascii=False).encode()
        if len(raw) > SPEC['limits']['body_bytes']:
            raise ProtoError('size', 'This push is larger than the server accepts.')
        build_id = keys.key_id(keys.raw_pub(self.build))
        req = urllib.request.Request(f'{self.base}/api/v1/ingest', data=raw, method='POST', headers={
            'Content-Type': 'application/json',
            'User-Agent': f'{NAME}/{VERSION}',
            'X-EDCMDR-Sig': keys.b64u(key.sign(raw)),
            'X-EDCMDR-Build': f'{build_id}.{keys.b64u(self.build.sign(raw))}',
        })
        status, body_bytes, headers = self._open(req)
        j = self._verify(body_bytes, headers, status)
        if j.get('re') != keys.b64u(hashlib.sha256(raw).digest())[:22]:
            raise ProtoError('reply', 'The reply does not answer this push.')
        if not j.get('ok'):
            if j.get('code') == 'clock' and isinstance(j.get('server_time'), int):
                self.clock_offset = j['server_time'] - int(time.time())
            raise ProtoError(str(j.get('code', 'server')), str(j.get('message', 'Refused.')), status, j)
        return j
