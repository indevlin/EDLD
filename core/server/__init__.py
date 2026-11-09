"""core/server — EDLD's server mode, for the EDAM mobile client.

Modules
-------
identity   the server's key and certificate, and fingerprints
pairing    one-time pairing tickets, the paired-device registry, pairing links
protocol   message framing and the snapshot/panel model sent to devices
service    the listener, per-connection handling, and change publishing

See docs/SERVER.md for the protocol and the security model.
"""

PROTOCOL_VERSION = 1
