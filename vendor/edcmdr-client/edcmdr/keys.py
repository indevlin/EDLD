"""Commander keys (one per FID), the build key, and the server keys replies must be signed with."""
import base64
import hashlib
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from . import paths

# Server public keys (current, next). bin/keygen.php server prints them.
SERVER_KEYS: list[str] = [
    'qrnjVvjBGHZq9zOAkUrrxpTPy9YrvtAJXrxtvSSu60E',
]


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))


def raw_pub(priv: Ed25519PrivateKey) -> bytes:
    return priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def key_id(pub: bytes) -> str:
    return b64u(hashlib.sha256(pub).digest())[:22]


def _from_sodium_secret(s: str) -> Ed25519PrivateKey:
    raw = unb64u(s.strip())
    if len(raw) not in (32, 64):
        raise ValueError('not an Ed25519 key')
    return Ed25519PrivateKey.from_private_bytes(raw[:32])


def commander_key(fid: str) -> Ed25519PrivateKey:
    """Load or create this commander's key; stored as the 32-byte seed, mode 0600."""
    d = paths.config_dir() / 'keys'
    d.mkdir(exist_ok=True)
    if os.name != 'nt':
        os.chmod(d, 0o700)
    f = d / f'{fid}.key'
    if f.exists():
        return Ed25519PrivateKey.from_private_bytes(unb64u(f.read_text().strip()))
    k = Ed25519PrivateKey.generate()
    seed = k.private_bytes_raw()
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as fh:
        fh.write(b64u(seed) + '\n')
    return k


def drop_commander_key(fid: str) -> None:
    f = paths.config_dir() / 'keys' / f'{fid}.key'
    if f.exists():
        f.unlink()


def build_key() -> Ed25519PrivateKey | None:
    """Release builds carry it in _build_secret; source runs read $EDCMDR_BUILD_KEY or ~/.config/edcmdr/build.key."""
    try:
        from . import _build_secret  # type: ignore[attr-defined]
        return _from_sodium_secret(_build_secret.BUILD_KEY)
    except ImportError:
        pass
    env = os.environ.get('EDCMDR_BUILD_KEY')
    if env:
        return _from_sodium_secret(env)
    f = Path.home() / '.config' / 'edcmdr' / 'build.key'
    if f.exists():
        return _from_sodium_secret(f.read_text())
    return None


def server_keys() -> dict[str, Ed25519PublicKey]:
    keys = list(SERVER_KEYS)
    dev = os.environ.get('EDCMDR_DEV_SERVER_KEY')
    if dev:
        keys.append(dev)
    out = {}
    for k in keys:
        raw = unb64u(k)
        out[key_id(raw)] = Ed25519PublicKey.from_public_bytes(raw)
    return out
