# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""PeerPedia facade — wires protocols together into a usable engine.

Dependency injection for the protocol layer.  Holds all backends
and exposes lifecycle actions as named methods::

    pp = Peerpedia(storage, lifecycle, user_storage)
    aid = pp.create()
    pp.revise(aid, content="...", article=...)
    pp.publish(aid, article=...)
"""

from __future__ import annotations

from peerpedia_core.protocols.compiler import Compiler
from peerpedia_core.protocols.lifecycle import (
    Extra,
    Lifecycle,
    execute,
)
from peerpedia_core.protocols.storage import ArticleStorage
from peerpedia_core.protocols.user_storage import UserStorage
from peerpedia_core.types.entities import Article, ArticleId, Review, User


class Peerpedia:
    """Wired engine — holds backends, delegates to ``execute()``."""

    def __init__(
        self,
        storage: ArticleStorage,
        lifecycle: Lifecycle,
        user_storage: UserStorage,
        compiler: Compiler | None = None,
    ):
        self.storage = storage
        self.lifecycle = lifecycle
        self.users = user_storage
        self.compiler = compiler

    # ── Lifecycle actions ────────────────────────────────────────────────

    def create(self) -> ArticleId:
        return execute("create", {}, None, self.lifecycle)

    def revise(self, article_id: ArticleId, content: str, article: Article) -> ArticleId:
        extra: Extra = {"content": content, "article": article}
        return execute("revise", extra, article_id, self.lifecycle)

    def publish(self, article_id: ArticleId, article: Article) -> ArticleId:
        return execute("publish", {"article": article}, article_id, self.lifecycle)

    def delete(self, article_id: ArticleId) -> ArticleId:
        return execute("delete", {}, article_id, self.lifecycle)

    def review(self, article_id: ArticleId, review: Review, scores_json: str) -> ArticleId:
        extra: Extra = {"review": review, "scores": scores_json}
        return execute("review", extra, article_id, self.lifecycle)

    # ── Storage convenience ──────────────────────────────────────────────

    def read_meta(self, article_id: ArticleId) -> Article:
        return self.storage.read_meta(article_id)

    def read_user(self, user_id) -> User:
        return self.users.read(user_id)

    # ── Compiler ─────────────────────────────────────────────────────────

    def compile(self, article_id: ArticleId, fmt) -> bytes:
        if self.compiler is None:
            raise RuntimeError("No compiler configured")
        content_ref = self.storage.read_content(article_id)
        body = self.storage.get_content(article_id).deref_body(content_ref)
        return self.compiler.compile(body, fmt)
