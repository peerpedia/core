# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Cryptographic identity protocols — abstract, algorithm-agnostic.

Core does not know the concrete signature scheme (Ed25519, RSA, etc.).
It only knows these two interfaces.  The implementation lives in a
separate package or is injected at startup.
"""

from __future__ import annotations

from typing import Protocol


class SigningKey(Protocol):
    """A private key that can produce signatures."""

    def sign(self, data: bytes) -> bytes:
        """Return a detached signature over *data*."""
        ...

    def public_key(self) -> PublicKey:
        """Return the corresponding public key."""
        ...


class PublicKey(Protocol):
    """A public key that can verify signatures."""

    def verify(self, data: bytes, signature: bytes) -> bool:
        """Return True if *signature* is valid for *data*."""
        ...

    def fingerprint(self) -> str:
        """Return a short hex string identifying this key."""
        ...


class KeyPair:
    """A SigningKey + PublicKey bundle — returned by key generators."""

    def __init__(self, signing_key: SigningKey, public_key: PublicKey):
        self.signing_key = signing_key
        self.public_key = public_key
