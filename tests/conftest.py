"""Reference fixtures — in-memory backends for all protocols."""
from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import datetime, timezone

from peerpedia_core.exceptions import BadRequestError, NotFoundError
from peerpedia_core.protocols.auth import AuthResult
from peerpedia_core.protocols.lifecycle import (
    Lifecycle, Evaluation, Extra,
)
from peerpedia_core.protocols.storage import (
    ArticleContentStorage, ArticleMetaStorage, ArticleStorage,
    ReviewContentStorage, ReviewMetaStorage, UserStorage,
)
from peerpedia_core.protocols.sync import ArticleSync, ReviewSync
from peerpedia_core.types import (
    Article, ArticleDiff, ArticleId, ContentRef,
    HistoryEntry, Review, ReviewId, Scores, User, UserId, Version,
)
from peerpedia_core.types.queries import ArticleQuery

_MD = "markdown"


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
        try:
            return self._rows[key.id]
        except KeyError:
            raise NotFoundError(
                f"Article {key.id!r} not found",
                resource_type="article", resource_id=key.id,
            ) from None

    def update(self, key: ArticleId, meta: Article) -> Version:
        self._rows[key.id] = meta
        return Version(id=f"v-{time.monotonic_ns()}")

    def delete(self, key: ArticleId) -> Version:
        del self._rows[key.id]
        return Version(id=f"v-{time.monotonic_ns()}")

    def query(self, q: ArticleQuery | None = None) -> list[Article]:
        results = list(self._rows.values())
        if q is None:
            return results

        if q.statuses is not None:
            results = [a for a in results if a.status in q.statuses]
        if q.search is not None:
            term = q.search.lower()
            results = [
                a for a in results
                if term in a.title.lower() or (a.abstract and term in a.abstract.lower())
            ]
        if q.id_prefix is not None:
            results = [a for a in results if a.id.id.startswith(q.id_prefix)]
        if q.offset:
            results = results[q.offset:]
        if q.limit is not None:
            results = results[:q.limit]
        return results


class MemContentStorage:
    def __init__(self):
        self._blobs: dict[str, str] = {}
        self._repos: dict[str, ContentRef] = {}
        self._versions: dict[str, list[Version]] = {}

    def create(self, key: ArticleId, fmt: str) -> Version:
        ref = ContentRef(ref=f"blob:{key.id}-0")
        self._repos[key.id] = ref
        self._blobs[ref.ref] = ""
        v = Version(id=f"v-{time.monotonic_ns()}")
        self._versions.setdefault(key.id, []).append(v)
        return v

    def read(self, key: ArticleId) -> ContentRef:
        return self._repos[key.id]

    def read_body(self, ref: ContentRef) -> str:
        return self._blobs[ref.ref]

    def write_article(self, key: ArticleId, write) -> Version:
        import json
        from peerpedia_core.types.writes import ArticleWrite
        # Serialize article metadata as YAML-like frontmatter
        frontmatter = json.dumps({
            "title": write.article.title,
            "authors": list(write.article.authors),
            "abstract": write.article.abstract,
            "status": write.article.status,
        })
        content = f"---\n{frontmatter}\n---\n{write.content}"
        return self.update(key, content)

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
        versions = self._versions.get(key.id, [])
        entries = []
        for v in reversed(versions):
            entries.append(HistoryEntry(
                version=v,
                message="",
                user=User(id=UserId(id="system"), name="system"),
                timestamp=datetime.now(timezone.utc),
            ))
        return entries

    def diff(self, key: ArticleId, a: Version, b: Version) -> ArticleDiff:
        return ArticleDiff(version_a=a, version_b=b, content_diff="")


