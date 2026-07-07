"""Reference fixtures — in-memory backends for all protocols."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from peerpedia_core.exceptions import BadRequestError
from peerpedia_core.protocols.auth import AuthResult
from peerpedia_core.protocols.lifecycle import (
    Lifecycle, Evaluation, Extra, _UNIVERSAL_ACTIONS,
)
from peerpedia_core.protocols.storage import (
    ArticleContentStorage, ArticleMetaStorage, ArticleStorage,
)
from peerpedia_core.protocols.review_storage import ReviewStorage
from peerpedia_core.protocols.sync import ArticleSync, ReviewSync
from peerpedia_core.protocols.user_storage import UserStorage
from peerpedia_core.types import (
    Article, ArticleDiff, ArticleId, ContentRef, Format,
    HistoryEntry, Review, ReviewId, Scores, User, UserId, Version,
)
from peerpedia_core.types.queries import ArticleQuery

_MD = Format(name="markdown")


# ═══════════════════════════════════════════════════════════════════════════
# Article storage backends
# ═══════════════════════════════════════════════════════════════════════════

class MemMetaStorage:
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
    def __init__(self):
        self._blobs: dict[str, str] = {}
        self._repos: dict[str, ContentRef] = {}
        self._versions: dict[str, list[Version]] = {}

    def create(self, key: ArticleId, fmt: Format) -> Version:
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
    def __init__(self):
        self.meta = MemMetaStorage()
        self.content = MemContentStorage()
        self.reviews: dict[str, MemReviewStorage] = {}
        self.users = MemUserStorage()

    def get_meta(self, key: ArticleId | None = None) -> ArticleMetaStorage:
        return self.meta

    def get_content(self, key: ArticleId | None = None) -> ArticleContentStorage:
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
        return self.read_meta(key)


# ═══════════════════════════════════════════════════════════════════════════
# Domain backends
# ═══════════════════════════════════════════════════════════════════════════

class MemUserStorage:
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
    def __init__(self):
        self._rows: dict[str, Review] = {}

    def create(self, article_id: ArticleId, reviewer_id: UserId) -> Review:
        r = Review(
            id=ReviewId(id=f"rev-{article_id.id}-{reviewer_id.id}"),
            article_id=article_id, reviewer_id=reviewer_id,
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


# ═══════════════════════════════════════════════════════════════════════════
# Lifecycle
# ═══════════════════════════════════════════════════════════════════════════

class MemLifecycle:
    def __init__(self, storage: MemArticleStorage):
        self.storage = storage

    @property
    def actions(self) -> frozenset[str]:
        return _UNIVERSAL_ACTIONS

    def compatible(self, action: str, context: ArticleId | None, extra: Extra) -> bool:
        return action in self.actions

    def resolve(self, action: str) -> Evaluation:
        from peerpedia_core.protocols.lifecycle import (
            action_create, action_revise, action_publish,
            action_delete, action_review,
        )
        s = self.storage
        if action == "create":
            return lambda extra, ctx: action_create(extra, ctx, s)
        if action == "revise":
            return lambda extra, ctx: action_revise(extra, ctx, s)
        if action == "publish":
            return lambda extra, ctx: action_publish(extra, ctx, s)
        if action == "delete":
            return lambda extra, ctx: action_delete(extra, ctx, s)
        if action == "review":
            return lambda extra, ctx: action_review(extra, ctx, s)
        raise BadRequestError(f"Unknown action: {action}")


class MemScoringEngine:
    def compute(self, reviews: list[Review]) -> Scores:
        dims: dict[str, list[float]] = {}
        for r in reviews:
            for dim, val in r.scores.dimensions.items():
                dims.setdefault(dim, []).append(val)
        return Scores(dimensions={
            d: sum(vals) / len(vals) for d, vals in dims.items()
        })


# ═══════════════════════════════════════════════════════════════════════════
# Sync
# ═══════════════════════════════════════════════════════════════════════════

class MemArticleSync:
    def __init__(self):
        self._registry: dict[str, dict[str, tuple[bytes, Version]]] = {}

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
    def __init__(self):
        self._registry: dict[str, dict[str, bytes]] = {}

    def push(self, peer_url: str, article_id: ArticleId, reviewer_id: UserId,
             data: bytes, since: Version | None = None) -> Version:
        self._registry.setdefault(peer_url, {})[f"{article_id.id}/{reviewer_id.id}"] = data
        return Version(id=f"v-{time.monotonic_ns()}")

    def pull(self, peer_url: str, article_id: ArticleId, reviewer_id: UserId,
             since: Version | None = None) -> bytes | None:
        return self._registry.get(peer_url, {}).get(f"{article_id.id}/{reviewer_id.id}")


# ═══════════════════════════════════════════════════════════════════════════
# Auth
# ═══════════════════════════════════════════════════════════════════════════

class MemAuthProvider:
    def sign(self, method: str, path: str, user_id: UserId,
             private_key: bytes, pubkey_hex: str, body: bytes = b"") -> str:
        return f"Peerpedia {user_id.id}:{pubkey_hex}:0:abc:ff"

    def verify(self, header_value: str, method: str, path: str,
               body: bytes = b"") -> AuthResult:
        return AuthResult(ok=True, user_id=UserId(id="alice"))
