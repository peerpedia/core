# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Article storage protocols — meta, content, and composed.

Meta and content are universally separate storage concerns::

    ArticleMetaStorage    — indexed cache (DB), fast reads, queryable
    ArticleContentStorage — versioned source-of-truth (git), lazy body access
    ArticleStorage        — composed, adds ``reconcile``

Reconcile rebuilds the meta cache from content history.
Writes go through lifecycle actions, not storage methods directly.
"""

from __future__ import annotations

from typing import Protocol

from peerpedia_core.types.entities import (
    Article,
    ArticleDiff,
    ArticleId,
    ContentRef,
    Format,
    HistoryEntry,
    Review,
    User,
    UserId,
    Version,
)
from peerpedia_core.protocols.review_storage import ReviewStorage
from peerpedia_core.protocols.user_storage import UserStorage
from peerpedia_core.types.queries import ArticleQuery


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
    Content is lazy-loaded via ``deref_body``.
    """

    def create(self, key: ArticleId, fmt: Format) -> Version:
        """Initialize content for *key* with *fmt* (git init)."""
        ...

    def read(self, key: ArticleId) -> ContentRef:
        """Return the content locator for *key*."""
        ...

    def read_format(self, key: ArticleId) -> Format:
        """Return the content format for *key*."""
        ...

    def deref_body(self, ref: ContentRef) -> str:
        """Resolve *ref* to raw body text (lazy, potentially large)."""
        ...

    def update(self, key: ArticleId, content: str, fmt: Format) -> Version:
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


class ArticleStorage(Protocol):
    """Composed storage — meta cache + content source-of-truth.

    Access sub-protocols via ``get_meta()`` / ``get_content()``
    for domain-specific operations, or use ``read_meta`` /
    ``read_content`` for common access patterns.
    ``reconcile`` rebuilds the meta cache from content history.
    """

    def get_meta(self, key: ArticleId) -> ArticleMetaStorage:
        """Return the metadata sub-storage for *key*."""
        ...

    def get_content(self, key: ArticleId) -> ArticleContentStorage:
        """Return the content sub-storage for *key*."""
        ...

    def read_meta(self, key: ArticleId) -> Article:
        """Convenience — delegates to ``get_meta(key).read(key)``."""
        ...

    def read_content(self, key: ArticleId) -> ContentRef:
        """Convenience — delegates to ``get_content(key).read(key)``."""
        ...

    def get_review(self, key: ArticleId) -> ReviewStorage:
        """Return the review sub-storage for *key*."""
        ...

    def read_review(self, key: ArticleId, reviewer_id: UserId) -> Review:
        """Convenience — delegates to ``get_review(key).read(key, reviewer_id)``."""
        ...

    def get_user(self) -> UserStorage:
        """Return the user sub-storage (global — not per-article)."""
        ...

    def read_user(self, key: UserId) -> User:
        """Convenience — delegates to ``get_user().read(key)``."""
        ...

    def extract(self, key: ArticleId) -> Article:
        """Extract metadata from content source-of-truth.

        Reads content history and reconstructs metadata fields:
        - ``authors`` ← git commit authors
        - ``status`` ← git commit message transitions
        - ``created_at`` / ``updated_at`` ← git commit timestamps
        - ``title`` / ``abstract`` ← YAML frontmatter

        The caller composes this with ``meta.update()`` to rebuild
        the cache — see ``reconcile()``, the derived helper.
        """
        ...


def reconcile(storage: ArticleStorage, key: ArticleId) -> None:
    """Rebuild meta cache from content source-of-truth.

    ``extract`` + ``meta.update`` — a derived convenience, not a
    protocol primitive.
    """
    storage.get_meta(key).update(key, storage.extract(key))
