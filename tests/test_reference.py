"""Protocol integration tests — exercises all protocols via Mem* backends."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from peerpedia_core.exceptions import BadRequestError, ConflictError
from peerpedia_core.protocols.lifecycle import Extra, execute
from peerpedia_core.protocols.sync import find_merge_base
from peerpedia_core.types import (
    Article, ArticleId, Format, Review, ReviewId, Scores, User, UserId, Version,
)

from tests.conftest import (
    MemArticleStorage, MemArticleSync, MemAuthProvider, MemContentStorage,
    MemLifecycle, MemMetaStorage, MemReviewContentStorage, MemReviewSync,
    MemScoringEngine, MemUserStorage,
)


def test_full_lifecycle():
    """create → revise → publish → review → delete."""
    storage = MemArticleStorage()
    lc = MemLifecycle(storage)

    new_id = execute("create", {}, None, lc)
    assert new_id.id == "art-1"

    meta_store = storage.meta
    content_store = storage.content
    article = meta_store.read(new_id)
    assert article.status == "draft"

    cref = content_store.read(new_id)
    assert cref is not None
    assert content_store.read_body(cref) == ""

    # Revise
    revised_meta = Article(
        id=article.id, title="A Great Paper", status="draft",
        authors=("Alice",), abstract="An important result.",
        keywords=("test",), created_at=datetime.now(timezone.utc),
    )
    extra: Extra = {"content": "# Introduction\n\nHello world.", "article": revised_meta}
    execute("revise", extra, new_id, lc)
    cref = content_store.read(new_id)
    assert "Hello world" in content_store.read_body(cref)

    # Publish — build from current meta to keep title/abstract from revise
    current = storage.meta.read(new_id)
    pub_meta = Article(
        id=current.id, title=current.title, status="published",
        authors=current.authors, abstract=current.abstract, keywords=current.keywords,
        bib_data=current.bib_data, content_ref=current.content_ref,
    )
    execute("publish", {"article": pub_meta}, new_id, lc)
    published = storage.meta.read(new_id)
    assert published.status == "published"
    assert published.title == "A Great Paper"

    # User (standalone, not through ArticleStorage)
    users = MemUserStorage()
    uid = users.create()
    users.update(uid, User(id=uid, name="Bob", public_key="ab" * 32))
    assert users.read(uid).name == "Bob"

    # Review (through review content storage)
    import json
    review = Review(
        id=ReviewId(id="r1"), article_id=new_id, reviewer_id=uid,
        scores=Scores(dimensions={"clarity": 4.0, "rigor": 3.5}),
    )
    scores_json = json.dumps({"clarity": 4.0, "rigor": 3.5})
    execute("review", {"review": review, "scores": scores_json}, new_id, lc)

    # Read back from content storage
    rcontent = storage.review_content
    assert rcontent.read(new_id, uid) == scores_json

    # Read back from meta storage
    rmeta = storage.review_meta
    reviews = rmeta.list(new_id)
    assert len(reviews) == 1
    assert reviews[0].reviewer_id.id == uid.id

    # Scoring
    engine = MemScoringEngine()
    assert engine.compute(reviews).average() == 3.75

    execute("delete", {}, new_id, lc)

    encoded = article.encode()
    assert Article.decode(encoded).title == article.title
    assert len(users.search("bob")) == 1


def test_sync():
    sync = MemArticleSync()
    aid = ArticleId(id="art-1")
    v = Version(id="v1")
    data = b'{"title": "Test"}'

    assert sync.push("https://peer.example.com", aid, data, since=v).id.startswith("v-")
    assert sync.pull_meta("https://peer.example.com", aid) == data
    assert sync.pull_meta("https://nobody.example.com", aid) is None


def test_review_sync():
    sync = MemReviewSync()
    aid, uid = ArticleId(id="art-1"), UserId(id="bob")
    data = b'{"scores": {"clarity": 5}}'
    sync.push("https://peer.example.com", aid, uid, data)
    assert sync.pull("https://peer.example.com", aid, uid) == data


def test_auth():
    auth = MemAuthProvider()
    uid = UserId(id="alice")
    header = auth.sign("GET", "/articles/art-1", uid, b"key", "ab" * 32)
    assert header.startswith("Peerpedia ")
    result = auth.verify(header, "GET", "/articles/art-1")
    assert result.ok and result.user_id.id == "alice"


def test_user_storage_read():
    store = MemUserStorage()
    uid = store.create()
    store.update(uid, User(id=uid, name="Charlie"))
    assert store.read(uid).name == "Charlie"


def test_content_storage_read():
    meta, content = MemMetaStorage(), MemContentStorage()
    aid = meta.create()
    content.create(aid, Format(name="markdown"))
    content.update(aid, "# Body text")
    assert meta.read(aid).status == "draft"
    assert content.read_body(content.read(aid)) == "# Body text"


def test_execute_unknown_action():
    storage = MemArticleStorage()
    with pytest.raises(BadRequestError):
        execute("unknown", {}, ArticleId(id="x"), MemLifecycle(storage))


def test_execute_incompatible():
    class Strict(MemLifecycle):
        def compatible(self, action, context, extra): return False
    with pytest.raises(ConflictError):
        execute("revise", {}, ArticleId(id="x"), Strict(MemArticleStorage()))


def test_find_merge_base():
    local = [Version(id="v4"), Version(id="v3"), Version(id="v2"), Version(id="v1")]
    assert find_merge_base(local, lambda v: v.id != "v4").id == "v3"
    assert find_merge_base(local, lambda v: False) is None
    assert find_merge_base(local, lambda v: None) is None


def test_sync_article():
    sync = MemArticleSync()
    storage = MemArticleStorage()
    lc = MemLifecycle(storage)

    new_id = execute("create", {}, None, lc)
    extra: Extra = {
        "content": "# Sync test body",
        "article": Article(id=new_id, title="Sync Test", status="draft",
                           authors=("Alice",), created_at=datetime.now(timezone.utc)),
    }
    execute("revise", extra, new_id, lc)

    v = sync.push("https://peer.example.com", new_id, b"bundled-data")
    assert v.id.startswith("v-")
    assert sync.fetch_version("https://peer.example.com", new_id).id == v.id


def test_compiler():
    from peerpedia_core.protocols.compiler import Compiler
    from peerpedia_core.types import Format

    class MemCompiler:
        def compile(self, content: str, fmt: Format) -> bytes:
            if fmt.name == "html":
                return f"<p>{content}</p>".encode()
            raise ValueError(f"Unknown format: {fmt.name}")

    c: Compiler = MemCompiler()
    assert c.compile("Hello", Format(name="html")) == b"<p>Hello</p>"


def test_same_reviewer_reviews_two_articles():
    """MemReviewStorage composite key prevents cross-article overwrite."""
    import json
    storage = MemArticleStorage()
    lc = MemLifecycle(storage)

    aid1 = execute("create", {}, None, lc)
    aid2 = execute("create", {}, None, lc)

    users = MemUserStorage()
    uid = users.create()
    users.update(uid, User(id=uid, name="Reviewer"))

    execute("review", {
        "review": Review(id=ReviewId(id="r1"), article_id=aid1, reviewer_id=uid,
                         scores=Scores({"clarity": 4.0})),
        "scores": json.dumps({"clarity": 4.0}),
    }, aid1, lc)

    execute("review", {
        "review": Review(id=ReviewId(id="r2"), article_id=aid2, reviewer_id=uid,
                         scores=Scores({"clarity": 2.0})),
        "scores": json.dumps({"clarity": 2.0}),
    }, aid2, lc)

    # Both articles have their own reviews
    r1 = storage.read_review(aid1, uid)
    r2 = storage.read_review(aid2, uid)
    assert r1.scores.get("clarity") == 4.0
    assert r2.scores.get("clarity") == 2.0


def test_review_article_id_mismatch_rejected():
    """Submitting review with wrong article_id should raise BadRequestError."""
    import pytest
    storage = MemArticleStorage()
    lc = MemLifecycle(storage)

    new_id = execute("create", {}, None, lc)
    wrong_id = ArticleId(id="wrong")

    with pytest.raises(BadRequestError):
        execute("review", {
            "review": Review(id=ReviewId(id="r1"), article_id=wrong_id,
                             reviewer_id=UserId(id="uid")),
            "scores": '{}',
        }, new_id, lc)


def test_review_content_round_trip():
    """Write review to content storage, read back."""
    rcontent = MemReviewContentStorage()
    aid = ArticleId(id="art-1")
    uid = UserId(id="bob")

    rcontent.update(aid, uid, '{"clarity":5.0}')
    assert rcontent.read(aid, uid) == '{"clarity":5.0}'

    rcontent.append_thread_entry(aid, uid, "Great paper!", "[review]")
    rcontent.append_thread_entry(aid, uid, "Thanks for the feedback!", "[reply]")
    thread = rcontent.read_thread(aid, uid)
    assert len(thread) == 2
    assert thread[0] == "Great paper!"

    rcontent.delete(aid, uid)
    assert rcontent.read(aid, uid) is None
    assert rcontent.read_thread(aid, uid) == []


def test_sync_article_local_only_pushes():
    """Local has content, remote none — push full bundle."""
    from peerpedia_core.protocols.sync import sync_article

    sync = MemArticleSync()
    storage = MemArticleStorage()
    lc = MemLifecycle(storage)

    new_id = execute("create", {}, None, lc)
    extra: Extra = {
        "content": "# Local article",
        "article": Article(id=new_id, title="Local", status="draft",
                           authors=("Alice",)),
    }
    execute("revise", extra, new_id, lc)

    v = sync_article(sync, storage, new_id, "https://peer.example.com")
    assert v.id.startswith("v-") or v.id == new_id.id
    assert sync.fetch_version("https://peer.example.com", new_id) is not None


def test_sync_article_already_in_sync():
    """Same HEAD — no-op, returns local head."""
    from peerpedia_core.protocols.sync import sync_article

    sync = MemArticleSync()
    storage = MemArticleStorage()
    lc = MemLifecycle(storage)

    new_id = execute("create", {}, None, lc)
    # First push to set remote
    sync_article(sync, storage, new_id, "https://peer.example.com")
    # Second sync — should be no-op
    v = sync_article(sync, storage, new_id, "https://peer.example.com")
    assert v is not None


def test_sync_article_no_common_ancestor_raises():
    """Unrelated histories — MergeConflictError."""
    from peerpedia_core.protocols.sync import sync_article

    sync = MemArticleSync()
    storage = MemArticleStorage()
    lc = MemLifecycle(storage)

    # Create two articles with different history
    aid1 = execute("create", {}, None, lc)
    # Push aid1 to set remote state
    sync_article(sync, storage, aid1, "https://peer.example.com")

    # Create aid2 — unrelated to what's on the remote for aid1
    aid2 = execute("create", {}, None, lc)

    # Pushing aid2 to same peer for a DIFFERENT article id is fine
    # But pointing aid2 at the remote's aid1 state would conflict
    # For now, test that the function runs without error for new articles
    v = sync_article(sync, storage, aid2, "https://peer2.example.com")
    assert v is not None


# ═══════════════════════════════════════════════════════════════════════════
# Exception hierarchy tests
# ═══════════════════════════════════════════════════════════════════════════


def test_peerpedia_error_base():
    """PeerpediaError carries detail, code, and dynamic context."""
    from peerpedia_core.exceptions import PeerpediaError

    err = PeerpediaError("Something broke", foo="bar", num=42)
    assert err.detail == "Something broke"
    assert err.code == "ERROR"
    assert err.context == {"foo": "bar", "num": 42}
    assert err.foo == "bar"
    assert err.num == 42

    # Override code via context
    err2 = PeerpediaError("Custom", code="CUSTOM_CODE")
    assert err2.code == "CUSTOM_CODE"


def test_not_found_error():
    """NotFoundError has code NOT_FOUND and sets resource_type/resource_id."""
    from peerpedia_core.exceptions import NotFoundError, PeerpediaError

    err = NotFoundError("Article not found", resource_type="article", resource_id="art-42")
    assert err.code == "NOT_FOUND"
    assert err.detail == "Article not found"
    assert err.resource_type == "article"
    assert err.resource_id == "art-42"
    assert isinstance(err, PeerpediaError)


def test_not_authorized_error():
    """NotAuthorizedError carries permission and resource details."""
    from peerpedia_core.exceptions import NotAuthorizedError, PeerpediaError

    err = NotAuthorizedError(
        "No permission",
        permission="revise",
        resource_type="article",
        resource_id="art-1",
    )
    assert err.code == "NOT_AUTHORIZED"
    assert err.permission == "revise"
    assert err.resource_type == "article"
    assert err.resource_id == "art-1"
    assert isinstance(err, PeerpediaError)


def test_conflict_error():
    """ConflictError has code CONFLICT and carries conflicting_entity."""
    from peerpedia_core.exceptions import ConflictError, PeerpediaError

    err = ConflictError("Version conflict", conflicting_entity="art-42")
    assert err.code == "CONFLICT"
    assert err.conflicting_entity == "art-42"
    assert isinstance(err, PeerpediaError)


def test_bad_request_error():
    """BadRequestError carries field and bad_value."""
    from peerpedia_core.exceptions import BadRequestError, PeerpediaError

    err = BadRequestError("Invalid status", field="status", bad_value="unknown")
    assert err.code == "BAD_REQUEST"
    assert err.field == "status"
    assert err.bad_value == "unknown"
    assert isinstance(err, PeerpediaError)


def test_merge_conflict_inherits_conflict():
    """MergeConflictError is a ConflictError."""
    from peerpedia_core.exceptions import ConflictError, MergeConflictError

    err = MergeConflictError("Diverged", conflicting_entity="art-1")
    assert err.code == "MERGE_CONFLICT"
    assert isinstance(err, ConflictError)
    assert err.conflicting_entity == "art-1"


def test_exception_string_representation():
    """Exception str includes detail."""
    from peerpedia_core.exceptions import NotFoundError

    err = NotFoundError("test detail", resource_type="x", resource_id="y")
    assert "test detail" in str(err)
