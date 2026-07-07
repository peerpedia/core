# PeerPedia Core — Full Source Dump

**Total: 2229 lines** (1662 source + 567 tests)
**Architecture**: Clean Architecture — entities → protocols → engine → facade
**Pattern**: Meta/Content split for articles and reviews (DB cache + git SOT)

---


### peerpedia_core/types/scores.py (31 lines)
```python
# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Score abstraction — a set of named dimensions with float values.

Dimension names are NOT hardcoded here.  The scoring plugin defines
which dimensions exist (e.g. five dimensions, three dimensions, etc.).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Scores:
    """A multi-dimensional score with named dimensions.

    >>> s = Scores(dimensions={"originality": 4.0, "rigor": 3.5})
    >>> s.average()
    3.75
    """

    dimensions: Mapping[str, float] = field(default_factory=dict)

    def average(self) -> float:
        if not self.dimensions:
            return 0.0
        return sum(self.dimensions.values()) / len(self.dimensions)

    def get(self, dim: str, default: float = 0.0) -> float:
        return self.dimensions.get(dim, default)
```

### peerpedia_core/types/queries.py (45 lines)
```python
# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Abstract query types — storage-agnostic, no IO.

Storage backends translate these into their native query language
(SQL, filesystem globs, API calls).  Fields are optional and AND-ed
together.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ArticleQuery:
    """Filter conditions for listing articles.

    All fields are optional AND-ed together.  An empty query returns
    recent articles.  Each storage backend translates this into its
    native query mechanism.

    Examples::

        ArticleQuery()                                          # all, recent first
        ArticleQuery(statuses={"published", "sedimentation"})   # multiple statuses
        ArticleQuery(search="quantum")                          # full-text search
        ArticleQuery(statuses={"published"}, search="gravity", limit=10)
    """

    statuses: frozenset[str] | None = None
    """Filter by status values (OR within set, AND with other filters)."""

    search: str | None = None
    """Case-insensitive substring match in title and abstract."""

    id_prefix: str | None = None
    """Filter articles whose ID starts with this prefix."""

    limit: int | None = None
    """Max results to return."""

    offset: int = 0
    """Results offset for pagination."""
```

### peerpedia_core/types/writes.py (44 lines)
```python
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
```

### peerpedia_core/types/entities.py (252 lines)
```python
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
            format=Format(name=d["format"]) if d.get("format") else None,
            score=d.get("score"),
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
```

### peerpedia_core/types/__init__.py (11 lines)
```python
# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Shared types — pure, no IO."""

from peerpedia_core.types.entities import Article, ArticleDiff, ArticleId, BibData, ContentRef, HistoryEntry, Format, Review, ReviewId, User, UserId, Version
from peerpedia_core.types.queries import ArticleQuery
from peerpedia_core.types.scores import Scores
from peerpedia_core.types.writes import CommitData

__all__ = ["Article", "ArticleDiff", "ArticleId", "ArticleQuery", "BibData", "CommitData", "ContentRef", "HistoryEntry", "Format", "Review", "ReviewId", "Scores", "User", "UserId", "Version"]
```

### peerpedia_core/exceptions.py (89 lines)
```python
# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

r"""Semantic exceptions — pure business logic, no IO concepts.

Exception hierarchy
-------------------
PeerpediaError (base)       ``code: str``  ``detail: str``  ``context: dict``
  ├── NotFoundError          resource_type, resource_id
  ├── NotAuthorizedError     permission, resource_type, resource_id
  ├── ConflictError          conflicting_entity
  └── BadRequestError        field, bad_value
"""


class PeerpediaError(Exception):
    """Base for all PeerPedia business-logic errors.

    Attributes:
        detail: Human-readable description (always present).
        code:  Machine-readable error code (default ``"ERROR"``).
        context:  Arbitrary key-value pairs for structured error output.
    """

    code: str = "ERROR"

    def __init__(self, detail: str = "", **context):
        if "code" in context:
            self.code = context.pop("code")
        if not detail and self.code != "ERROR":
            detail = self.code
        super().__init__(detail)
        self.detail = detail
        self.context = context
        for k, v in context.items():
            setattr(self, k, v)


class NotFoundError(PeerpediaError):
    """Requested resource does not exist."""

    code = "NOT_FOUND"

    def __init__(self, detail: str = "", resource_type: str = "", resource_id: str = "", **kwargs):
        if resource_type and resource_id:
            kwargs[f"{resource_type}_id"] = resource_id
        super().__init__(detail, resource_type=resource_type, resource_id=resource_id, **kwargs)


class NotAuthorizedError(PeerpediaError):
    """User lacks permission for the requested action."""

    code = "NOT_AUTHORIZED"

    def __init__(self, detail: str = "", permission: str = "",
                 resource_type: str = "", resource_id: str = "", **kwargs):
        super().__init__(detail, permission=permission,
                         resource_type=resource_type, resource_id=resource_id, **kwargs)


class ConflictError(PeerpediaError):
    """Request conflicts with the current state of the resource."""

    code = "CONFLICT"

    def __init__(self, detail: str = "", conflicting_entity: str = "", **kwargs):
        super().__init__(detail, conflicting_entity=conflicting_entity, **kwargs)


class BadRequestError(PeerpediaError):
    """Input is invalid or missing required data."""

    code = "BAD_REQUEST"

    def __init__(self, detail: str = "", field: str = "", bad_value: str = "", **kwargs):
        super().__init__(detail, field=field, bad_value=bad_value, **kwargs)


class MergeConflictError(ConflictError):
    """Raised when a merge encounters conflicts that can't auto-resolve.

    Storage-layer concept — git-specific in the current backend,
    but the concept applies to any versioned storage.
    """

    code = "MERGE_CONFLICT"

    def __init__(self, detail: str = "", conflicting_entity: str = "", **kwargs):
        super().__init__(detail, conflicting_entity=conflicting_entity, **kwargs)
```

### peerpedia_core/crypto.py (45 lines)
```python
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
```

## Protocols (adapter interfaces)

### peerpedia_core/protocols/review_meta_storage.py (45 lines)
```python
# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Review meta storage protocol — DB index for peer evaluations.

The source of truth for review content lives in the article git repo
(see ``ReviewContentStorage``).  This protocol provides a fast-query
index rebuilt via ``reconcile_reviews()``.
"""

from __future__ import annotations

from typing import Protocol

from peerpedia_core.types.entities import ArticleId, Review, UserId, Version


class ReviewMetaStorage(Protocol):
    """Indexed review cache — fast reads, queryable.

    Typically DB-backed.  Git is the source of truth; this cache
    is rebuilt via ``reconcile_reviews()``.
    """

    def create(self, article_id: ArticleId, reviewer_id: UserId) -> Review:
        """Allocate a new review index row for *article_id* and *reviewer_id*."""
        ...

    def read(self, article_id: ArticleId, reviewer_id: UserId) -> Review:
        """Return the cached review by *reviewer_id* on *article_id*."""
        ...

    def update(
        self, article_id: ArticleId, reviewer_id: UserId, review: Review
    ) -> Version:
        """Replace the cached review — returns the article version."""
        ...

    def delete(self, article_id: ArticleId, reviewer_id: UserId) -> Version:
        """Remove the review index row — returns the article version."""
        ...

    def list(self, article_id: ArticleId) -> list[Review]:
        """Return all cached reviews for *article_id*."""
        ...
```

