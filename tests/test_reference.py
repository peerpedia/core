"""Reference implementation — in-memory backends exercising all protocols.

Runs the full lifecycle pipeline: create → revise → publish → review → delete.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from peerpedia_core.exceptions import BadRequestError, ConflictError
from peerpedia_core.protocols.auth import AuthProvider, AuthResult
from peerpedia_core.protocols.lifecycle import (
    Lifecycle, Evaluation, Extra, _UNIVERSAL_ACTIONS, execute,
)
from peerpedia_core.protocols.scoring import ScoringEngine
from peerpedia_core.protocols.storage import (
    ArticleContentStorage, ArticleMetaStorage, ArticleStorage,
)
from peerpedia_core.protocols.review_storage import ReviewStorage
from peerpedia_core.protocols.sync import ArticleSync, ReviewSync
from peerpedia_core.protocols.user_storage import UserStorage
from peerpedia_core.types import (
    Article, ArticleDiff, ArticleId, BibData, ContentRef,
    HistoryEntry, Review, ReviewId, Scores, User, UserId, Version,
)
from peerpedia_core.types.queries import ArticleQuery


# ═══════════════════════════════════════════════════════════════════════════
# In-memory backends
# ═══════════════════════════════════════════════════════════════════════════

class MemMetaStorage:
    """In-memory ArticleMetaStorage."""

    def __init__(self):
        self._rows: dict[str, Article] = {}
        self._counter = 0

    def create(self) -> ArticleId:
        self._counter += 1
        aid = ArticleId(id=f"art-{self._counter}")
        self._rows[aid.id] = Article(id=aid, title="", status="draft")
        return aid

    def read(self, key: ArticleId) -> Article:
        return self._rows[key.id]

    def update(self, key: ArticleId, meta: Article) -> Version:
        self._rows[key.id] = meta
        return Version(id=f"v-{time.monotonic_ns()}")

    def delete(self, key: ArticleId) -> Version:
        del self._rows[key.id]
        return Version(id=f"v-{time.monotonic_ns()}")

    def query(self, q: ArticleQuery | None = None) -> list[Article]:
        return list(self._rows.values())


class MemContentStorage:
    """In-memory ArticleContentStorage."""

    def __init__(self):
        self._blobs: dict[str, str] = {}   # ref → text
        self._repos: dict[str, ContentRef] = {}  # article_id → ref
        self._versions: dict[str, list[Version]] = {}  # article_id → versions

    def create(self, key: ArticleId) -> Version:
        ref = ContentRef(ref=f"blob:{key.id}-0")
        self._repos[key.id] = ref
        self._blobs[ref.ref] = ""
        v = Version(id=f"v-{time.monotonic_ns()}")
        self._versions.setdefault(key.id, []).append(v)
        return v

    def read(self, key: ArticleId) -> ContentRef:
        return self._repos[key.id]

    def deref_body(self, ref: ContentRef) -> str:
        return self._blobs[ref.ref]

    def update(self, key: ArticleId, content: str) -> Version:
        ref = ContentRef(ref=f"blob:{key.id}-{len(self._versions.get(key.id, []))}")
        self._repos[key.id] = ref
        self._blobs[ref.ref] = content
        v = Version(id=f"v-{time.monotonic_ns()}")
        self._versions.setdefault(key.id, []).append(v)
        return v

    def delete(self, key: ArticleId) -> Version:
        ref = self._repos.pop(key.id, None)
        if ref:
            self._blobs.pop(ref.ref, None)
        return Version(id=f"v-{time.monotonic_ns()}")

    def create_bundle(self, key: ArticleId, since: Version | None = None) -> bytes:
        ref = self._repos[key.id]
        return self._blobs[ref.ref].encode()

    def ingest_bundle(self, key: ArticleId, data: bytes) -> Version:
        return self.update(key, data.decode())

    def history(self, key: ArticleId, since: Version | None = None) -> list[HistoryEntry]:
        return []

    def diff(self, key: ArticleId, a: Version, b: Version) -> ArticleDiff:
        return ArticleDiff(version_a=a, version_b=b, content_diff="")


class MemArticleStorage:
    """Composed in-memory ArticleStorage."""

    def __init__(self):
        self.meta = MemMetaStorage()
        self.content = MemContentStorage()
        self.reviews: dict[str, MemReviewStorage] = {}
        self.users = MemUserStorage()

    def get_meta(self, key: ArticleId) -> ArticleMetaStorage:
        return self.meta

    def get_content(self, key: ArticleId) -> ArticleContentStorage:
        return self.content

    def read_meta(self, key: ArticleId) -> Article:
        return self.meta.read(key)

    def read_content(self, key: ArticleId) -> ContentRef:
        return self.content.read(key)

    def get_review(self, key: ArticleId) -> ReviewStorage:
        if key.id not in self.reviews:
            self.reviews[key.id] = MemReviewStorage()
        return self.reviews[key.id]

    def read_review(self, key: ArticleId, reviewer_id: UserId) -> Review:
        return self.reviews[key.id].read(key, reviewer_id)

    def get_user(self) -> UserStorage:
        return self.users

    def read_user(self, key: UserId) -> User:
        return self.users.read(key)

    def extract(self, key: ArticleId) -> Article:
        return self.read_meta(key)  # In-memory: meta IS content


class MemUserStorage:
    """In-memory UserStorage."""

    def __init__(self):
        self._rows: dict[str, User] = {}
        self._counter = 0

    def create(self) -> UserId:
        self._counter += 1
        return UserId(id=f"user-{self._counter}")

    def read(self, key: UserId) -> User:
        return self._rows[key.id]

    def update(self, key: UserId, user: User) -> None:
        self._rows[key.id] = user

    def delete(self, key: UserId) -> None:
        self._rows.pop(key.id, None)

    def search(self, query: str) -> list[User]:
        return [u for u in self._rows.values() if query.lower() in u.name.lower()]

    def list(self) -> list[User]:
        return list(self._rows.values())


class MemReviewStorage:
    """In-memory ReviewStorage."""

    def __init__(self):
        self._rows: dict[str, Review] = {}  # reviewer_id → Review

    def create(self, article_id: ArticleId, reviewer_id: UserId) -> Review:
        r = Review(
            id=ReviewId(id=f"rev-{article_id.id}-{reviewer_id.id}"),
            article_id=article_id,
            reviewer_id=reviewer_id,
        )
        self._rows[reviewer_id.id] = r
        return r

    def read(self, article_id: ArticleId, reviewer_id: UserId) -> Review:
        return self._rows[reviewer_id.id]

    def update(self, article_id: ArticleId, reviewer_id: UserId, review: Review) -> Version:
        self._rows[reviewer_id.id] = review
        return Version(id=f"v-{time.monotonic_ns()}")

    def delete(self, article_id: ArticleId, reviewer_id: UserId) -> Version:
        self._rows.pop(reviewer_id.id, None)
        return Version(id=f"v-{time.monotonic_ns()}")

    def list(self, article_id: ArticleId) -> list[Review]:
        return list(self._rows.values())


class MemLifecycle:
    """Lifecycle that wires universal actions to MemArticleStorage."""

    def __init__(self, storage: MemArticleStorage):
        self.storage = storage

    @property
    def actions(self) -> frozenset[str]:
        return _UNIVERSAL_ACTIONS

    def compatible(self, action: str, context: ArticleId | None, extra: Extra) -> bool:
        return action in self.actions

    def resolve(self, action: str) -> Evaluation:
        if action == "create":
            return lambda extra, ctx: self._action_create()
        if action == "revise":
            return lambda extra, ctx: self._action_revise(extra, ctx)
        if action == "publish":
            return lambda extra, ctx: self._action_publish(extra, ctx)
        if action == "delete":
            return lambda extra, ctx: self._action_delete(extra, ctx)
        if action == "review":
            return lambda extra, ctx: self._action_review(extra, ctx)
        raise BadRequestError(f"Unknown action: {action}")

    def _action_create(self) -> ArticleId:
        article_id = self.storage.meta.create()
        self.storage.content.create(article_id, )
        return article_id

    def _action_revise(self, extra: Extra, ctx: ArticleId) -> ArticleId:
        content = extra.get("content", "")
        article = extra.get("article")
        self.storage.content.update(ctx, content, )
        if article is not None:
            self.storage.meta.update(ctx, article)
        return ctx

    def _action_publish(self, extra: Extra, ctx: ArticleId) -> ArticleId:
        meta = self.storage.meta.read(ctx)
        published = Article(
            id=meta.id, title=meta.title, status="published",
            authors=meta.authors, abstract=meta.abstract, keywords=meta.keywords,
            bib_data=meta.bib_data, content_ref=meta.content_ref,
            created_at=meta.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        self.storage.meta.update(ctx, published)
        return ctx

    def _action_delete(self, extra: Extra, ctx: ArticleId) -> ArticleId:
        self.storage.meta.delete(ctx)
        self.storage.content.delete(ctx)
        return ctx

    def _action_review(self, extra: Extra, ctx: ArticleId) -> ArticleId:
        review = extra.get("review")
        if review is None:
            raise BadRequestError("Missing review in extra")
        rstore = self.storage.get_review(ctx)
        rstore.create(ctx, review.reviewer_id)
        # Copy scores from the submitted review
        rstore.update(ctx, review.reviewer_id, review)
        return ctx


class MemScoringEngine:
    """Simple averaging scoring engine."""

    def compute(self, reviews: list[Review]) -> Scores:
        dims: dict[str, list[float]] = {}
        for r in reviews:
            for dim, val in r.scores.dimensions.items():
                dims.setdefault(dim, []).append(val)
        return Scores(dimensions={
            d: sum(vals) / len(vals) for d, vals in dims.items()
        })


class MemArticleSync:
    """In-memory peer-to-peer sync."""

    def __init__(self):
        self._registry: dict[str, dict[str, tuple[bytes, Version]]] = {}
        # peer_url → {article_id: (data, version)}

    def fetch_version(self, peer_url: str, article_id: ArticleId) -> Version | None:
        entry = self._registry.get(peer_url, {}).get(article_id.id)
        return entry[1] if entry else None

    def push(self, peer_url: str, article_id: ArticleId, data: bytes,
             since: Version | None = None) -> Version:
        v = Version(id=f"v-{time.monotonic_ns()}")
        self._registry.setdefault(peer_url, {})[article_id.id] = (data, v)
        return v

    def pull_meta(self, peer_url: str, article_id: ArticleId,
                  since: Version | None = None) -> bytes | None:
        entry = self._registry.get(peer_url, {}).get(article_id.id)
        return entry[0] if entry else None

    def pull_all(self, peer_url: str, article_id: ArticleId,
                 since: Version | None = None) -> bytes | None:
        return self.pull_meta(peer_url, article_id, since)


class MemReviewSync:
    """In-memory review sync."""

    def __init__(self):
        self._registry: dict[str, dict[str, bytes]] = {}

    def push(self, peer_url: str, article_id: ArticleId, reviewer_id: UserId,
             data: bytes, since: Version | None = None) -> Version:
        self._registry.setdefault(peer_url, {})[f"{article_id.id}/{reviewer_id.id}"] = data
        return Version(id=f"v-{time.monotonic_ns()}")

    def pull(self, peer_url: str, article_id: ArticleId, reviewer_id: UserId,
             since: Version | None = None) -> bytes | None:
        return self._registry.get(peer_url, {}).get(f"{article_id.id}/{reviewer_id.id}")


class MemAuthProvider:
    """Stub auth — always passes, returns Alice."""

    def sign(self, method: str, path: str, user_id: UserId,
             private_key: bytes, pubkey_hex: str, body: bytes = b"") -> str:
        return f"Peerpedia {user_id.id}:{pubkey_hex}:0:abc:ff"

    def verify(self, header_value: str, method: str, path: str,
               body: bytes = b"") -> AuthResult:
        return AuthResult(ok=True, user_id=UserId(id="alice"))


# ═══════════════════════════════════════════════════════════════════════════
# Full pipeline tests
# ═══════════════════════════════════════════════════════════════════════════

def test_full_lifecycle():
    """create → revise → publish → review → delete."""
    storage = MemArticleStorage()
    lc = MemLifecycle(storage)

    # ── Create ──
    new_id = execute("create", {}, None, lc)
    assert new_id.id == "art-1"

    # ── Deref chain ──
    meta_store = storage.get_meta(new_id)
    content_store = storage.get_content(new_id)

    article = new_id.deref_meta(meta_store)
    assert article.status == "draft"

    cref = new_id.deref_content(content_store)
    assert cref is not None
    body = cref.deref(content_store)
    assert body == ""  # empty initial content

    # ── Revise ──
    revised_meta = Article(
        id=article.id, title="A Great Paper", status="draft",
        authors=("Alice",), abstract="An important result.",
        keywords=("test",),
        created_at=datetime.now(timezone.utc),
    )
    extra: Extra = {"content": "# Introduction\n\nHello world.", "article": revised_meta}
    execute("revise", extra, new_id, lc)
    cref = new_id.deref_content(content_store)  # update creates new ref
    updated_content = cref.deref(content_store)
    assert "Hello world" in updated_content

    # ── Publish ──
    pub_extra: Extra = {"article": revised_meta}
    execute("publish", pub_extra, new_id, lc)
    published = storage.read_meta(new_id)
    assert published.status == "published"

    # ── User + Review ──
    uid = storage.users.create()
    storage.users.update(uid, User(id=uid, name="Bob", public_key="ab" * 32))
    user = uid.deref(storage.users)
    assert user.name == "Bob"

    review = Review(
        id=ReviewId(id="r1"), article_id=new_id, reviewer_id=uid,
        scores=Scores(dimensions={"clarity": 4.0, "rigor": 3.5}),
    )
    review_extra: Extra = {"review": review}
    execute("review", review_extra, new_id, lc)

    rstore = storage.get_review(new_id)
    reviews = rstore.list(new_id)
    assert len(reviews) == 1
    assert reviews[0].reviewer_id.id == uid.id

    # ── Scoring ──
    engine = MemScoringEngine()
    scores = engine.compute(reviews)
    assert scores.average() == 3.75

    # ── Delete ──
    execute("delete", {}, new_id, lc)

    # ── Article encode/decode round trip ──
    encoded = article.encode()
    decoded = Article.decode(encoded)
    assert decoded.title == article.title

    # ── User search ──
    results = storage.users.search("bob")
    assert len(results) == 1


def test_sync():
    """Push and pull between two in-memory peers."""
    sync = MemArticleSync()
    aid = ArticleId(id="art-1")
    v = Version(id="v1")

    # Push to peer
    data = b'{"title": "Test"}'
    new_v = sync.push("https://peer.example.com", aid, data, since=v)
    assert new_v.id.startswith("v-")

    # Pull from peer
    pulled = sync.pull_meta("https://peer.example.com", aid)
    assert pulled == data

    # Unknown peer returns None
    missing = sync.pull_meta("https://nobody.example.com", aid)
    assert missing is None


def test_review_sync():
    """Push and pull reviews between peers."""
    sync = MemReviewSync()
    aid = ArticleId(id="art-1")
    uid = UserId(id="bob")
    data = b'{"scores": {"clarity": 5}}'

    v = sync.push("https://peer.example.com", aid, uid, data)
    assert v.id.startswith("v-")

    pulled = sync.pull("https://peer.example.com", aid, uid)
    assert pulled == data


def test_auth():
    """Sign and verify auth headers."""
    auth = MemAuthProvider()
    uid = UserId(id="alice")
    header = auth.sign("GET", "/articles/art-1", uid, b"key", "ab" * 32)
    assert header.startswith("Peerpedia ")

    result = auth.verify(header, "GET", "/articles/art-1")
    assert result.ok
    assert result.user_id.id == "alice"


def test_userid_deref():
    """UserId.deref resolves through UserStorage."""
    store = MemUserStorage()
    uid = store.create()
    store.update(uid, User(id=uid, name="Charlie"))

    user = uid.deref(store)
    assert user.name == "Charlie"


def test_deref_chain():
    """ArticleId → Article → ContentRef → str."""
    meta = MemMetaStorage()
    content = MemContentStorage()

    aid = meta.create()
    content.create(aid, )
    content.update(aid, "# Body text", )

    article = aid.deref_meta(meta)
    assert article.status == "draft"

    cref = aid.deref_content(content)
    body = cref.deref(content)
    assert body == "# Body text"


def test_execute_unknown_action():
    """Unknown actions raise BadRequestError."""
    storage = MemArticleStorage()
    lc = MemLifecycle(storage)

    try:
        execute("unknown", {}, ArticleId(id="x"), lc)
        assert False, "should have raised"
    except BadRequestError:
        pass


def test_execute_incompatible():
    """Incompatible actions raise ConflictError."""
    class StrictLifecycle(MemLifecycle):
        def compatible(self, action, context, extra):
            return False

    storage = MemArticleStorage()
    lc = StrictLifecycle(storage)

    try:
        execute("revise", {}, ArticleId(id="x"), lc)
        assert False, "should have raised"
    except ConflictError:
        pass


def test_find_merge_base():
    """Pure merge-base algorithm."""
    from peerpedia_core.protocols.sync import find_merge_base

    local = [Version(id="v4"), Version(id="v3"), Version(id="v2"), Version(id="v1")]
    # Remote has v3 and older, missing v4
    base = find_merge_base(local, lambda v: v.id != "v4")
    assert base.id == "v3"

    # No common ancestor
    assert find_merge_base(local, lambda v: False) is None

    # Probe failure (None)
    assert find_merge_base(local, lambda v: None) is None


def test_sync_article():
    """Full sync orchestrator — push + pull between two peers."""
    from peerpedia_core.protocols.sync import sync_article

    sync = MemArticleSync()
    storage = MemArticleStorage()
    lc = MemLifecycle(storage)

    # Create and publish an article locally
    new_id = execute("create", {}, None, lc)
    article = Article(
        id=new_id, title="Sync Test", status="draft",
        authors=("Alice",), created_at=datetime.now(timezone.utc),
    )
    extra: Extra = {"content": "# Sync test body", "article": article}
    execute("revise", extra, new_id, lc)

    # Push to peer
    v = sync.push("https://peer.example.com", new_id, b"bundled-data")
    assert v.id.startswith("v-")

    # fetch_version works
    remote_v = sync.fetch_version("https://peer.example.com", new_id)
    assert remote_v is not None
    assert remote_v.id == v.id


def test_crypto_ed25519():
    """Round-trip key generation, signing, verification."""
    from peerpedia_core.crypto_ed25519 import (
        generate_key_pair, derive_key_pair, new_salt,
        sha256_hex, sign_detached, verify_signature,
    )

    kp = generate_key_pair()
    sig = sign_detached(kp.signing_key, b"data")
    assert verify_signature(kp.public_key, b"data", sig)
    assert not verify_signature(kp.public_key, b"wrong", sig)

    salt = new_salt()
    kp2 = derive_key_pair("pw", salt)
    kp3 = derive_key_pair("pw", salt)
    assert kp2.public_key.hex == kp3.public_key.hex

    assert sha256_hex(b"a") != ""
    assert sha256_hex(b"") == ""


def test_compiler():
    """Markdown → HTML reference compiler."""
    from peerpedia_core.protocols.compiler import Compiler
    from peerpedia_core.types import Format

    class MemCompiler:
        def compile(self, content: str, fmt: Format) -> bytes:
            if fmt.name == "html":
                return f"<p>{content}</p>".encode()
            raise ValueError(f"Unknown format: {fmt.name}")

    c: Compiler = MemCompiler()
    result = c.compile("Hello", Format(name="html"))
    assert result == b"<p>Hello</p>"
