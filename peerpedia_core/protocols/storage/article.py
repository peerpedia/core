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

__all__ = [
    "ArticleContentStorage",
    "ArticleMetaStorage",
    "ArticleStorage",
]

import json
from dataclasses import replace
from typing import Protocol

from peerpedia_core.exceptions import BadRequestError, NotFoundError
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
from peerpedia_core.types.writes import ArticleWrite, CommitData, ReviewWrite
from peerpedia_core.protocols.storage.review import ReviewMetaStorage, ReviewContentStorage
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

    def write_article(self, key: ArticleId, write: ArticleWrite) -> Version:
        """Write article metadata + body to SOT as a single bundled operation.

        The backend serializes the full ``Article`` entity (title, abstract,
        authors, status, etc.) alongside the body content.  This is the
        canonical write path — ``update()`` is a convenience for body-only
        changes.
        """
        ...

    def update(self, key: ArticleId, content: str) -> Version:
        """Append a new version of *content* to *key* (git commit).

        Convenience for body-only writes.  Prefer ``write_article()``
        when metadata changes as well.
        """
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

    def create_article(self, commit: CommitData | None = None) -> ArticleId:
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
        commit: CommitData | None = None,
    ) -> None:
        """Update an existing article — write SOT, then reconcile."""
        self._content.write_article(
            article_id,
            ArticleWrite(article=article, content=content_str, commit=commit),
        )
        self.reconcile_article(article_id)

    def delete_article(self, article_id: ArticleId, commit: CommitData | None = None) -> None:
        """Delete an article — remove meta first (cache), then content (SOT)."""
        self._meta.delete(article_id)
        self._content.delete(article_id)

    # ── Review CRUD ─────────────────────────────────────────────────────

    def create_review(
        self, article_id: ArticleId, reviewer_id: UserId,
        scores: Scores, body: str = "",
        commit: CommitData | None = None,
    ) -> None:
        """Create a review — write SOT, then reconcile meta."""
        self._review_content.write_review(
            article_id,
            ReviewWrite(
                reviewer_id=reviewer_id, scores=scores,
                content=body, commit=commit,
            ),
        )
        self._reconcile_reviews(article_id)

    def read_review(self, article_id: ArticleId, reviewer_id: UserId) -> Review:
        """Read a review from the indexed meta cache."""
        return self._review_meta.read(article_id, reviewer_id)

    def update_review(
        self, article_id: ArticleId, reviewer_id: UserId,
        scores: Scores, body: str = "",
        commit: CommitData | None = None,
    ) -> None:
        """Update an existing review — write SOT, then reconcile."""
        self._review_content.write_review(
            article_id,
            ReviewWrite(
                reviewer_id=reviewer_id, scores=scores,
                content=body, commit=commit,
            ),
        )
        self._reconcile_reviews(article_id)

    def delete_review(self, article_id: ArticleId, reviewer_id: UserId, commit: CommitData | None = None) -> None:
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

        The default implementation reads from the meta cache and fills
        in content_ref from the content store.  Backends with real git
        history should override.
        """
        article = self._meta.read(key)
        try:
            content_ref: ContentRef | None = self._content.read(key)
        except Exception:
            content_ref = article.content_ref
        return replace(
            article,
            content_ref=content_ref,
            format=article.format or Format(name="markdown"),
        )

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
            except NotFoundError:
                existing = None

            if existing is None:
                rmeta.create(key, review.reviewer_id)
                existing = rmeta.read(key, review.reviewer_id)

            updated = replace(
                existing,
                article_id=key,
                reviewer_id=review.reviewer_id,
                scope=review.scope,
                scores=review.scores,
                content_ref=review.content_ref,
                created_at=review.created_at,
            )
            rmeta.update(key, review.reviewer_id, updated)