### peerpedia_core/protocols/review_content_storage.py (85 lines)
```python
# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Review content storage protocol — git SOT for peer evaluations.

Reviews live inside the article git repository under
``reviews/{dir_id}/``::

    reviews/{dir_id}/scores.json
    reviews/{dir_id}/threads/001.md
    reviews/{dir_id}/threads/002.md

This protocol provides CRUD for review content plus thread append/read.
Semantic operations (submit, reply) live on ``ArticleStorage``.
"""

from __future__ import annotations

from typing import Protocol

from peerpedia_core.types.entities import ArticleId, UserId, Version


class ReviewContentStorage(Protocol):
    """CRUD for review content in the article git repo.

    Each method targets the reviewer's directory under
    ``reviews/{dir_id}/`` within the article repository.

    Scores are the primary content (create / read / update).
    Thread entries are append-only (no update — each reply is a new entry).
    """

    # ── CRUD ────────────────────────────────────────────────────────────

    def create(
        self, article_id: ArticleId, reviewer_id: UserId,
    ) -> Version:
        """Initialize the review directory for *reviewer_id*."""
        ...

    def read(
        self, article_id: ArticleId, reviewer_id: UserId,
    ) -> str | None:
        """Read ``scores.json`` — return JSON text or None."""
        ...

    def update(
        self, article_id: ArticleId, reviewer_id: UserId, scores: str,
    ) -> Version:
        """Write ``scores.json`` for *reviewer_id*.  *scores* is JSON text."""
        ...

    def delete(
        self, article_id: ArticleId, reviewer_id: UserId,
    ) -> Version:
        """Remove the entire ``reviews/{dir_id}/`` directory."""
        ...

    # ── Thread (append-only) ────────────────────────────────────────────

    def append_thread_entry(
        self, article_id: ArticleId, reviewer_id: UserId,
        content: str, marker: str,
    ) -> Version:
        """Append a numbered ``threads/NNN.md`` with *marker* as commit prefix.

        *marker* is ``"[review]"`` for the initial review or
        ``"[reply]"`` for follow-up messages.
        """
        ...

    def read_thread(
        self, article_id: ArticleId, reviewer_id: UserId,
    ) -> list[str]:
        """Return all thread entry contents, ordered by filename."""
        ...

    # ── Query ───────────────────────────────────────────────────────────

    def list_reviewers(
        self, article_id: ArticleId,
    ) -> list[UserId]:
        """Return all reviewer ids that have written content for *article_id*."""
        ...
```

### peerpedia_core/protocols/user_storage.py (42 lines)
```python
# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""User storage protocol — CRUD for peer identities."""

from __future__ import annotations

from typing import Protocol

from peerpedia_core.types.entities import User, UserId


class UserStorage(Protocol):
    """CRUD for users — peer identities in the network.

    Matches the pattern of ``ArticleMetaStorage``: ``create()``
    allocates an id, ``update()`` fills in the data.
    """

    def create(self) -> UserId:
        """Allocate a new user id."""
        ...

    def read(self, key: UserId) -> User:
        """Return the user for *key*."""
        ...

    def update(self, key: UserId, user: User) -> None:
        """Replace the user record for *key*."""
        ...

    def delete(self, key: UserId) -> None:
        """Remove a user."""
        ...

    def search(self, query: str) -> list[User]:
        """Full-text search by name."""
        ...

    def list(self) -> list[User]:
        """Return all active users."""
        ...
```

### peerpedia_core/protocols/auth.py (64 lines)
```python
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
```

### peerpedia_core/protocols/authorizer.py (33 lines)
```python
# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Authorizer protocol — permission checks.

Separated from Lifecycle because authorization (who are you?)
and state transitions (what status is this article in?) are
independent concerns.  Some actions don't need auth at all
(e.g. reading a published article).
"""

from __future__ import annotations

from typing import Protocol

from peerpedia_core.types.entities import Article, User


class Authorizer(Protocol):
    """Decide whether *user* may perform *action* on *article*.

    Handlers call this BEFORE ``execute()`` — a failed auth check
    never reaches the lifecycle state machine.
    """

    def authorize(self, user: User, article: Article, action: str) -> bool:
        """Return True if *user* is allowed to perform *action*.

        The authorizer may inspect user identity, article ownership,
        maintainer status, or any other factor.  It does NOT inspect
        the article's lifecycle status — that is the lifecycle's job.
        """
        ...
```

### peerpedia_core/protocols/compiler.py (27 lines)
```python
# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Compiler protocol — render article content to output formats."""

from __future__ import annotations

from typing import Protocol

from peerpedia_core.types.entities import Format


class Compiler(Protocol):
    """Compile article content to an output format.

    The core does not know what formats are available — that is a
    plugin concern (``"html"``, ``"pdf"``, ``"latex"``, etc.).

    ::

        compiler.compile("# Title\n\nHello", Format(name="html"))
        → b"<h1>Title</h1>..."
    """

    def compile(self, content: str, fmt: Format) -> bytes:
        """Compile *content* to *fmt*, returning rendered bytes."""
        ...
```

### peerpedia_core/protocols/scoring.py (23 lines)
```python
# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""ScoringEngine protocol — the scoring plugin.

Core does not define what dimensions exist or how scores are aggregated.
The scoring plugin (in peerpedia-compute) implements this.
"""

from __future__ import annotations

from typing import Protocol

from peerpedia_core.types.entities import Review
from peerpedia_core.types.scores import Scores


class ScoringEngine(Protocol):
    """Compute aggregate scores from a collection of reviews."""

    def compute(self, reviews: list[Review]) -> Scores:
        """Aggregate *reviews* into a single Scores value."""
        ...
```

