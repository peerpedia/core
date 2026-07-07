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
