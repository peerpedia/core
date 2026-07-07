# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""P2P auth protocol — sign and verify request headers.

Core defines the interface; the Ed25519 implementation (or any
alternative) lives in a backend package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from peerpedia_core.types.entities import UserId


@dataclass
class AuthResult:
    """Result of auth verification — check ``ok``, read ``reason`` on failure."""

    ok: bool
    user_id: UserId = field(default_factory=lambda: UserId(id=""))
    pubkey_hex: str = ""
    reason: str = ""


class AuthProvider(Protocol):
    """Sign outgoing HTTP requests and verify incoming ones.

    The signature covers ``<method>:<path>:<uid>:<ts>:<body_hash>``,
    binding the auth header to a specific request to prevent replay
    attacks.  The pubkey is embedded in the header so verification
    does not need a database lookup (TOFU model).

    Header format::

        Authorization: Peerpedia <uid>:<pubkey>:<ts>:<body_hash>:<sig>

    The private key is local — the caller holds it and passes it to
    ``sign()``.  The protocol never stores or transmits it.
    """

    def sign(
        self,
        method: str,                # HTTP method — "GET", "POST", etc.
        path: str,                  # request path — "/articles/123"
        user_id: UserId,            # who is making the request, embedded in header
        private_key: bytes,         # Ed25519 private key (32 raw bytes)
        pubkey_hex: str,            # Ed25519 public key (64 hex chars)
        body: bytes = b"",          # HTTP body (empty for GET)
    ) -> str:
        """Sign a request.  Returns the ``Authorization`` header value."""
        ...

    def verify(
        self,
        header_value: str,  # the ``Authorization`` header from the request
        method: str,        # HTTP method used in the request
        path: str,          # request path used in the request
        body: bytes = b"",  # HTTP body of the request
    ) -> AuthResult:
        """Verify an incoming request.  No DB lookup needed (TOFU)."""
        ...