### peerpedia_core/protocols/sync.py (259 lines)
```python
# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""P2P sync protocols — transport-agnostic.

Core does not know whether sync travels over HTTP, gRPC, or smoke signals.
It only knows this interface.  Each transport backend implements these
protocols.

Serialization lives on the entity types: ``Article.encode()`` /
``Article.decode()``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TYPE_CHECKING

from peerpedia_core.types.entities import ArticleId, UserId, Version

if TYPE_CHECKING:
    from peerpedia_core.protocols.storage import ArticleStorage


# ── Monotonic boundary search ─────────────────────────────────────────────


def search_monotonic_boundary(
    probe: Callable[[int], bool | None],
    max_idx: int,
    k: int = 5,
) -> int | None:
    """k-exponential search for the first index where *probe* returns False.

    The predicate is monotonic: *probe(i)* is True for all i < boundary,
    and False for all i >= boundary.  Returns the boundary index, or
    *max_idx*+1 if all True, or ``None`` on probe failure.

    This is a generic algorithm — no domain-specific types.  Use it to
    build higher-level merge-base or bisect functions.
    """
    if max_idx < 0:
        return None

    # ── Exponential phase — find an upper bound where probe fails ──
    upper = 1
    while upper <= max_idx:
        r = probe(upper)
        if r is True:
            upper *= k
        elif r is False:
            break
        else:
            return None
    # All probes succeeded — boundary is beyond max_idx
    if upper > max_idx:
        upper = max_idx
        if probe(upper) is True:
            return max_idx + 1

    # ── Binary refinement ──
    lower = upper // k
    while lower + 1 < upper:
        mid = (lower + upper) // 2
        r = probe(mid)
        if r is True:
            lower = mid
        elif r is False:
            upper = mid
        else:
            return None
    return upper


# ── Merge-base search ─────────────────────────────────────────────────────


def find_merge_base(
    local_versions: list[Version],
    probe: Callable[[Version], bool | None],
    k: int = 5,
) -> Version | None:
    """Find the newest version shared by local and remote.

    *local_versions* is ordered newest-first (from ``history()``).
    Built on ``search_monotonic_boundary``.

    The monotonic property: "once a version is present on remote, all
    older versions are also present".  So *probe(v)* returning False
    is the "still missing" phase, and True is "present from here on".
    """
    n = len(local_versions)
    if n == 0:
        return None

    # Skip past versions remote doesn't have (local ahead of remote).
    while n > 0:
        r = probe(local_versions[0])
        if r is None:
            return None
        if r:
            break
        local_versions = local_versions[1:]
        n -= 1
    if n == 0:
        return None  # no common ancestor

    # Now local_versions[0] IS on remote.  Use the monotonic search from
    # here: True (present) → False (missing) as index increases.
    def _present(i: int) -> bool | None:
        return probe(local_versions[i])

    boundary = search_monotonic_boundary(_present, n - 1, k=k)
    if boundary is None:
        return None
    if boundary > n - 1:
        return local_versions[0]            # all present — newest is merge base
    if boundary == 0:
        return None                         # first probe after skip failed
    return local_versions[boundary - 1]     # just before first missing


# ── ArticleSync protocol ──────────────────────────────────────────────────


class ArticleSync(Protocol):
    """Bi-directional article sync between peers.

    *since* is a content version for incremental sync (``None`` = full pull).
    """

    def fetch_version(
        self, peer_url: str, article_id: ArticleId
    ) -> Version | None:
        """Get the HEAD version from *peer_url* (ultra-light probe)."""
        ...

    def push(
        self,
        peer_url: str,
        article_id: ArticleId,
        data: bytes,
        since: Version | None = None,
    ) -> Version:
        """Push *data* to *peer_url*.  *since* is the base version;
        returns the new version assigned by the receiver."""
        ...

    def pull_meta(
        self,
        peer_url: str,
        article_id: ArticleId,
        since: Version | None = None,
    ) -> bytes | None:
        """Pull metadata only from *peer_url*."""
        ...

    def pull_all(
        self,
        peer_url: str,
        article_id: ArticleId,
        since: Version | None = None,
    ) -> bytes | None:
        """Pull full article (meta + content) from *peer_url*."""
        ...


# ── ReviewSync protocol ───────────────────────────────────────────────────


class ReviewSync(Protocol):
    """Bi-directional review sync between peers.

    Reviews are synced per article — *article_id* scopes the reviews
    being pushed or pulled.
    """

    def push(
        self,
        peer_url: str,
        article_id: ArticleId,
        reviewer_id: UserId,
        data: bytes,
        since: Version | None = None,
    ) -> Version:
        """Push review *data* to *peer_url*."""
        ...

    def pull(
        self,
        peer_url: str,
        article_id: ArticleId,
        reviewer_id: UserId,
        since: Version | None = None,
    ) -> bytes | None:
        """Pull review data from *peer_url*."""
        ...


# ── Sync orchestrator ─────────────────────────────────────────────────────


def sync_article(
    sync: ArticleSync,
    storage: ArticleStorage,
    article_id: ArticleId,
    peer_url: str,
) -> Version:
    """Sync *article_id* with *peer_url* — three-way merge.

    Returns the new local HEAD version after sync.  Composes
    ``ArticleSync`` + ``ArticleContentStorage`` + ``reconcile``.
    """
    content = storage.content
    local_history = content.history(article_id)
    local_head = local_history[0].version if local_history else None

    # ── Probe remote ──
    remote_head = sync.fetch_version(peer_url, article_id)
    if remote_head is None:
        # Remote doesn't have this article — push everything
        if local_head:
            bundle = content.create_bundle(article_id, since=None)
            return sync.push(peer_url, article_id, bundle)
        raise ValueError("sync_article: no local or remote content")

    if local_head and local_head.id == remote_head.id:
        return local_head  # already in sync

    # ── Find merge base ──
    def _probe(v: Version) -> bool | None:
        return sync.pull_all(peer_url, article_id, since=v) is not None

    merge_base = find_merge_base(
        [e.version for e in local_history], _probe,
    )

    # ── Three-way decision ──
    if merge_base is None or merge_base.id == local_head.id if local_head else False:
        # Local behind — pull remote
        bundle = sync.pull_all(peer_url, article_id, since=local_head)
        if bundle:
            new_head = content.ingest_bundle(article_id, bundle)
            storage.reconcile_article(article_id)
            return new_head
    elif merge_base.id == remote_head.id:
        # Local ahead — push
        if local_head:
            bundle = content.create_bundle(article_id, since=remote_head)
            return sync.push(peer_url, article_id, bundle, since=remote_head)
    else:
        # Diverged — pull remote, local stays on top
        bundle = sync.pull_all(peer_url, article_id, since=merge_base)
        if bundle:
            content.ingest_bundle(article_id, bundle)
            storage.reconcile_article(article_id)
    return local_head or Version(id="unknown")


```

