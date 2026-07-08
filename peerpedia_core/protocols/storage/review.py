# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Review storage protocols -- meta index (DB) + content SOT (git).

Meta and content are separate storage concerns::

    ReviewMetaStorage    — indexed cache (DB), fast reads, queryable
    ReviewContentStorage — versioned source-of-truth (git), file-level CRUD
"""

from __future__ import annotations

__all__ = [
    "ReviewContentStorage",
    "ReviewMetaStorage",
]

from typing import Protocol, TYPE_CHECKING

from peerpedia_core.types.entities import ArticleId, Review, UserId, Version

if TYPE_CHECKING:
    from peerpedia_core.types.writes import ReviewWrite


# ═══════════════════════════════════════════════════════════════════════════
# Meta storage — DB index
# ═══════════════════════════════════════════════════════════════════════════


class ReviewMetaStorage(Protocol):
    """Indexed review cache -- fast reads, queryable.

    Typically DB-backed.  Git is the source of truth; this cache
    is rebuilt via ``_reconcile_reviews()``.
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
        """Replace the cached review -- returns the article version."""
        ...

    def delete(self, article_id: ArticleId, reviewer_id: UserId) -> Version:
        """Remove the review index row -- returns the article version."""
        ...

    def list(self, article_id: ArticleId) -> list[Review]:
        """Return all cached reviews for *article_id*."""
        ...


# ═══════════════════════════════════════════════════════════════════════════
# Content storage — git SOT
# ═══════════════════════════════════════════════════════════════════════════


class ReviewContentStorage(Protocol):
    """CRUD for review content in the article git repo.

    Each method targets the reviewer's directory under
    ``reviews/{dir_id}/`` within the article repository.

    Scores are the primary content (create / read / update).
    Thread entries are append-only (no update -- each reply is a new entry).
    """

    # ── CRUD ────────────────────────────────────────────────────────────

    def create(
        self, article_id: ArticleId, reviewer_id: UserId,
    ) -> Version:
        """Initialize the review directory for *reviewer_id*."""
        ...

    def write_review(
        self, article_id: ArticleId, write: ReviewWrite,
    ) -> Version:
        """Write a complete review -- scores + thread entry -- as a bundled operation.

        The backend serializes *write.scores* to JSON and appends
        *write.content* to the review thread in one logical operation.
        """
        ...

    def read(
        self, article_id: ArticleId, reviewer_id: UserId,
    ) -> str | None:
        """Read ``scores.json`` -- return JSON text or None."""
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
