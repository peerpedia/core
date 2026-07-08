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

from peerpedia_core.exceptions import NotAuthorizedError
from peerpedia_core.protocols.authorizer import Authorizer
from peerpedia_core.protocols.compiler import Compiler
from peerpedia_core.protocols.lifecycle import (
    Extra,
    Lifecycle,
    execute,
)
from peerpedia_core.protocols.storage import ArticleStorage, UserStorage
from peerpedia_core.types.entities import Article, ArticleId, Format, Review, User, UserId


class Peerpedia:
    """Wired engine — holds backends, delegates to ``execute()``.

    Authorization is optional.  If an ``Authorizer`` is injected and
    *user* is provided on a mutating call, the facade checks permission
    before executing the lifecycle action.
    """

    def __init__(
        self,
        storage: ArticleStorage,
        lifecycle: Lifecycle,
        user_storage: UserStorage,
        compiler: Compiler | None = None,
        authorizer: Authorizer | None = None,
    ):
        self.storage = storage
        self.lifecycle = lifecycle
        self.users = user_storage
        self.compiler = compiler
        self.authorizer = authorizer

    # ── Lifecycle actions ────────────────────────────────────────────────

    def create(self, user: User | None = None) -> ArticleId:
        return execute("create", {}, None, self.lifecycle)

    def revise(
        self, article_id: ArticleId, content: str, article: Article,
        user: User | None = None,
    ) -> ArticleId:
        self._authorize(user, article_id, "revise")
        extra: Extra = {"content": content, "article": article}
        return execute("revise", extra, article_id, self.lifecycle)

    def publish(
        self, article_id: ArticleId, article: Article,
        user: User | None = None,
    ) -> ArticleId:
        self._authorize(user, article_id, "publish")
        return execute("publish", {"article": article}, article_id, self.lifecycle)

    def delete(
        self, article_id: ArticleId, user: User | None = None,
    ) -> ArticleId:
        self._authorize(user, article_id, "delete")
        return execute("delete", {}, article_id, self.lifecycle)

    def review(
        self, article_id: ArticleId, review: Review, scores_json: str,
        user: User | None = None,
    ) -> ArticleId:
        self._authorize(user, article_id, "review")
        extra: Extra = {"review": review, "scores": scores_json}
        return execute("review", extra, article_id, self.lifecycle)

    def _authorize(
        self, user: User | None, article_id: ArticleId, action: str,
    ) -> None:
        if self.authorizer is None or user is None:
            return
        article = self.storage.meta.read(article_id)
        if not self.authorizer.authorize(user, article, action):
            raise NotAuthorizedError(
                f"User {user.id.id!r} is not authorized to {action} "
                f"article {article_id.id!r}",
                permission=action,
                resource_type="article",
                resource_id=article_id.id,
            )

    # ── Storage convenience ──────────────────────────────────────────────

    def read_meta(self, article_id: ArticleId) -> Article:
        return self.storage.meta.read(article_id)

    def read_user(self, user_id: UserId) -> User:
        return self.users.read(user_id)

    # ── Compiler ─────────────────────────────────────────────────────────

    def compile(self, article_id: ArticleId, fmt: Format) -> bytes:
        if self.compiler is None:
            raise RuntimeError("No compiler configured")
        content_ref = self.storage.content.read(article_id)
        body = self.storage.content.read_body(content_ref)
        return self.compiler.compile(body, fmt)