class MemReviewStorage:
    def __init__(self):
        self._rows: dict[str, Review] = {}

    @staticmethod
    def _key(article_id: ArticleId, reviewer_id: UserId) -> str:
        return f"{article_id.id}/{reviewer_id.id}"

    def create(self, article_id: ArticleId, reviewer_id: UserId) -> Review:
        r = Review(
            id=ReviewId(id=f"rev-{article_id.id}-{reviewer_id.id}"),
            article_id=article_id, reviewer_id=reviewer_id,
        )
        self._rows[self._key(article_id, reviewer_id)] = r
        return r

    def read(self, article_id: ArticleId, reviewer_id: UserId) -> Review:
        try:
            return self._rows[self._key(article_id, reviewer_id)]
        except KeyError:
            raise NotFoundError(
                f"Review by {reviewer_id.id!r} on {article_id.id!r} not found",
                resource_type="review",
                resource_id=f"{article_id.id}/{reviewer_id.id}",
            ) from None

    def update(self, article_id: ArticleId, reviewer_id: UserId, review: Review) -> Version:
        self._rows[self._key(article_id, reviewer_id)] = review
        return Version(id=f"v-{time.monotonic_ns()}")

    def delete(self, article_id: ArticleId, reviewer_id: UserId) -> Version:
        self._rows.pop(self._key(article_id, reviewer_id), None)
        return Version(id=f"v-{time.monotonic_ns()}")

    def list(self, article_id: ArticleId) -> list[Review]:
        prefix = f"{article_id.id}/"
        return [v for k, v in self._rows.items() if k.startswith(prefix)]


class MemReviewContentStorage:
    """In-memory ReviewContentStorage — simulates git repo review files."""

    def __init__(self):
        self._scores: dict[str, str] = {}       # "aid/uid" -> JSON
        self._threads: dict[str, list[str]] = {} # "aid/uid" -> [entry, ...]

    def _key(self, article_id: ArticleId, reviewer_id: UserId) -> str:
        return f"{article_id.id}/{reviewer_id.id}"

    def list_reviewers(self, article_id: ArticleId) -> list[UserId]:
        prefix = f"{article_id.id}/"
        return [UserId(id=k.split("/")[1]) for k in self._scores if k.startswith(prefix)]

    def create(self, article_id: ArticleId, reviewer_id: UserId) -> Version:
        k = self._key(article_id, reviewer_id)
        self._scores.setdefault(k, "{}")
        self._threads.setdefault(k, [])
        return Version(id=f"v-{time.monotonic_ns()}")

    def write_review(self, article_id: ArticleId, write) -> Version:
        scores_json = json.dumps(dict(write.scores.dimensions))
        self.update(article_id, write.reviewer_id, scores_json)
        if write.content:
            self.append_thread_entry(article_id, write.reviewer_id, write.content, "[review]")
        return Version(id=f"v-{time.monotonic_ns()}")

    def read(self, article_id: ArticleId, reviewer_id: UserId) -> str | None:
        return self._scores.get(self._key(article_id, reviewer_id))

    def update(self, article_id: ArticleId, reviewer_id: UserId,
               scores: str) -> Version:
        self._scores[self._key(article_id, reviewer_id)] = scores
        return Version(id=f"v-{time.monotonic_ns()}")

    def delete(self, article_id: ArticleId, reviewer_id: UserId) -> Version:
        k = self._key(article_id, reviewer_id)
        self._scores.pop(k, None)
        self._threads.pop(k, None)
        return Version(id=f"v-{time.monotonic_ns()}")

    def append_thread_entry(self, article_id: ArticleId, reviewer_id: UserId,
                            content: str, marker: str) -> Version:
        k = self._key(article_id, reviewer_id)
        self._threads.setdefault(k, []).append(content)
        return Version(id=f"v-{time.monotonic_ns()}")

    def read_thread(self, article_id: ArticleId, reviewer_id: UserId) -> list[str]:
        return self._threads.get(self._key(article_id, reviewer_id), [])


