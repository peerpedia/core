# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

r"""Ed25519 reference implementation — concrete SigningKey / PublicKey / KeyPair.

Requires the ``cryptography`` library (optional dependency).
Install with ``pip install peerpedia-core[ed25519]``.

Key derivation::

    password ──scrypt──→ 32-byte seed ──Ed25519──→ (private, public)
    Same password + same salt = same key pair (deterministic).

Commit signing uses git's native ``gpg.format=ssh`` with Ed25519 keys.
Verification uses the pubkey embedded in each commit message (TOFU model).
"""

from __future__ import annotations

import hashlib
import secrets

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric import ed25519
except ImportError:
    raise ImportError(
        "crypto_ed25519 requires the 'cryptography' library. "
        "Install with: pip install peerpedia-core[ed25519]"
    ) from None

from peerpedia_core.crypto import KeyPair, SigningKey, PublicKey
from peerpedia_core.exceptions import BadRequestError

# scrypt parameters — ~100ms on modern hardware, memory-hard against brute force
_SCRYPT_N = 2 ** 14  # 16384
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32

_PUBKEY_HEX_LEN = 64
_PUBKEY_BYTES = 32
_SIG_HEX_LEN = 128
_SALT_BYTES = 16


class Ed25519SigningKey(SigningKey):
    """Concrete Ed25519 private key."""

    _key: ed25519.Ed25519PrivateKey

    def __init__(self, seed_bytes: bytes | ed25519.Ed25519PrivateKey):
        if isinstance(seed_bytes, ed25519.Ed25519PrivateKey):
            self._key = seed_bytes
        else:
            self._key = ed25519.Ed25519PrivateKey.from_private_bytes(seed_bytes)

    def sign(self, data: bytes) -> bytes:
        return self._key.sign(data)

    def public_key(self) -> Ed25519PublicKey:
        return Ed25519PublicKey(self._key.public_key())

    @property
    def raw_bytes(self) -> bytes:
        return self._raw()

    def _raw(self) -> bytes:
        # private_bytes_raw needs the hazmat API
        return self._key.private_bytes_raw()  # type: ignore[attr-defined]


class Ed25519PublicKey(PublicKey):
    """Concrete Ed25519 public key."""

    _key: ed25519.Ed25519PublicKey

    def __init__(self, key_bytes: bytes | ed25519.Ed25519PublicKey):
        if isinstance(key_bytes, ed25519.Ed25519PublicKey):
            self._key = key_bytes
        else:
            self._key = ed25519.Ed25519PublicKey.from_public_bytes(key_bytes)

    def verify(self, data: bytes, signature: bytes) -> bool:
        try:
            self._key.verify(signature, data)
            return True
        except InvalidSignature:
            return False

    def fingerprint(self) -> str:
        return self._raw().hex()

    @property
    def raw_bytes(self) -> bytes:
        return self._raw()

    def _raw(self) -> bytes:
        return self._key.public_bytes_raw()  # type: ignore[attr-defined]

    @property
    def hex(self) -> str:
        return self._raw().hex()

    @classmethod
    def from_hex(cls, pubkey_hex: str) -> Ed25519PublicKey:
        if len(pubkey_hex) != _PUBKEY_HEX_LEN:
            raise BadRequestError(
                f"Expected {_PUBKEY_HEX_LEN}-char hex pubkey, got {len(pubkey_hex)}",
                field="pubkey_hex",
                bad_value=str(len(pubkey_hex)),
            )
        return cls(bytes.fromhex(pubkey_hex))


class Ed25519KeyPair(KeyPair):
    """Ready-to-use Ed25519 key pair."""

    def __init__(self, signing_key: Ed25519SigningKey, public_key: Ed25519PublicKey):
        super().__init__(signing_key, public_key)
        self.signing_key: Ed25519SigningKey = signing_key
        self.public_key: Ed25519PublicKey = public_key


# ── Factory functions ────────────────────────────────────────────────────────


def generate_key_pair() -> Ed25519KeyPair:
    """Generate a fresh Ed25519 key pair."""
    private = ed25519.Ed25519PrivateKey.generate()
    sk = Ed25519SigningKey(private)
    pk = Ed25519PublicKey(private.public_key())
    return Ed25519KeyPair(sk, pk)


def derive_key_pair(password: str, salt_hex: str) -> Ed25519KeyPair:
    """Derive an Ed25519 key pair from a password and salt.

    Deterministic: same password + same salt = same key pair.
    """
    salt = bytes.fromhex(salt_hex)
    seed = hashlib.scrypt(
        password.encode(), salt=salt,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN,
    )
    sk = Ed25519SigningKey(seed)
    pk = Ed25519PublicKey.from_hex(sk.public_key().hex)
    return Ed25519KeyPair(sk, pk)


def new_salt() -> str:
    """Generate a new random 16-byte salt, hex-encoded."""
    return secrets.token_bytes(_SALT_BYTES).hex()


def sha256_hex(data: bytes) -> str:
    """SHA-256 hash of *data*, hex-encoded.  Empty bytes → empty string."""
    if not data:
        return ""
    return hashlib.sha256(data).hexdigest()


def sign_detached(signing_key: Ed25519SigningKey, message: bytes) -> bytes:
    """Sign *message* with *signing_key*.  Returns 64-byte signature."""
    return signing_key.sign(message)


def verify_signature(public_key: Ed25519PublicKey, message: bytes, signature: bytes) -> bool:
    """Verify a detached Ed25519 signature."""
    return public_key.verify(message, signature)


def validate_pubkey_hex(pubkey_hex: str) -> bytes:
    """Return raw 32-byte public key, or raise BadRequestError."""
    if len(pubkey_hex) != _PUBKEY_HEX_LEN:
        raise BadRequestError(
            f"Expected {_PUBKEY_HEX_LEN}-char hex pubkey, got {len(pubkey_hex)}",
            field="pubkey_hex",
            bad_value=str(len(pubkey_hex)),
        )
    raw = bytes.fromhex(pubkey_hex)
    if len(raw) != _PUBKEY_BYTES:
        raise BadRequestError(
            f"Expected {_PUBKEY_BYTES}-byte pubkey, got {len(raw)}",
            field="pubkey_hex",
            bad_value=str(len(raw)),
        )
    return raw


def validate_sig_hex(sig_hex: str) -> bytes:
    """Return raw 64-byte signature, or raise BadRequestError."""
    if len(sig_hex) != _SIG_HEX_LEN:
        raise BadRequestError(
            f"Expected {_SIG_HEX_LEN}-char hex signature, got {len(sig_hex)}",
            field="sig_hex",
            bad_value=str(len(sig_hex)),
        )
    return bytes.fromhex(sig_hex)
