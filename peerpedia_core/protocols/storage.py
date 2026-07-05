# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""ArticleStorage protocol — the storage-backend plugin.

Core does not know whether articles live in git repos, PDF files,
or flat wiki pages.  It only knows this interface.  Each backend
(gitdb, arxiv, wiki) is a separate package that implements it.

Read pipeline (no auth, no lifecycle)::

    st: StorageContext, article_id -> get(st, article_id) -> Article
    st: StorageContext, query      -> list(st, query)     -> list[Article]
    st: StorageContext, id, v1, v2 -> diff(st, id, v1, v2) -> str

Write pipeline (auth + lifecycle)::

    Authorizer -> Lifecycle -> write_source / write_review / ...
"""

from __future__ import annotations

from typing import Protocol

from peerpedia_core.types.entities import Article, Review


class ArticleStorage(Protocol):
    """Storage operations the core engine requires.

    Implementations are plugins — swap gitdb for arxiv by changing
    one configuration line.  Core never imports a concrete backend.
    """

    # ── Read ────────────────────────────────────────────────────────────

    def get(self, article_id: str) -> Article:
        """Return a single article by ID.

        Raises NotFoundError if the article does not exist.
        """
        ...

    def list(self, query: str | None = None) -> list[Article]:
        """Return articles matching *query*.

        A None or empty query returns recent articles.  Specific
        backends may support title search, author filter, etc.
        """
        ...

    def diff(
        self, article_id: str, from_version: str, to_version: str
    ) -> str:
        """Return a unified diff between two versions."""
        ...

    # ── Source content ──────────────────────────────────────────────────

    def read_source(self, article_id: str) -> bytes:
        """Return the raw source content of *article_id*."""
        ...

    def write_source(
        self, article_id: str, content: bytes, author: str, message: str
    ) -> str:
        """Write source content, return a version identifier."""
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
        signer: object,
    ) -> str:
        """Persist a review, return a version identifier."""
        ...

    # ── Write metadata ──────────────────────────────────────────────────

    def write_metadata(self, article_id: str, article: Article) -> None:
        """Persist metadata for *article_id*."""
        ...
