# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Review content storage protocol — git SOT for peer evaluations.

Reviews live inside the article git repository under
``reviews/{dir_id}/``::

    reviews/{dir_id}/scores.json
    reviews/{dir_id}/threads/001.md
    reviews/{dir_id}/threads/002.md

This protocol provides file-level read/write access.  Semantic
operations (submit, reply) live in lifecycle actions.
"""

from __future__ import annotations

from typing import Protocol

from peerpedia_core.types.entities import ArticleId, UserId, Version


class ReviewContentStorage(Protocol):
    """File-level operations on review content in the article git repo.

    Each method targets the reviewer's directory under
    ``reviews/{dir_id}/`` within the article repository.
    """

    def list_reviewers(
        self, article_id: ArticleId,
    ) -> list[UserId]:
        """Return all reviewer ids that have written content for *article_id*."""
        ...

    def write_scores(
        self, article_id: ArticleId, reviewer_id: UserId, scores: str
    ) -> Version:
        """Write ``scores.json`` for *reviewer_id*.  *scores* is JSON text."""
        ...

    def read_scores(
        self, article_id: ArticleId, reviewer_id: UserId
    ) -> str | None:
        """Read ``scores.json`` — return JSON text or None."""
        ...

    def write_thread_entry(
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

    def delete_review_dir(
        self, article_id: ArticleId, reviewer_id: UserId,
    ) -> Version:
        """Remove the entire ``reviews/{dir_id}/`` directory."""
        ...
