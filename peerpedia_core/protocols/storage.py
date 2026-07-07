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
    UserId,
    Version,
)
from peerpedia_core.protocols.review_meta_storage import ReviewMetaStorage
from peerpedia_core.protocols.review_content_storage import ReviewContentStorage
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
        """Initialize content for *key* in *fmt* (git init)."""
        ...


    def read(self, key: ArticleId) -> ContentRef:
        """Return the content locator for *key*."""
        ...

    def deref_body(self, ref: ContentRef) -> str:
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


class ArticleStorage(Protocol):
    """Composed storage — meta cache + content SOT for articles and reviews.

    Article and review each follow the same meta/content split::

        ArticleMetaStorage     /  ArticleContentStorage
        ReviewMetaStorage      /  ReviewContentStorage

    ``reconcile()`` rebuilds article meta from content.
    ``reconcile_reviews()`` rebuilds review meta from content.
    """

    # ── Article sub-storage ────────────────────────────────────────────

    def get_meta(self, key: ArticleId | None = None) -> ArticleMetaStorage:
        """Return the article-meta sub-storage for *key*.

        When *key* is ``None`` (not yet created), returns a global
        meta store for id-allocation operations like ``create()``.
        """
        ...

    def get_content(self, key: ArticleId | None = None) -> ArticleContentStorage:
        """Return the article-content sub-storage for *key*."""
        ...

    def read_meta(self, key: ArticleId) -> Article:
        """Convenience — delegates to ``get_meta(key).read(key)``."""
        return self.get_meta(key).read(key)

    def read_content(self, key: ArticleId) -> ContentRef:
        """Convenience — delegates to ``get_content(key).read(key)``."""
        return self.get_content(key).read(key)

    # ── Review sub-storage ─────────────────────────────────────────────

    def get_review_meta(self, key: ArticleId) -> ReviewMetaStorage:
        """Return the review-meta sub-storage for *key*."""
        ...

    def get_review_content(self, key: ArticleId) -> ReviewContentStorage:
        """Return the review-content sub-storage for *key*."""
        ...

    def read_review_meta(
        self, key: ArticleId, reviewer_id: UserId
    ) -> Review:
        """Convenience — delegates to ``get_review_meta(key).read(key, reviewer_id)``."""
        return self.get_review_meta(key).read(key, reviewer_id)

    def read_review_content(
        self, key: ArticleId, reviewer_id: UserId
    ) -> list[str]:
        """Convenience — delegates to ``get_review_content(key).read_thread(key, reviewer_id)``."""
        return self.get_review_content(key).read_thread(key, reviewer_id)

    # ── Source-of-truth extraction ─────────────────────────────────────

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


def reconcile_reviews(storage: ArticleStorage, key: ArticleId) -> None:
    """Rebuild review meta cache from review content SOT.

    Extracts review metadata from the git content store and writes
    it to ``ReviewMetaStorage``.  Run after review content changes.
    """
    import json

    from peerpedia_core.types.entities import Review, Scores

    rmeta = storage.get_review_meta(key)
    rcontent = storage.get_review_content(key)

    for reviewer_id in rcontent.list_reviewers(key):
        scores_json = rcontent.read_scores(key, reviewer_id)
        scores = Scores(dimensions=json.loads(scores_json)) if scores_json else Scores()

        # Read or create the meta entry
        try:
            existing = rmeta.read(key, reviewer_id)
        except Exception:
            existing = None

        if existing is None:
            rmeta.create(key, reviewer_id)
            existing = rmeta.read(key, reviewer_id)

        updated = Review(
            id=existing.id,
            article_id=key,
            reviewer_id=reviewer_id,
            scores=scores,
        )
        rmeta.update(key, reviewer_id, updated)
