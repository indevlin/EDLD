"""
tests/test_server_fingerprint_vector.py — the pairing fingerprint, pinned.

The `fp` in a pairing link is the one value every implementation has to derive
identically: EDLD here, EDAM in Kotlin from ``X509Certificate.publicKey.encoded``,
``scripts/edld_client.py`` in Python again.  A client that computes it even
slightly differently simply cannot pair, and the handshake gives no hint why —
so the computation is pinned to a fixed certificate rather than left as prose in
docs/SERVER.md for each side to interpret.

The certificate below is the vector published in docs/SERVER.md.  If this test
fails, either the computation changed or the doc is now wrong; fix the one that
moved, and keep both in step.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest.importorskip("cryptography")

from cryptography import x509                                       # noqa: E402
from cryptography.hazmat.primitives import serialization            # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec            # noqa: E402

from core.server import identity                                    # noqa: E402

# A self-signed EC P-256 certificate of the shape `edld -s` generates.
VECTOR_PEM = """\
-----BEGIN CERTIFICATE-----
MIIBNzCB36ADAgECAgUA7R1+VzAKBggqhkjOPQQDAjAbMRkwFwYDVQQDDBBFRExE
IHRlc3QgdmVjdG9yMB4XDTIwMDEwMTAwMDAwMFoXDTQ1MDEwMTAwMDAwMFowGzEZ
MBcGA1UEAwwQRURMRCB0ZXN0IHZlY3RvcjBZMBMGByqGSM49AgEGCCqGSM49AwEH
A0IABNOgtrqE9BPoDo38YiNtN95jJc8T123lF0fVPiSlXsn3uE7eluiJYh/qQEVH
YwICy0bRfYxdWAETWDP6JGmc/wmjEDAOMAwGA1UdEwEB/wQCMAAwCgYIKoZIzj0E
AwIDRwAwRAIgRrtLDXxKo6c8nLR3AUS2pyomSqcnrKc7B5RQdP/NZyACIEwZJrds
1dlkD5jdq4+NpNO5yMjOQF4CqmECm8oPy/r4
-----END CERTIFICATE-----
"""

EXPECTED_FP = "Ww-k_3c2NkupB5RICcUmQS8JmOb5ZxqdzmSxPeWgqFA"
EXPECTED_SHORT = "Ww-k_3c2"

# sha256 over the whole DER certificate — the value someone reaching for the
# obvious computation gets.  Asserted only to prove it is NOT the pin.
WHOLE_CERT_SHA256 = "341bf80add5df967e25f72e4bf0c22ee560cfbae36142ff98f8bde7ec1422d8d"


@pytest.fixture(scope="module")
def cert_der() -> bytes:
    cert = x509.load_pem_x509_certificate(VECTOR_PEM.encode())
    return cert.public_bytes(serialization.Encoding.DER)


def test_fingerprint_matches_the_published_vector(cert_der: bytes) -> None:
    assert identity.spki_fingerprint_der(cert_der) == EXPECTED_FP


def test_fingerprint_is_43_characters(cert_der: bytes) -> None:
    """EDAM rejects a pairing link whose `fp` is not exactly 43 characters."""
    assert len(identity.spki_fingerprint_der(cert_der)) == 43


def test_fingerprint_is_base64url_without_padding(cert_der: bytes) -> None:
    fp = identity.spki_fingerprint_der(cert_der)
    assert "=" not in fp
    assert "+" not in fp and "/" not in fp


def test_short_id_is_the_first_eight(cert_der: bytes) -> None:
    assert identity.short_id(identity.spki_fingerprint_der(cert_der)) == EXPECTED_SHORT


def test_pin_is_over_the_spki_not_the_certificate(cert_der: bytes) -> None:
    """The near-miss computation must not accidentally agree."""
    whole = hashlib.sha256(cert_der).hexdigest()
    assert whole == WHOLE_CERT_SHA256
    assert identity.b64url(bytes.fromhex(whole)) != identity.spki_fingerprint_der(cert_der)


def test_vector_still_resembles_what_edld_generates(cert_der: bytes) -> None:
    """A vector on some other key type would stop guarding the real path."""
    key = x509.load_der_x509_certificate(cert_der).public_key()
    assert isinstance(key, ec.EllipticCurvePublicKey)
    assert key.curve.name == "secp256r1"


def test_reissue_over_the_same_key_keeps_the_pin(cert_der: bytes) -> None:
    """Why the pin is on the key: a fresh certificate must not break pairing.

    Re-signs the vector's public key into a different certificate — new serial,
    new validity, new subject — and expects the same fingerprint.
    """
    import datetime as dt

    from cryptography.hazmat.primitives import hashes

    signer = ec.generate_private_key(ec.SECP256R1())
    original = x509.load_der_x509_certificate(cert_der)
    name = x509.Name(
        [x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "EDLD on some other host")]
    )
    now = dt.datetime.now(dt.timezone.utc)
    reissued = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(original.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(signer, hashes.SHA256())
    )
    assert reissued.public_bytes(serialization.Encoding.DER) != cert_der
    assert (
        identity.spki_fingerprint_der(reissued.public_bytes(serialization.Encoding.DER))
        == EXPECTED_FP
    )
