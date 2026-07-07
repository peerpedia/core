"""Protocol integration tests — exercises all protocols via Mem* backends."""
from __future__ import annotations

from datetime import datetime, timezone

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

    meta_store = storage.get_meta(new_id)
    content_store = storage.get_content(new_id)
    article = new_id.deref_meta(meta_store)
    assert article.status == "draft"

    cref = new_id.deref_content(content_store)
    assert cref is not None
    assert cref.deref(content_store) == ""

    # Revise
    revised_meta = Article(
        id=article.id, title="A Great Paper", status="draft",
        authors=("Alice",), abstract="An important result.",
        keywords=("test",), created_at=datetime.now(timezone.utc),
    )
    extra: Extra = {"content": "# Introduction\n\nHello world.", "article": revised_meta}
    execute("revise", extra, new_id, lc)
    cref = new_id.deref_content(content_store)
    assert "Hello world" in cref.deref(content_store)

    # Publish
    pub_meta = Article(
        id=article.id, title=article.title, status="published",
        authors=article.authors, abstract=article.abstract, keywords=article.keywords,
        bib_data=article.bib_data, content_ref=article.content_ref,
    )
    execute("publish", {"article": pub_meta}, new_id, lc)
    assert storage.read_meta(new_id).status == "published"

    # User (standalone, not through ArticleStorage)
    users = MemUserStorage()
    uid = users.create()
    users.update(uid, User(id=uid, name="Bob", public_key="ab" * 32))
    assert uid.deref(users).name == "Bob"

    # Review (through review content storage)
    import json
    review = Review(
        id=ReviewId(id="r1"), article_id=new_id, reviewer_id=uid,
        scores=Scores(dimensions={"clarity": 4.0, "rigor": 3.5}),
    )
    scores_json = json.dumps({"clarity": 4.0, "rigor": 3.5})
    execute("review", {"review": review, "scores": scores_json}, new_id, lc)

    # Read back from content storage
    rcontent = storage.get_review_content(new_id)
    assert rcontent.read_scores(new_id, uid) == scores_json

    # Read back from meta storage
    rmeta = storage.get_review_meta(new_id)
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


def test_userid_deref():
    store = MemUserStorage()
    uid = store.create()
    store.update(uid, User(id=uid, name="Charlie"))
    assert uid.deref(store).name == "Charlie"


def test_deref_chain():
    meta, content = MemMetaStorage(), MemContentStorage()
    aid = meta.create()
    content.create(aid, Format(name="markdown"))
    content.update(aid, "# Body text")
    assert aid.deref_meta(meta).status == "draft"
    assert aid.deref_content(content).deref(content) == "# Body text"


def test_execute_unknown_action():
    storage = MemArticleStorage()
    try:
        execute("unknown", {}, ArticleId(id="x"), MemLifecycle(storage))
        assert False
    except BadRequestError:
        pass


def test_execute_incompatible():
    class Strict(MemLifecycle):
        def compatible(self, action, context, extra): return False
    try:
        execute("revise", {}, ArticleId(id="x"), Strict(MemArticleStorage()))
        assert False
    except ConflictError:
        pass


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


def test_review_content_round_trip():
    """Write review to content storage, read back."""
    rcontent = MemReviewContentStorage()
    aid = ArticleId(id="art-1")
    uid = UserId(id="bob")

    rcontent.write_scores(aid, uid, '{"clarity":5.0}')
    assert rcontent.read_scores(aid, uid) == '{"clarity":5.0}'

    rcontent.write_thread_entry(aid, uid, "Great paper!", "[review]")
    rcontent.write_thread_entry(aid, uid, "Thanks for the feedback!", "[reply]")
    thread = rcontent.read_thread(aid, uid)
    assert len(thread) == 2
    assert thread[0] == "Great paper!"

    rcontent.delete_review_dir(aid, uid)
    assert rcontent.read_scores(aid, uid) is None
    assert rcontent.read_thread(aid, uid) == []
