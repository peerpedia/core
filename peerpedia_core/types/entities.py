# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Core entities — frozen, storage-agnostic, no IO.

Each type carries only its essential identity.  Version identifiers
(commit hash, revision number, etc.) are storage-layer concerns and
do not belong here.  Status values are opaque strings — the lifecycle
plugin defines what they mean.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from peerpedia_core.types.scores import Scores


# ═══════════════════════════════════════════════════════════════════════════
# Dereference chain — the pointer hierarchy
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ArticleId:
    """An article's unique identifier — opaque wrapper."""

    id: str


@dataclass(frozen=True)
class UserId:
    """A user's unique identifier — opaque wrapper."""

    id: str


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
    format: Format | None = None           # content format (e.g. markdown, typst)
    score: Scores | None = None            # aggregate score, updated on review submission
    created_at: datetime | None = None
    updated_at: datetime | None = None

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
            "format": self.format.name if self.format else None,
            "score": dict(self.score.dimensions) if self.score else None,
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
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
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
            format=Format(name=d["format"]) if d.get("format") else None,
            score=Scores(dimensions=d["score"]) if d.get("score") else None,
            created_at=datetime.fromisoformat(d["created_at"]) if d.get("created_at") else None,
            updated_at=datetime.fromisoformat(d["updated_at"]) if d.get("updated_at") else None,
        )


@dataclass(frozen=True)
class ContentRef:
    """A pointer to raw body text — resolves via ``content.read_body(ref)``."""

    ref: str


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
class Format:
    """A content format — ``"html"``, ``"pdf"``, ``"latex"``, ``"markdown"``, etc."""

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