class MemArticleStorage(ArticleStorage):
    """In-memory ArticleStorage — Mem* sub-storages + overridden extract."""

    def __init__(self):
        super().__init__(
            meta=MemMetaStorage(),
            content=MemContentStorage(),
            review_meta=MemReviewStorage(),
            review_content=MemReviewContentStorage(),
        )

    def extract(self, key: ArticleId) -> Article:
        import json as _json
        article = self.meta.read(key)
        try:
            raw = self.content.read_body(self.content.read(key))
        except Exception:
            return article

        if raw.startswith("---"):
            try:
                _, fm_str, _ = raw.split("---", 2)
                fm = _json.loads(fm_str.strip())
                # Merge frontmatter fields into article (meta cache is authoritative)
                updates: dict[str, object] = {}
                if not article.title and fm.get("title"):
                    updates["title"] = fm["title"]
                if not article.authors and fm.get("authors"):
                    updates["authors"] = tuple(fm["authors"])
                if not article.abstract and fm.get("abstract"):
                    updates["abstract"] = fm["abstract"]
                if updates:
                    article = replace(article, **updates)
            except (ValueError, KeyError):
                pass
        return article

    def extract_reviews(self, key: ArticleId) -> list[Review]:
        rcontent = self.review_content
        reviews: list[Review] = []
        for reviewer_id in rcontent.list_reviewers(key):
            scores_json = rcontent.read(key, reviewer_id)
            scores = Scores(dimensions=json.loads(scores_json)) if scores_json else Scores()
            reviews.append(Review(
                id=ReviewId(id=f"rev-{key.id}-{reviewer_id.id}"),
                article_id=key,
                reviewer_id=reviewer_id,
                scores=scores,
            ))
        return reviews


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


# ═══════════════════════════════════════════════════════════════════════════
# Lifecycle
# ═══════════════════════════════════════════════════════════════════════════

class MemLifecycle:
    """Lifecycle that bridges ``execute()`` to ``ArticleStorage`` methods."""

    def __init__(self, storage: ArticleStorage):
        self.storage = storage

    @property
    def actions(self) -> frozenset[str]:
        return frozenset({"create", "revise", "publish", "delete", "review"})

    def resolve(self, action: str) -> Evaluation:
        s = self.storage
        if action == "create":
            return lambda extra, ctx: s.create_article()
        if action == "revise":
            return lambda extra, ctx: (
                s.update_article(ctx, str(extra["content"]),
                                 _require_article(extra)), ctx)[1]
        if action == "publish":
            return lambda extra, ctx: (
                s.meta.update(ctx, _require_article(extra)),
                s.reconcile_article(ctx), ctx)[2]
        if action == "delete":
            return lambda extra, ctx: (s.delete_article(ctx), ctx)[1]
        if action == "review":
            return lambda extra, ctx: (
                _validate_review_context(extra, ctx),
                s.create_review(
                    ctx,
                    _require_review(extra).reviewer_id,
                    _parse_scores(extra),
                ), ctx)[1]
        raise BadRequestError(f"Unknown action: {action}")


def _validate_review_context(extra: Extra, context: ArticleId | None) -> None:
    review = _require_review(extra)
    if review.article_id != context:
        raise BadRequestError(
            f"Review article_id {review.article_id.id!r} does not match "
            f"context {context.id if context else 'None'!r}",
            field="review.article_id",
            bad_value=review.article_id.id,
        )


def _parse_scores(extra: Extra) -> Scores:
    scores_str = str(extra.get("scores", "{}"))
    return Scores(dimensions=json.loads(scores_str))


def _require_article(extra: Extra) -> Article:
    a = extra.get("article")
    if not isinstance(a, Article):
        raise BadRequestError(
            f"Expected 'article' to be Article, got {type(a).__name__}",
            field="article", bad_value=str(type(a)),
        )
    return a


def _require_review(extra: Extra) -> Review:
    r = extra.get("review")
    if not isinstance(r, Review):
        raise BadRequestError(
            f"Expected 'review' to be Review, got {type(r).__name__}",
            field="review", bad_value=str(type(r)),
        )
    return r


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