### peerpedia_core/protocols/storage.py (305 lines)
```python
# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Article storage — sub-storage protocols + composed concrete class.

Meta and content are universally separate storage concerns::

    ArticleMetaStorage    — indexed cache (DB), fast reads, queryable
    ArticleContentStorage — versioned source-of-truth (git), lazy body access
    ArticleStorage        — composed, wires sub-storages with action methods

Reconcile rebuilds the meta cache from content history.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Protocol

from peerpedia_core.exceptions import BadRequestError
from peerpedia_core.types.entities import (
    Article,
    ArticleDiff,
    ArticleId,
    ContentRef,
    Format,
    HistoryEntry,
    Review,
    UserId,
    Version,
)
from peerpedia_core.protocols.review_meta_storage import ReviewMetaStorage
from peerpedia_core.protocols.review_content_storage import ReviewContentStorage
from peerpedia_core.types.queries import ArticleQuery
from peerpedia_core.types.scores import Scores


# ═══════════════════════════════════════════════════════════════════════════
# Sub-storage protocols — pluggable backends
# ═══════════════════════════════════════════════════════════════════════════


class ArticleMetaStorage(Protocol):
    """Indexed metadata cache — fast reads, queryable.

    Typically DB-backed.  Git is the source of truth; this cache
    is rebuilt via ``ArticleStorage.reconcile()``.
    """

    def create(self) -> ArticleId:
        """Allocate a new article id with empty metadata (git init)."""
        ...

    def read(self, key: ArticleId) -> Article:
        """Return cached metadata for *key*."""
        ...

    def update(self, key: ArticleId, meta: Article) -> Version:
        """Replace cached metadata for *key*.  Returns content version."""
        ...

    def delete(self, key: ArticleId) -> Version:
        """Remove metadata row for *key*."""
        ...

    def query(self, q: ArticleQuery | None = None) -> list[Article]:
        """Search metadata with optional filters."""
        ...


class ArticleContentStorage(Protocol):
    """Versioned content store — git-backed source of truth.

    Body text, commit history, and authorship live here.
    Content is lazy-loaded via ``read_body``.
    """

    def create(self, key: ArticleId, fmt: Format) -> Version:
        """Initialize content for *key* in *fmt* (git init)."""
        ...

    def read(self, key: ArticleId) -> ContentRef:
        """Return the content locator for *key*."""
        ...

    def read_body(self, ref: ContentRef) -> str:
        """Resolve *ref* to raw body text (lazy, potentially large)."""
        ...

    def update(self, key: ArticleId, content: str) -> Version:
        """Append a new version of *content* to *key* (git commit)."""
        ...

    def delete(self, key: ArticleId) -> Version:
        """Mark content as deleted, retaining history."""
        ...

    def create_bundle(
        self, key: ArticleId, since: Version | None = None
    ) -> bytes:
        """Create a git bundle for *key*.  Incremental from *since*
        if given; full bundle otherwise."""
        ...

    def ingest_bundle(self, key: ArticleId, data: bytes) -> Version:
        """Apply a git bundle to *key*, returning the new head version."""
        ...

    def history(
        self, key: ArticleId, since: Version | None = None
    ) -> list[HistoryEntry]:
        """Version log for *key*, newest first."""
        ...

    def diff(
        self, key: ArticleId, version_a: Version, version_b: Version
    ) -> ArticleDiff:
        """Unified diff between two versions."""
        ...


# ═══════════════════════════════════════════════════════════════════════════
# Composed storage — concrete class, not a Protocol
# ═══════════════════════════════════════════════════════════════════════════


class ArticleStorage:
    """Composed storage — wires sub-storages with article action methods.

    Sub-storages (meta / content for articles and reviews) are injected.
    The action methods here are the canonical implementation; backends
    override only when they need custom storage logic.
    """

    def __init__(
        self,
        meta: ArticleMetaStorage,
        content: ArticleContentStorage,
        review_meta: ReviewMetaStorage,
        review_content: ReviewContentStorage,
    ):
        self._meta = meta
        self._content = content
        self._review_meta = review_meta
        self._review_content = review_content

    # ── Sub-storage access ──────────────────────────────────────────────

    @property
    def meta(self) -> ArticleMetaStorage:
        return self._meta

    @property
    def content(self) -> ArticleContentStorage:
        return self._content

    @property
    def review_meta(self) -> ReviewMetaStorage:
        return self._review_meta

    @property
    def review_content(self) -> ReviewContentStorage:
        return self._review_content

    # ── Article CRUD ────────────────────────────────────────────────────

    def create_article(self) -> ArticleId:
        """Create a new article — allocate id, init content, reconcile."""
        article_id = self._meta.create()
        self._content.create(article_id, Format(name="markdown"))
        self.reconcile_article(article_id)
        return article_id

    def read_article(self, article_id: ArticleId) -> Article:
        """Read article metadata (cheap — from indexed cache)."""
        return self._meta.read(article_id)

    def update_article(
        self, article_id: ArticleId, content_str: str, article: Article,
    ) -> None:
        """Update an existing article — content + meta, then reconcile."""
        self._content.update(article_id, content_str)
        self._meta.update(article_id, article)
        self.reconcile_article(article_id)

    def delete_article(self, article_id: ArticleId) -> None:
        """Delete an article — remove meta first (cache), then content (SOT)."""
        self._meta.delete(article_id)
        self._content.delete(article_id)

    # ── Review CRUD ─────────────────────────────────────────────────────

    def create_review(
        self, article_id: ArticleId, review: Review, scores_json: str,
    ) -> None:
        """Create a review — write content, reconcile meta, update score."""
        if review.article_id != article_id:
            raise BadRequestError(
                f"Review article_id {review.article_id.id!r} does not match "
                f"context {article_id.id!r}",
                field="review.article_id",
                bad_value=review.article_id.id,
            )

        scores = Scores(dimensions=json.loads(scores_json))

        # Dereference the review body content if present
        thread_content = (
            self._content.read_body(review.content_ref)
            if review.content_ref else ""
        )

        # Write to git SOT (content storage)
        self._review_content.update(article_id, review.reviewer_id, scores_json)
        self._review_content.append_thread_entry(
            article_id, review.reviewer_id, thread_content, "[review]",
        )

        # Rebuild meta index from content
        self._reconcile_reviews(article_id)

        # Update article aggregate score
        article = self._meta.read(article_id)
        self._meta.update(article_id, replace(article, score=scores))

    def read_review(self, article_id: ArticleId, reviewer_id: UserId) -> Review:
        """Read a review from the indexed meta cache."""
        return self._review_meta.read(article_id, reviewer_id)

    def update_review(
        self, article_id: ArticleId, reviewer_id: UserId,
        review: Review, scores_json: str,
    ) -> None:
        """Update an existing review — scores + thread, then reconcile."""
        self._review_content.update(article_id, reviewer_id, scores_json)
        self._review_content.append_thread_entry(
            article_id, reviewer_id,
            self._content.read_body(review.content_ref) if review.content_ref else "",
            "[reply]",
        )
        self._reconcile_reviews(article_id)

    def delete_review(self, article_id: ArticleId, reviewer_id: UserId) -> None:
        """Delete a review — remove meta first (cache), then content (SOT)."""
        self._review_meta.delete(article_id, reviewer_id)
        self._review_content.delete(article_id, reviewer_id)

    # ── Reconcile — public entry point for sync ─────────────────────────

    def reconcile_article(self, key: ArticleId) -> None:
        """Rebuild article meta cache from content SOT.

        Called internally by ``create`` / ``revise`` / ``publish``, and
        externally by sync after pulling remote data.
        """
        self._meta.update(key, self.extract(key))

    # ── Source-of-truth extraction ──────────────────────────────────────

    def extract(self, key: ArticleId) -> Article:
        """Extract metadata from content source-of-truth.

        Reads content history and reconstructs metadata fields:
        - ``authors`` ← git commit authors
        - ``status`` ← git commit message transitions
        - ``created_at`` / ``updated_at`` ← git commit timestamps
        - ``title`` / ``abstract`` ← YAML frontmatter

        The default implementation returns the current cached article.
        Backends with real git history should override.
        """
        return self._meta.read(key)

    def extract_reviews(self, key: ArticleId) -> list[Review]:
        """Extract Review objects from review content SOT.

        The default implementation is empty — backends with review content
        should override.
        """
        return []

    # ── Reconcile helpers ───────────────────────────────────────────────

    def _reconcile_reviews(self, key: ArticleId) -> None:
        """Rebuild review meta cache from review content SOT."""
        rmeta = self._review_meta

        for review in self.extract_reviews(key):
            try:
                existing = rmeta.read(key, review.reviewer_id)
            except Exception:
                existing = None

            if existing is None:
                rmeta.create(key, review.reviewer_id)
                existing = rmeta.read(key, review.reviewer_id)

            updated = Review(
                id=existing.id,
                article_id=key,
                reviewer_id=review.reviewer_id,
                scores=review.scores,
            )
            rmeta.update(key, review.reviewer_id, updated)
```

