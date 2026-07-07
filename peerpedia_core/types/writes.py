# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Abstract write metadata — storage-agnostic, no IO.

Bundles the identity and intent behind a storage write so the
protocol doesn't scatter related parameters across the signature.
"""

from __future__ import annotations

from dataclasses import dataclass

from peerpedia_core.crypto import SigningKey
from peerpedia_core.types.entities import User


@dataclass
class CommitData:
    """Everything a storage backend needs to record *who* wrote *what* and *why*.

    ``signer`` is the cryptographic identity (private key).  ``user`` is
    the public identity (display name, public key).  They are separate
    because the private key is never stored or transmitted — it's a local
    secret the caller holds at write time.

    Examples::

        commit = CommitData(
            signer=sk,
            message="Initial submission",
            user=User(id="alice-1", name="Alice"),
        )
        storage.write("article-1", data, commit)
    """

    signer: SigningKey
    """Private key that signs the write."""

    message: str
    """Human-readable description of the change."""

    user: User
    """Public identity — display name and public key."""
