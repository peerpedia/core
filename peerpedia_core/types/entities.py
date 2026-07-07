# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Core entities — frozen, storage-agnostic, no IO.

Each type carries only its essential identity.  Version identifiers
(commit hash, revision number, etc.) are storage-layer concerns and
do not belong here.  Status values are opaque strings — the lifecycle
plugin defines what they mean.

Dereference chain
-----------------
::

    ArticleId.deref_meta(storage)     ──→  Article       (cheap)
    ArticleId.deref_content(storage)  ──→  ContentRef    (cheap)
    Article.deref()                   ──→  ContentRef|None (pure field access)
    ContentRef.deref(storage)         ──→  str           (lazy, expensive)
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from peerpedia_core.types.scores import Scores

if TYPE_CHECKING:
    from peerpedia_core.protocols.storage import (
        ArticleContentStorage,
        ArticleMetaStorage,
    )
    from peerpedia_core.protocols.user_storage import UserStorage


# ═══════════════════════════════════════════════════════════════════════════
# Dereference chain — the pointer hierarchy
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ArticleId:
    """A pointer into storage — ``&ArticleId`` yields an ``Article``."""

    id: str

    def deref_meta(self, meta: ArticleMetaStorage) -> Article:
        """&id → Article metadata (cheap)."""
        return meta.read(self)

    def deref_content(self, content: ArticleContentStorage) -> ContentRef:
        """&id → content storage path (cheap)."""
        return content.read(self)


@dataclass(frozen=True)
class UserId:
    """A user's unique identifier — opaque wrapper."""

    id: str

    def deref(self, users: UserStorage) -> User:
        """&id → User (cheap)."""
        return users.read(self)


@dataclass(frozen=True)
class ReviewId:
    """A review's unique identifier — opaque wrapper."""

    id: str


@dataclass(frozen=True)
class Article:
    """A unit of knowledge — the central entity of the system.

    Carries structured metadata and a pointer to body content.
    Ownership and lifecycle are external concerns.
    """

    id: ArticleId
    title: str
    status: str                          # opaque — lifecycle plugin defines values
    authors: tuple[str, ...] = ()        # objective authors, reconstructed from git
    abstract: str | None = None
    keywords: tuple[str, ...] = ()
    bib_data: BibData | None = None      # structured bibliographic metadata
    content_ref: ContentRef | None = None  # second-level dereference target
    score: Scores | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def deref(self) -> ContentRef | None:
        """&article → content storage path (second-level dereference)."""
        return self.content_ref

    def to_dict(self) -> dict:
        """Article → JSON-serializable dict."""
        from dataclasses import asdict

        d: dict[str, object] = {
            "id": self.id.id,
            "title": self.title,
            "status": self.status,
            "authors": list(self.authors),
            "abstract": self.abstract,
            "keywords": list(self.keywords),
            "content_ref": self.content_ref.ref if self.content_ref else None,
            "score": self.score,
        }
        if self.bib_data is not None:
            d["bib_data"] = asdict(self.bib_data)
        if self.created_at is not None:
            d["created_at"] = self.created_at.isoformat()
        if self.updated_at is not None:
            d["updated_at"] = self.updated_at.isoformat()
        return {k: v for k, v in d.items() if v is not None}

    def encode(self) -> bytes:
        """Article → transport bytes (canonical JSON)."""
        import json
        return json.dumps(
            self.to_dict(), ensure_ascii=False, default=str
        ).encode("utf-8")

    @classmethod
    def decode(cls, data: bytes) -> Article:
        """Transport bytes → Article."""
        import json
        return cls.from_dict(json.loads(data.decode("utf-8")))

    @classmethod
    def from_dict(cls, d: dict) -> Article:
        """JSON dict → Article."""
        from datetime import datetime

        bib_data = None
        if "bib_data" in d:
            bd = d["bib_data"]
            bib_data = BibData(
                entry_type=bd.get("entry_type", "article"),
                cite_key=bd.get("cite_key", ""),
                journal=bd.get("journal"),
                year=bd.get("year"),
                volume=bd.get("volume"),
                number=bd.get("number"),
                pages=bd.get("pages"),
                doi=bd.get("doi"),
                issn=bd.get("issn"),
                url=bd.get("url"),
                extra=bd.get("extra", {}),
            )

        return cls(
            id=ArticleId(id=d["id"]),
            title=d["title"],
            status=d["status"],
            authors=tuple(d.get("authors", ())),
            abstract=d.get("abstract"),
            keywords=tuple(d.get("keywords", ())),
            bib_data=bib_data,
            content_ref=ContentRef(ref=d["content_ref"]) if d.get("content_ref") else None,
            score=d.get("score"),
            created_at=datetime.fromisoformat(d["created_at"]) if d.get("created_at") else None,
            updated_at=datetime.fromisoformat(d["updated_at"]) if d.get("updated_at") else None,
        )


@dataclass(frozen=True)
class ContentRef:
    """A pointer to raw body text — ``&ContentRef`` yields a ``str``."""

    ref: str

    def deref(self, content: ArticleContentStorage) -> str:
        """&ref → raw content text (lazy, possibly expensive)."""
        return content.deref_body(self)


# ═══════════════════════════════════════════════════════════════════════════
# Version control
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Version:
    """A version identifier — opaque wrapper around a backend-specific string.

    Git SHA, incremental number, UUID — callers don't care which.
    """

    id: str                              # backend-specific version string


@dataclass(frozen=True)
class OutputFormat:
    """A compiler output format — ``"html"``, ``"pdf"``, ``"latex"``, etc."""

    name: str


@dataclass(frozen=True)
class BibData:
    """Bibliographic metadata — BibLaTeX-compatible structure.

    Carries only *bibliographic* fields that live outside
    ``Article``'s core identity.  Fields shared with ``Article``
    (``title``, ``authors``, ``abstract``, ``keywords``) are **not**
    duplicated here — a complete BibLaTeX entry is assembled at the IO
    layer by merging ``Article`` + ``BibData``.
    """

    entry_type: str                      # "article", "book", "inproceedings", ...
    cite_key: str                        # e.g. "einstein1905"
    journal: str | None = None           # journaltitle in BibLaTeX
    year: str | None = None
    volume: str | None = None
    number: str | None = None
    pages: str | None = None             # "1--10"
    doi: str | None = None
    issn: str | None = None
    url: str | None = None
    extra: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class HistoryEntry:
    """One entry in an article's version history.

    Maps naturally to a ``git log`` record — version identifier, who
    made the change, when, and why.  Contains only public information
    (no private keys).
    """

    version: Version
    message: str
    user: User                           # public identity only — no SigningKey
    timestamp: datetime


@dataclass(frozen=True)
class ArticleDiff:
    """Content difference between two article versions.

    Only the body content is compared — metadata fields are
    reconstructed from git history, not diffed here.
    """

    version_a: Version
    version_b: Version
    content_diff: str                    # unified diff of body text


# ═══════════════════════════════════════════════════════════════════════════
# Other entities
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class User:
    """A peer in the network — Ed25519 identity."""

    id: UserId
    name: str
    public_key: str | None = None         # Ed25519 public key (hex)
    reputation: Scores | None = None


@dataclass(frozen=True)
class Review:
    """A peer's evaluation of an article.

    Scores use string dimension names — the scoring plugin defines
    which dimensions exist and what they mean.
    """

    id: ReviewId
    article_id: ArticleId
    reviewer_id: UserId
    scope: str = ""                       # e.g. "sedimentation", "published"
    scores: Scores = field(default_factory=Scores)
    content_ref: ContentRef | None = None  # written review text (lazy)
    created_at: datetime | None = None
