"""Tests for the Peerpedia facade — wires protocols into a usable engine."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from peerpedia_core import Peerpedia
from peerpedia_core.exceptions import NotAuthorizedError
from peerpedia_core.protocols.authorizer import Authorizer
from peerpedia_core.protocols.lifecycle import Extra, execute
from peerpedia_core.types import (
    Article, ArticleId, Review, ReviewId, Scores, User, UserId,
)
from tests.conftest import (
    MemArticleStorage, MemLifecycle, MemUserStorage,
)


def _make_peerpedia(**kw) -> Peerpedia:
    """Factory — creates a wired Peerpedia with Mem* backends."""
    storage = kw.pop("storage", MemArticleStorage())
    lifecycle = kw.pop("lifecycle", MemLifecycle(storage))
    users = kw.pop("users", MemUserStorage())
    return Peerpedia(
        storage=storage,
        lifecycle=lifecycle,
        user_storage=users,
        **kw,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Lifecycle actions
# ═══════════════════════════════════════════════════════════════════════════


def test_create_article():
    """Peerpedia.create() returns a valid ArticleId."""
    pp = _make_peerpedia()
    aid = pp.create()
    assert isinstance(aid, ArticleId)
    assert aid.id.startswith("art-")


def test_revise_article():
    """Peerpedia.revise() updates content and metadata."""
    pp = _make_peerpedia()
    aid = pp.create()

    article = Article(
        id=aid, title="My Paper", status="draft",
        authors=("Alice",), abstract="A great result.",
    )
    pp.revise(aid, content="# Hello World", article=article)

    cref = pp.storage.content.read(aid)
    assert "Hello World" in pp.storage.content.read_body(cref)
    assert pp.storage.meta.read(aid).title == "My Paper"


def test_publish_article():
    """Peerpedia.publish() transitions status to published."""
    pp = _make_peerpedia()
    aid = pp.create()

    article = Article(
        id=aid, title="My Paper", status="published",
        authors=("Alice",),
    )
    pp.publish(aid, article=article)

    published = pp.storage.meta.read(aid)
    assert published.status == "published"
    assert published.title == "My Paper"


def test_delete_article():
    """Peerpedia.delete() removes the article."""
    pp = _make_peerpedia()
    aid = pp.create()

    pp.delete(aid)

    with pytest.raises(Exception):
        pp.storage.meta.read(aid)


def test_review_article():
    """Peerpedia.review() creates a review with scores."""
    pp = _make_peerpedia()
    aid = pp.create()

    users = MemUserStorage()
    uid = users.create()
    users.update(uid, User(id=uid, name="Bob"))

    import json

    review = Review(
        id=ReviewId(id="r1"), article_id=aid, reviewer_id=uid,
        scores=Scores(dimensions={"clarity": 5.0, "rigor": 4.0}),
    )
    pp.review(aid, review=review, scores_json=json.dumps({"clarity": 5.0, "rigor": 4.0}))

    reviews = pp.storage.review_meta.list(aid)
    assert len(reviews) == 1
    assert reviews[0].reviewer_id.id == uid.id


def test_full_lifecycle_via_facade():
    """create → revise → publish → review → delete via Peerpedia facade."""
    pp = _make_peerpedia()
    aid = pp.create()

    # Revise
    article = Article(
        id=aid, title="Full Cycle", status="draft",
        authors=("Alice",),
    )
    pp.revise(aid, content="# Body", article=article)

    # Publish
    article = Article(
        id=aid, title="Full Cycle", status="published",
        authors=("Alice",),
    )
    pp.publish(aid, article=article)

    published = pp.storage.meta.read(aid)
    assert published.status == "published"

    pp.delete(aid)
    with pytest.raises(Exception):
        pp.storage.meta.read(aid)


# ═══════════════════════════════════════════════════════════════════════════
# Storage convenience
# ═══════════════════════════════════════════════════════════════════════════


def test_read_meta():
    """Peerpedia.read_meta() returns article metadata."""
    pp = _make_peerpedia()
    aid = pp.create()

    article = pp.read_meta(aid)
    assert isinstance(article, Article)
    assert article.id == aid


def test_read_user():
    """Peerpedia.read_user() returns user data."""
    pp = _make_peerpedia()

    uid = pp.users.create()
    pp.users.update(uid, User(id=uid, name="Charlie"))

    user = pp.read_user(uid)
    assert user.name == "Charlie"


# ═══════════════════════════════════════════════════════════════════════════
# Authorization
# ═══════════════════════════════════════════════════════════════════════════


class AllowAuthorizer:
    """Authorizer that allows everything."""

    def authorize(self, user: User, article: Article, action: str) -> bool:
        return True


class DenyAuthorizer:
    """Authorizer that denies everything."""

    def authorize(self, user: User, article: Article, action: str) -> bool:
        return False


def test_authorize_allows_with_authorizer():
    """Authorized action succeeds when authorizer returns True."""
    pp = _make_peerpedia(
        authorizer=AllowAuthorizer(),
    )
    aid = pp.create()
    article = Article(id=aid, title="T", status="draft")
    user = User(id=UserId(id="alice"), name="Alice")

    # Should not raise
    pp.revise(aid, content="# Ok", article=article, user=user)


def test_authorize_denies_with_authorizer():
    """Unauthorized action raises NotAuthorizedError."""
    pp = _make_peerpedia(
        authorizer=DenyAuthorizer(),
    )
    aid = pp.create()
    article = Article(id=aid, title="T", status="draft")
    user = User(id=UserId(id="alice"), name="Alice")

    with pytest.raises(NotAuthorizedError) as exc:
        pp.revise(aid, content="# Nope", article=article, user=user)

    assert exc.value.permission == "revise"
    assert exc.value.resource_type == "article"


def test_authorize_skipped_without_authorizer():
    """No authorizer → no auth check, even with user passed."""
    pp = _make_peerpedia()  # no authorizer
    aid = pp.create()

    user = User(id=UserId(id="anyone"), name="Anyone")
    article = Article(id=aid, title="T", status="draft")
    pp.revise(aid, content="# Fine", article=article, user=user)  # no raise


def test_authorize_skipped_without_user():
    """Authorizer configured but no user passed → no auth check."""
    pp = _make_peerpedia(authorizer=DenyAuthorizer())
    aid = pp.create()

    article = Article(id=aid, title="T", status="draft")
    # user is None — skips auth
    pp.revise(aid, content="# Fine", article=article)


# ═══════════════════════════════════════════════════════════════════════════
# Compiler
# ═══════════════════════════════════════════════════════════════════════════


class MemCompiler:
    """A simple in-memory compiler for testing."""

    def compile(self, content: str, fmt: str) -> bytes:
        if fmt == "html":
            return f"<p>{content}</p>".encode()
        raise ValueError(f"Unknown format: {fmt}")


def test_compile_with_compiler():
    """Peerpedia.compile() returns compiled output."""
    pp = _make_peerpedia(compiler=MemCompiler())
    aid = pp.create()

    article = Article(id=aid, title="T", status="draft", content_ref=None)
    pp.revise(aid, content="# Hello", article=article)

    result = pp.compile(aid, "html")
    # Body includes frontmatter from MemContentStorage.write_article
    assert b"Hello" in result
    assert result.startswith(b"<p>")


def test_compile_without_compiler_raises():
    """Peerpedia.compile() raises RuntimeError without compiler."""
    pp = _make_peerpedia()

    with pytest.raises(RuntimeError, match="No compiler configured"):
        pp.compile(ArticleId(id="x"), "html")
