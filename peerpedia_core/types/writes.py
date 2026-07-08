# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Abstract write metadata — storage-agnostic, no IO.

Bundles entity data, content, and commit provenance into value objects
so storage protocols receive complete write payloads in one parameter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from peerpedia_core.crypto import SigningKey
from peerpedia_core.types.entities import User, UserId

if TYPE_CHECKING:
    from peerpedia_core.types.entities import Article
    from peerpedia_core.types.scores import Scores


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
            user=User(id=UserId(id="alice-1"), name="Alice"),
        )
        storage.write("article-1", data, commit)
    """

    signer: SigningKey
    """Private key that signs the write."""

    message: str
    """Human-readable description of the change."""

    user: User
    """Public identity — display name and public key."""


@dataclass(frozen=True)
class ArticleWrite:
    """Complete write payload for an article — metadata + body + provenance.

    Backends use this to write both content and frontmatter (title,
    abstract, authors, status) into the SOT as a single bundled operation.
    """

    article: Article
    """Full article entity — metadata fields populate git frontmatter."""

    content: str
    """Raw body text (markdown, typst, etc.)."""

    commit: CommitData | None = None
    """Who wrote this and why (optional — metadata writes may skip signing)."""


@dataclass(frozen=True)
class ReviewWrite:
    """Complete write payload for a review — scores + body + provenance.

    Backends serialize *scores* to JSON and append *content* to the
    review thread as a single logical write.
    """

    reviewer_id: UserId
    """Who is submitting the review."""

    scores: Scores
    """Dimension scores — backend serializes to JSON."""

    content: str = ""
    """Review thread body text."""

    scope: str = ""
    """Review scope label (e.g. \"sedimentation\", \"published\")."""

    commit: CommitData | None = None
    """Who wrote this and why."""