### peerpedia_core/protocols/lifecycle.py (138 lines)
```python
# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Lifecycle protocol — the morphism plugin.

The core engine pipeline for every article action::

    action: str, extra: Extra, context: ArticleId | None
        -> lifecycle.actions must include action          // universal or plugin-defined
        -> lifecycle.compatible(action, context, extra)   // domain check
        -> evaluate = lifecycle.resolve(action)           // pick the morphism
        -> evaluate(extra, context)                       // reduction -> new ArticleId

CLI, REPL, and server never hardcode allowed transitions.
They inject a Lifecycle plugin and let ``execute()`` do the work.

Universal actions
-----------------
Every Lifecycle MUST support these five morphisms::

    create    — persist a new article (meta + content)
    revise    — update an existing article
    publish   — make public
    delete    — remove / archive
    review    — create a peer review on the article
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TYPE_CHECKING

from peerpedia_core.exceptions import BadRequestError, ConflictError
from peerpedia_core.types.entities import Article, ArticleId

if TYPE_CHECKING:
    from peerpedia_core.protocols.storage import ArticleStorage

# ── Universal actions ───────────────────────────────────────────────────────
# Every Lifecycle plugin MUST support these.

_UNIVERSAL_ACTIONS: frozenset[str] = frozenset(
    {"create", "revise", "publish", "delete", "review"}
)

# ── Types ───────────────────────────────────────────────────────────────────

# Extra data injected for this operation (content body, metadata delta, etc.).
Extra = dict[str, object]

# Evaluation = morphism reduction: extra * context -> new context.
# *context* is ``None`` for the ``create`` action (no pre-existing article).
Evaluation = Callable[[Extra, ArticleId | None], ArticleId]


# ── Universal action implementations ───────────────────────────────────────


def action_publish(
    article_id: ArticleId, article: Article, storage: ArticleStorage,
) -> None:
    """Publish an article — update meta status, then reconcile from SOT.

    *publish* is a business-level status transition, not a storage
    primitive.  It exists here because "publishing" is a PeerPedia
    lifecycle concept, not a universal storage operation.
    """
    storage.meta.update(article_id, article)
    storage.reconcile_article(article_id)


# ── Lifecycle protocol ─────────────────────────────────────────────────────


class Lifecycle(Protocol):
    """A set of named actions (morphisms) with domain-compatibility rules.

    The ``actions`` property MUST include all universal actions
    (``create``, ``revise``, ``publish``, ``delete``, ``review``)
    plus any plugin-specific extensions.

    Each plugin decides, for a given ``(action, context, extra)``,
    whether the morphism applies via ``compatible()``.

    ``resolve()`` returns an ``Evaluation`` — callers have already
    checked ``compatible()``.
    """

    @property
    def actions(self) -> frozenset[str]:
        """All valid action names — universal actions + plugin extensions."""
        ...

    def compatible(
        self, action: str, context: ArticleId | None, extra: Extra
    ) -> bool:
        """Return True if *action* can apply to *context* with *extra*."""
        ...

    def resolve(self, action: str) -> Evaluation:
        """Return the evaluation function for *action*.

        The caller MUST have already checked ``compatible()``.
        """
        ...


# ── Dispatcher ──────────────────────────────────────────────────────────────


def execute(
    action: str,
    extra: Extra,
    context: ArticleId | None,
    lifecycle: Lifecycle,
) -> ArticleId:
    """Reduce *action* against *extra* and *context* through *lifecycle*.

    *context* is ``None`` for ``create`` — there is no pre-existing article.

    ::

        new_id = execute("create", {}, None, lifecycle)
        new_id = execute("publish", {}, new_id, lifecycle)
    """
    if action not in lifecycle.actions:
        raise BadRequestError(
            f"Unknown action '{action}'",
            field="action",
            bad_value=action,
        )
    if not lifecycle.compatible(action, context, extra):
        raise ConflictError(
            f"Action '{action}' is not compatible with the current context",
            conflicting_entity=action,
        )
    evaluate = lifecycle.resolve(action)
    return evaluate(extra, context)
```

### peerpedia_core/protocols/__init__.py (40 lines)
```python
# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Engine protocols — interfaces the core understands.

Each protocol is a ``typing.Protocol`` — no implementation, just
structural contracts.  Plugins in other packages implement these.
"""

from peerpedia_core.protocols.auth import AuthProvider, AuthResult
from peerpedia_core.protocols.authorizer import Authorizer
from peerpedia_core.protocols.compiler import Compiler
from peerpedia_core.protocols.lifecycle import Lifecycle
from peerpedia_core.protocols.review_content_storage import ReviewContentStorage
from peerpedia_core.protocols.review_meta_storage import ReviewMetaStorage
from peerpedia_core.protocols.scoring import ScoringEngine
from peerpedia_core.protocols.storage import (
    ArticleContentStorage,
    ArticleMetaStorage,
    ArticleStorage,
)
from peerpedia_core.protocols.sync import ArticleSync, ReviewSync
from peerpedia_core.protocols.user_storage import UserStorage

__all__ = [
    "ArticleContentStorage",
    "ArticleMetaStorage",
    "ArticleStorage",
    "ArticleSync",
    "ReviewSync",
    "AuthProvider",
    "AuthResult",
    "Authorizer",
    "Compiler",
    "Lifecycle",
    "ReviewContentStorage",
    "ReviewMetaStorage",
    "ScoringEngine",
    "UserStorage",
]
```

## Facade

### peerpedia_core/peerpedia.py (77 lines)
```python
# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""PeerPedia facade — wires protocols together into a usable engine.

Dependency injection for the protocol layer.  Holds all backends
and exposes lifecycle actions as named methods::

    pp = Peerpedia(storage, lifecycle, user_storage)
    aid = pp.create()
    pp.revise(aid, content="...", article=...)
    pp.publish(aid, article=...)
"""

from __future__ import annotations

from peerpedia_core.protocols.compiler import Compiler
from peerpedia_core.protocols.lifecycle import (
    Extra,
    Lifecycle,
    execute,
)
from peerpedia_core.protocols.storage import ArticleStorage
from peerpedia_core.protocols.user_storage import UserStorage
from peerpedia_core.types.entities import Article, ArticleId, Review, User


class Peerpedia:
    """Wired engine — holds backends, delegates to ``execute()``."""

    def __init__(
        self,
        storage: ArticleStorage,
        lifecycle: Lifecycle,
        user_storage: UserStorage,
        compiler: Compiler | None = None,
    ):
        self.storage = storage
        self.lifecycle = lifecycle
        self.users = user_storage
        self.compiler = compiler

    # ── Lifecycle actions ────────────────────────────────────────────────

    def create(self) -> ArticleId:
        return execute("create", {}, None, self.lifecycle)

    def revise(self, article_id: ArticleId, content: str, article: Article) -> ArticleId:
        extra: Extra = {"content": content, "article": article}
        return execute("revise", extra, article_id, self.lifecycle)

    def publish(self, article_id: ArticleId, article: Article) -> ArticleId:
        return execute("publish", {"article": article}, article_id, self.lifecycle)

    def delete(self, article_id: ArticleId) -> ArticleId:
        return execute("delete", {}, article_id, self.lifecycle)

    def review(self, article_id: ArticleId, review: Review, scores_json: str) -> ArticleId:
        extra: Extra = {"review": review, "scores": scores_json}
        return execute("review", extra, article_id, self.lifecycle)

    # ── Storage convenience ──────────────────────────────────────────────

    def read_meta(self, article_id: ArticleId) -> Article:
        return self.storage.meta.read(article_id)

    def read_user(self, user_id) -> User:
        return self.users.read(user_id)

    # ── Compiler ─────────────────────────────────────────────────────────

    def compile(self, article_id: ArticleId, fmt) -> bytes:
        if self.compiler is None:
            raise RuntimeError("No compiler configured")
        content_ref = self.storage.content.read(article_id)
        body = self.storage.content.read_body(content_ref)
        return self.compiler.compile(body, fmt)
```

