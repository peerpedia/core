# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Review storage protocol — CRUD for peer evaluations."""

from __future__ import annotations

from typing import Protocol

from peerpedia_core.types.entities import ArticleId, Review, UserId, Version


class ReviewStorage(Protocol):
    """CRUD for reviews — peer evaluations linked to an article.

    Reviews associate a reviewer with an article, carrying scores
    and optional written comments (via ``content_ref``).
    """

    def create(self, article_id: ArticleId, reviewer_id: UserId) -> Review:
        """Allocate a new review for *article_id*."""
        ...

    def read(self, article_id: ArticleId, reviewer_id: UserId) -> Review:
        """Return the review by *reviewer_id* on *article_id*."""
        ...

    def update(
        self, article_id: ArticleId, reviewer_id: UserId, review: Review
    ) -> Version:
        """Replace the review — returns the article version."""
        ...

    def delete(self, article_id: ArticleId, reviewer_id: UserId) -> Version:
        """Remove the review — returns the article version."""
        ...

    def list(self, article_id: ArticleId) -> list[Review]:
        """Return all reviews for *article_id*."""
        ...
