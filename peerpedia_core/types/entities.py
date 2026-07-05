# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Core entities — frozen, storage-agnostic, no IO.

Each type carries only its essential identity.  Version identifiers
(commit hash, revision number, etc.) are storage-layer concerns and
do not belong here.  Status values are opaque strings — the lifecycle
plugin defines what they mean.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Article:
    """A unit of knowledge — the central entity of the system.

    Ownership and lifecycle are external concerns.  The ``status``
    field is an opaque string whose meaning is defined by the active
    lifecycle plugin.
    """

    id: str
    title: str
    status: str                          # opaque — lifecycle plugin defines values
    authors: tuple[str, ...] = ()        # objective authors, reconstructed from git
    abstract: str | None = None
    keywords: tuple[str, ...] = ()
    score: dict[str, float] | None = None
    forked_from: str | None = None
    fork_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class Review:
    """A peer's evaluation of an article.

    Scores use string dimension names — the scoring plugin defines
    which dimensions exist and what they mean.
    """

    id: str
    article_id: str
    reviewer_id: str
    scope: str = ""                       # e.g. "sedimentation", "published"
    scores: dict[str, float] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(frozen=True)
class User:
    """A peer in the network — Ed25519 identity."""

    id: str
    name: str
    public_key: str | None = None         # Ed25519 public key (hex)
    reputation: dict[str, float] | None = None
