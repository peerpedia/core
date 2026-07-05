# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""ArticleStorage protocol — the storage-backend plugin.

Core does not know whether articles live in git repos, PDF files,
or flat wiki pages.  It only knows this interface.  Each backend
(gitdb, arxiv, wiki) is a separate package that implements it.
"""

from __future__ import annotations

from typing import Protocol

from peerpedia_core.types.entities import Article, Review, User


class ArticleStorage(Protocol):
    """Storage operations the core engine requires.

    Implementations are plugins — swap gitdb for arxiv by changing
    one configuration line.  Core never imports a concrete backend.
    """

    # ── Source content ──────────────────────────────────────────────────

    def read_source(self, article_id: str) -> bytes:
        """Return the raw source content of *article_id*."""
        ...

    def write_source(
        self, article_id: str, content: bytes, author: str, message: str
    ) -> str:
        """Write source content, return a version identifier."""
        ...

    # ── Metadata ────────────────────────────────────────────────────────

    def read_metadata(self, article_id: str) -> Article:
        """Return the parsed metadata for *article_id*."""
        ...

    def write_metadata(self, article_id: str, metadata: Article) -> None:
        """Persist metadata for *article_id*."""
        ...

    # ── History ─────────────────────────────────────────────────────────

    def get_history(
        self, article_id: str, since: str | None = None
    ) -> list[dict]:
        """Return change history for *article_id*, optionally since *since*."""
        ...

    # ── Reviews ─────────────────────────────────────────────────────────

    def list_reviews(self, article_id: str) -> list[str]:
        """Return review IDs for *article_id*."""
        ...

    def read_review(self, article_id: str, reviewer_id: str) -> Review:
        """Return a single review."""
        ...

    def write_review(
        self,
        article_id: str,
        reviewer_id: str,
        scores: dict[str, float],
        comment: str,
        signer: object,  # signing key — concrete type from crypto layer
    ) -> str:
        """Persist a review, return a version identifier."""
        ...