### peerpedia_core/__init__.py (7 lines)
```python
# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""PeerPedia Core — engine protocols, types, and exceptions.

Zero dependencies.  No IO.  All other PeerPedia packages depend on this one.
"""
```

## Tests (Mem* in-memory backends + integration tests)

### tests/conftest.py (355 lines)
```python
"""Reference fixtures — in-memory backends for all protocols."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from peerpedia_core.exceptions import BadRequestError
from peerpedia_core.protocols.auth import AuthResult
from peerpedia_core.protocols.lifecycle import (
    Lifecycle, Evaluation, Extra, _UNIVERSAL_ACTIONS,
)
from peerpedia_core.protocols.storage import (
    ArticleContentStorage, ArticleMetaStorage, ArticleStorage,
)
from peerpedia_core.protocols.review_meta_storage import ReviewMetaStorage
from peerpedia_core.protocols.review_content_storage import ReviewContentStorage
from peerpedia_core.protocols.sync import ArticleSync, ReviewSync
from peerpedia_core.protocols.user_storage import UserStorage
from peerpedia_core.types import (
    Article, ArticleDiff, ArticleId, ContentRef, Format,
    HistoryEntry, Review, ReviewId, Scores, User, UserId, Version,
)
from peerpedia_core.types.queries import ArticleQuery

_MD = Format(name="markdown")


# ═══════════════════════════════════════════════════════════════════════════
# Article storage backends
# ═══════════════════════════════════════════════════════════════════════════

class MemMetaStorage:
    def __init__(self):
        self._rows: dict[str, Article] = {}
        self._counter = 0

    def create(self) -> ArticleId:
        self._counter += 1
        aid = ArticleId(id=f"art-{self._counter}")
        self._rows[aid.id] = Article(id=aid, title="", status="draft")
        return aid

    def read(self, key: ArticleId) -> Article:
        return self._rows[key.id]

    def update(self, key: ArticleId, meta: Article) -> Version:
        self._rows[key.id] = meta
        return Version(id=f"v-{time.monotonic_ns()}")

    def delete(self, key: ArticleId) -> Version:
        del self._rows[key.id]
        return Version(id=f"v-{time.monotonic_ns()}")

    def query(self, q: ArticleQuery | None = None) -> list[Article]:
        return list(self._rows.values())


class MemContentStorage:
    def __init__(self):
        self._blobs: dict[str, str] = {}
        self._repos: dict[str, ContentRef] = {}
        self._versions: dict[str, list[Version]] = {}

    def create(self, key: ArticleId, fmt: Format) -> Version:
        ref = ContentRef(ref=f"blob:{key.id}-0")
        self._repos[key.id] = ref
        self._blobs[ref.ref] = ""
        v = Version(id=f"v-{time.monotonic_ns()}")
        self._versions.setdefault(key.id, []).append(v)
        return v

    def read(self, key: ArticleId) -> ContentRef:
        return self._repos[key.id]

    def read_body(self, ref: ContentRef) -> str:
        return self._blobs[ref.ref]

    def update(self, key: ArticleId, content: str) -> Version:
        ref = ContentRef(ref=f"blob:{key.id}-{len(self._versions.get(key.id, []))}")
        self._repos[key.id] = ref
        self._blobs[ref.ref] = content
        v = Version(id=f"v-{time.monotonic_ns()}")
        self._versions.setdefault(key.id, []).append(v)
        return v

    def delete(self, key: ArticleId) -> Version:
        ref = self._repos.pop(key.id, None)
        if ref:
            self._blobs.pop(ref.ref, None)
        return Version(id=f"v-{time.monotonic_ns()}")

    def create_bundle(self, key: ArticleId, since: Version | None = None) -> bytes:
        ref = self._repos[key.id]
        return self._blobs[ref.ref].encode()

    def ingest_bundle(self, key: ArticleId, data: bytes) -> Version:
        return self.update(key, data.decode())

    def history(self, key: ArticleId, since: Version | None = None) -> list[HistoryEntry]:
        return []

    def diff(self, key: ArticleId, a: Version, b: Version) -> ArticleDiff:
        return ArticleDiff(version_a=a, version_b=b, content_diff="")


class MemReviewStorage:
    def __init__(self):
        self._rows: dict[str, Review] = {}

    def create(self, article_id: ArticleId, reviewer_id: UserId) -> Review:
        r = Review(
            id=ReviewId(id=f"rev-{article_id.id}-{reviewer_id.id}"),
            article_id=article_id, reviewer_id=reviewer_id,
        )
        self._rows[reviewer_id.id] = r
        return r

    def read(self, article_id: ArticleId, reviewer_id: UserId) -> Review:
        return self._rows[reviewer_id.id]

    def update(self, article_id: ArticleId, reviewer_id: UserId, review: Review) -> Version:
        self._rows[reviewer_id.id] = review
        return Version(id=f"v-{time.monotonic_ns()}")

    def delete(self, article_id: ArticleId, reviewer_id: UserId) -> Version:
        self._rows.pop(reviewer_id.id, None)
        return Version(id=f"v-{time.monotonic_ns()}")

    def list(self, article_id: ArticleId) -> list[Review]:
        return list(self._rows.values())


class MemReviewContentStorage:
    """In-memory ReviewContentStorage — simulates git repo review files."""

    def __init__(self):
        self._scores: dict[str, str] = {}       # "aid/uid" -> JSON
        self._threads: dict[str, list[str]] = {} # "aid/uid" -> [entry, ...]

    def _key(self, article_id: ArticleId, reviewer_id: UserId) -> str:
        return f"{article_id.id}/{reviewer_id.id}"

    def list_reviewers(self, article_id: ArticleId) -> list[UserId]:
        prefix = f"{article_id.id}/"
        return [UserId(id=k.split("/")[1]) for k in self._scores if k.startswith(prefix)]

    def create(self, article_id: ArticleId, reviewer_id: UserId) -> Version:
        k = self._key(article_id, reviewer_id)
        self._scores.setdefault(k, "{}")
        self._threads.setdefault(k, [])
        return Version(id=f"v-{time.monotonic_ns()}")

    def read(self, article_id: ArticleId, reviewer_id: UserId) -> str | None:
        return self._scores.get(self._key(article_id, reviewer_id))

    def update(self, article_id: ArticleId, reviewer_id: UserId,
               scores: str) -> Version:
        self._scores[self._key(article_id, reviewer_id)] = scores
        return Version(id=f"v-{time.monotonic_ns()}")

    def delete(self, article_id: ArticleId, reviewer_id: UserId) -> Version:
        k = self._key(article_id, reviewer_id)
        self._scores.pop(k, None)
        self._threads.pop(k, None)
        return Version(id=f"v-{time.monotonic_ns()}")

    def append_thread_entry(self, article_id: ArticleId, reviewer_id: UserId,
                            content: str, marker: str) -> Version:
        k = self._key(article_id, reviewer_id)
        self._threads.setdefault(k, []).append(content)
        return Version(id=f"v-{time.monotonic_ns()}")

    def read_thread(self, article_id: ArticleId, reviewer_id: UserId) -> list[str]:
        return self._threads.get(self._key(article_id, reviewer_id), [])


class MemArticleStorage(ArticleStorage):
    """In-memory ArticleStorage — Mem* sub-storages + overridden extract."""

    def __init__(self):
        super().__init__(
            meta=MemMetaStorage(),
            content=MemContentStorage(),
            review_meta=MemReviewStorage(),
            review_content=MemReviewContentStorage(),
        )

    def extract_reviews(self, key: ArticleId) -> list[Review]:
        rcontent = self.review_content
        reviews: list[Review] = []
        for reviewer_id in rcontent.list_reviewers(key):
            scores_json = rcontent.read(key, reviewer_id)
            scores = Scores(dimensions=json.loads(scores_json)) if scores_json else Scores()
            reviews.append(Review(
                id=ReviewId(id=f"rev-{key.id}-{reviewer_id.id}"),
                article_id=key,
                reviewer_id=reviewer_id,
                scores=scores,
            ))
        return reviews


# ═══════════════════════════════════════════════════════════════════════════
# Domain backends
# ═══════════════════════════════════════════════════════════════════════════

class MemUserStorage:
    def __init__(self):
        self._rows: dict[str, User] = {}
        self._counter = 0

    def create(self) -> UserId:
        self._counter += 1
        return UserId(id=f"user-{self._counter}")

    def read(self, key: UserId) -> User:
        return self._rows[key.id]

    def update(self, key: UserId, user: User) -> None:
        self._rows[key.id] = user

    def delete(self, key: UserId) -> None:
        self._rows.pop(key.id, None)

    def search(self, query: str) -> list[User]:
        return [u for u in self._rows.values() if query.lower() in u.name.lower()]

    def list(self) -> list[User]:
        return list(self._rows.values())


# ═══════════════════════════════════════════════════════════════════════════
# Lifecycle
# ═══════════════════════════════════════════════════════════════════════════

class MemLifecycle:
    """Lifecycle that bridges ``execute()`` to ``ArticleStorage`` methods."""

    def __init__(self, storage: ArticleStorage):
        self.storage = storage

    @property
    def actions(self) -> frozenset[str]:
        return _UNIVERSAL_ACTIONS

    def compatible(self, action: str, context: ArticleId | None, extra: Extra) -> bool:
        return action in self.actions

    def resolve(self, action: str) -> Evaluation:
        s = self.storage
        if action == "create":
            return lambda extra, ctx: s.create_article()
        if action == "revise":
            return lambda extra, ctx: (
                s.update_article(ctx, str(extra["content"]),
                                 _require_article(extra)), ctx)[1]
        if action == "publish":
            return lambda extra, ctx: (
                s.meta.update(ctx, _require_article(extra)),
                s.reconcile_article(ctx), ctx)[2]
        if action == "delete":
            return lambda extra, ctx: (s.delete_article(ctx), ctx)[1]
        if action == "review":
            return lambda extra, ctx: (
                s.create_review(ctx, _require_review(extra),
                                str(extra["scores"])), ctx)[1]
        raise BadRequestError(f"Unknown action: {action}")


def _require_article(extra: Extra) -> Article:
    a = extra.get("article")
    if not isinstance(a, Article):
        raise BadRequestError(
            f"Expected 'article' to be Article, got {type(a).__name__}",
            field="article", bad_value=str(type(a)),
        )
    return a


def _require_review(extra: Extra) -> Review:
    r = extra.get("review")
    if not isinstance(r, Review):
        raise BadRequestError(
            f"Expected 'review' to be Review, got {type(r).__name__}",
            field="review", bad_value=str(type(r)),
        )
    return r


class MemScoringEngine:
    def compute(self, reviews: list[Review]) -> Scores:
        dims: dict[str, list[float]] = {}
        for r in reviews:
            for dim, val in r.scores.dimensions.items():
                dims.setdefault(dim, []).append(val)
        return Scores(dimensions={
            d: sum(vals) / len(vals) for d, vals in dims.items()
        })


# ═══════════════════════════════════════════════════════════════════════════
# Sync
# ═══════════════════════════════════════════════════════════════════════════

class MemArticleSync:
    def __init__(self):
        self._registry: dict[str, dict[str, tuple[bytes, Version]]] = {}

    def fetch_version(self, peer_url: str, article_id: ArticleId) -> Version | None:
        entry = self._registry.get(peer_url, {}).get(article_id.id)
        return entry[1] if entry else None

    def push(self, peer_url: str, article_id: ArticleId, data: bytes,
             since: Version | None = None) -> Version:
        v = Version(id=f"v-{time.monotonic_ns()}")
        self._registry.setdefault(peer_url, {})[article_id.id] = (data, v)
        return v

    def pull_meta(self, peer_url: str, article_id: ArticleId,
                  since: Version | None = None) -> bytes | None:
        entry = self._registry.get(peer_url, {}).get(article_id.id)
        return entry[0] if entry else None

    def pull_all(self, peer_url: str, article_id: ArticleId,
                 since: Version | None = None) -> bytes | None:
        return self.pull_meta(peer_url, article_id, since)


class MemReviewSync:
    def __init__(self):
        self._registry: dict[str, dict[str, bytes]] = {}

    def push(self, peer_url: str, article_id: ArticleId, reviewer_id: UserId,
             data: bytes, since: Version | None = None) -> Version:
        self._registry.setdefault(peer_url, {})[f"{article_id.id}/{reviewer_id.id}"] = data
        return Version(id=f"v-{time.monotonic_ns()}")

    def pull(self, peer_url: str, article_id: ArticleId, reviewer_id: UserId,
             since: Version | None = None) -> bytes | None:
        return self._registry.get(peer_url, {}).get(f"{article_id.id}/{reviewer_id.id}")


# ═══════════════════════════════════════════════════════════════════════════
# Auth
# ═══════════════════════════════════════════════════════════════════════════

class MemAuthProvider:
    def sign(self, method: str, path: str, user_id: UserId,
             private_key: bytes, pubkey_hex: str, body: bytes = b"") -> str:
        return f"Peerpedia {user_id.id}:{pubkey_hex}:0:abc:ff"

    def verify(self, header_value: str, method: str, path: str,
               body: bytes = b"") -> AuthResult:
        return AuthResult(ok=True, user_id=UserId(id="alice"))
```

