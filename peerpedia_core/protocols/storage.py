# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""ArticleStorage protocol — the storage-backend plugin.

Core does not know whether articles live in git repos, PDF files,
or flat wiki pages.  It only knows this interface.  Each backend
(gitdb, arxiv, wiki) is a separate package that implements it.

Storage knows nothing about reviews, scores, or status.  Those are
lifecycle-plugin concepts.  Storage only knows keys and bytes.

Read pipeline::

    st: Storage, article_id -> read(st, article_id) -> Article
    st: Storage, query      -> list(st, query)     -> list[Article]

Write pipeline::

    Authorizer → Lifecycle → action calls st.write(key, data, signer, message)
"""

from __future__ import annotations

from typing import Any, Protocol

from peerpedia_core.crypto import SigningKey


class ArticleStorage(Protocol):
    """Generic key-value storage with versioned writes.

    Implementations are plugins — git repos, PDF directories,
    flat wiki pages.  Core never imports a concrete backend.
    """

    # ── Read ────────────────────────────────────────────────────────────

    def read(self, key: str) -> dict[str, Any]:
        """Return the data stored at *key* as a dict.

        The dict shape depends on what was written — Article, Review,
        or arbitrary metadata.  Callers are responsible for constructing
        typed entities from the returned dict.
        """
        ...

    def list(self, query: str | None = None) -> list[str]:
        """Return keys matching *query*.

        A None or empty query returns recent keys.  Backends may support
        prefix search, full-text search, etc.
        """
        ...

    # ── Write ───────────────────────────────────────────────────────────

    def write(
        self,
        key: str,
        data: dict[str, Any],
        signer: SigningKey,
        message: str,
    ) -> str:
        """Persist *data* at *key*, return a version identifier.

        *signer* identifies the author.  *message* is a human-readable
        description of the change.
        """
        ...

    # ── History ─────────────────────────────────────────────────────────

    def history(
        self, key: str, since: str | None = None
    ) -> list[dict]:
        """Return change history for *key*, optionally since *since*."""
        ...