### tests/test_reference.py (212 lines)
```python
"""Protocol integration tests — exercises all protocols via Mem* backends."""
from __future__ import annotations

from datetime import datetime, timezone

from peerpedia_core.exceptions import BadRequestError, ConflictError
from peerpedia_core.protocols.lifecycle import Extra, execute
from peerpedia_core.protocols.sync import find_merge_base
from peerpedia_core.types import (
    Article, ArticleId, Format, Review, ReviewId, Scores, User, UserId, Version,
)

from tests.conftest import (
    MemArticleStorage, MemArticleSync, MemAuthProvider, MemContentStorage,
    MemLifecycle, MemMetaStorage, MemReviewContentStorage, MemReviewSync,
    MemScoringEngine, MemUserStorage,
)


def test_full_lifecycle():
    """create → revise → publish → review → delete."""
    storage = MemArticleStorage()
    lc = MemLifecycle(storage)

    new_id = execute("create", {}, None, lc)
    assert new_id.id == "art-1"

    meta_store = storage.meta
    content_store = storage.content
    article = meta_store.read(new_id)
    assert article.status == "draft"

    cref = content_store.read(new_id)
    assert cref is not None
    assert content_store.read_body(cref) == ""

    # Revise
    revised_meta = Article(
        id=article.id, title="A Great Paper", status="draft",
        authors=("Alice",), abstract="An important result.",
        keywords=("test",), created_at=datetime.now(timezone.utc),
    )
    extra: Extra = {"content": "# Introduction\n\nHello world.", "article": revised_meta}
    execute("revise", extra, new_id, lc)
    cref = content_store.read(new_id)
    assert "Hello world" in content_store.read_body(cref)

    # Publish
    pub_meta = Article(
        id=article.id, title=article.title, status="published",
        authors=article.authors, abstract=article.abstract, keywords=article.keywords,
        bib_data=article.bib_data, content_ref=article.content_ref,
    )
    execute("publish", {"article": pub_meta}, new_id, lc)
    assert storage.meta.read(new_id).status == "published"

    # User (standalone, not through ArticleStorage)
    users = MemUserStorage()
    uid = users.create()
    users.update(uid, User(id=uid, name="Bob", public_key="ab" * 32))
    assert users.read(uid).name == "Bob"

    # Review (through review content storage)
    import json
    review = Review(
        id=ReviewId(id="r1"), article_id=new_id, reviewer_id=uid,
        scores=Scores(dimensions={"clarity": 4.0, "rigor": 3.5}),
    )
    scores_json = json.dumps({"clarity": 4.0, "rigor": 3.5})
    execute("review", {"review": review, "scores": scores_json}, new_id, lc)

    # Read back from content storage
    rcontent = storage.review_content
    assert rcontent.read(new_id, uid) == scores_json

    # Read back from meta storage
    rmeta = storage.review_meta
    reviews = rmeta.list(new_id)
    assert len(reviews) == 1
    assert reviews[0].reviewer_id.id == uid.id

    # Scoring
    engine = MemScoringEngine()
    assert engine.compute(reviews).average() == 3.75

    execute("delete", {}, new_id, lc)

    encoded = article.encode()
    assert Article.decode(encoded).title == article.title
    assert len(users.search("bob")) == 1


def test_sync():
    sync = MemArticleSync()
    aid = ArticleId(id="art-1")
    v = Version(id="v1")
    data = b'{"title": "Test"}'

    assert sync.push("https://peer.example.com", aid, data, since=v).id.startswith("v-")
    assert sync.pull_meta("https://peer.example.com", aid) == data
    assert sync.pull_meta("https://nobody.example.com", aid) is None


def test_review_sync():
    sync = MemReviewSync()
    aid, uid = ArticleId(id="art-1"), UserId(id="bob")
    data = b'{"scores": {"clarity": 5}}'
    sync.push("https://peer.example.com", aid, uid, data)
    assert sync.pull("https://peer.example.com", aid, uid) == data


def test_auth():
    auth = MemAuthProvider()
    uid = UserId(id="alice")
    header = auth.sign("GET", "/articles/art-1", uid, b"key", "ab" * 32)
    assert header.startswith("Peerpedia ")
    result = auth.verify(header, "GET", "/articles/art-1")
    assert result.ok and result.user_id.id == "alice"


def test_user_storage_read():
    store = MemUserStorage()
    uid = store.create()
    store.update(uid, User(id=uid, name="Charlie"))
    assert store.read(uid).name == "Charlie"


def test_content_storage_read():
    meta, content = MemMetaStorage(), MemContentStorage()
    aid = meta.create()
    content.create(aid, Format(name="markdown"))
    content.update(aid, "# Body text")
    assert meta.read(aid).status == "draft"
    assert content.read_body(content.read(aid)) == "# Body text"


def test_execute_unknown_action():
    storage = MemArticleStorage()
    try:
        execute("unknown", {}, ArticleId(id="x"), MemLifecycle(storage))
        assert False
    except BadRequestError:
        pass


def test_execute_incompatible():
    class Strict(MemLifecycle):
        def compatible(self, action, context, extra): return False
    try:
        execute("revise", {}, ArticleId(id="x"), Strict(MemArticleStorage()))
        assert False
    except ConflictError:
        pass


def test_find_merge_base():
    local = [Version(id="v4"), Version(id="v3"), Version(id="v2"), Version(id="v1")]
    assert find_merge_base(local, lambda v: v.id != "v4").id == "v3"
    assert find_merge_base(local, lambda v: False) is None
    assert find_merge_base(local, lambda v: None) is None


def test_sync_article():
    sync = MemArticleSync()
    storage = MemArticleStorage()
    lc = MemLifecycle(storage)

    new_id = execute("create", {}, None, lc)
    extra: Extra = {
        "content": "# Sync test body",
        "article": Article(id=new_id, title="Sync Test", status="draft",
                           authors=("Alice",), created_at=datetime.now(timezone.utc)),
    }
    execute("revise", extra, new_id, lc)

    v = sync.push("https://peer.example.com", new_id, b"bundled-data")
    assert v.id.startswith("v-")
    assert sync.fetch_version("https://peer.example.com", new_id).id == v.id


def test_compiler():
    from peerpedia_core.protocols.compiler import Compiler
    from peerpedia_core.types import Format

    class MemCompiler:
        def compile(self, content: str, fmt: Format) -> bytes:
            if fmt.name == "html":
                return f"<p>{content}</p>".encode()
            raise ValueError(f"Unknown format: {fmt.name}")

    c: Compiler = MemCompiler()
    assert c.compile("Hello", Format(name="html")) == b"<p>Hello</p>"


def test_review_content_round_trip():
    """Write review to content storage, read back."""
    rcontent = MemReviewContentStorage()
    aid = ArticleId(id="art-1")
    uid = UserId(id="bob")

    rcontent.update(aid, uid, '{"clarity":5.0}')
    assert rcontent.read(aid, uid) == '{"clarity":5.0}'

    rcontent.append_thread_entry(aid, uid, "Great paper!", "[review]")
    rcontent.append_thread_entry(aid, uid, "Thanks for the feedback!", "[reply]")
    thread = rcontent.read_thread(aid, uid)
    assert len(thread) == 2
    assert thread[0] == "Great paper!"

    rcontent.delete(aid, uid)
    assert rcontent.read(aid, uid) is None
    assert rcontent.read_thread(aid, uid) == []
```

