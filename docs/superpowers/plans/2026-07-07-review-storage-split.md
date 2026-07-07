# Review Storage Split — Meta/Content Parallel + User Independence

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `ReviewStorage` into `ReviewMetaStorage` (DB index) + `ReviewContentStorage` (git SOT), parallel to `ArticleMetaStorage` + `ArticleContentStorage`. Remove `get_user()`/`read_user()` from `ArticleStorage` — `UserStorage` becomes a standalone backend.

**Architecture:** Reviews follow the same meta/content pattern as articles. `ReviewContentStorage` operates on `reviews/{dir_id}/scores.json` + `threads/*.md` in the article git repo. `ReviewMetaStorage` is a fast-query index. `reconcile_reviews()` rebuilds the index from git content. `UserStorage` is injected independently alongside `ArticleStorage` and `Lifecycle`.

**Tech Stack:** Python >=3.11, zero deps, typing.Protocol, pytest

## Global Constraints

- All protocols use `typing.Protocol` — structural subtyping, no ABC
- Types are frozen `@dataclass` in `peerpedia_core/types/entities.py`
- No IO in protocol or types modules
- Tests use in-memory reference implementations in `tests/conftest.py`

---

## Files Map

| File | Action | Responsibility |
|------|--------|----------------|
| `peerpedia_core/protocols/review_storage.py` | Delete | Replaced by `review_meta_storage.py` |
| `peerpedia_core/protocols/review_meta_storage.py` | Create | `ReviewMetaStorage` — DB index for reviews |
| `peerpedia_core/protocols/review_content_storage.py` | Create | `ReviewContentStorage` — git SOT for reviews |
| `peerpedia_core/protocols/storage.py` | Modify | Remove `get_user`/`read_user`/`get_review`/`read_review`; add `get_review_meta`/`get_review_content` + convenience + `reconcile_reviews` |
| `peerpedia_core/protocols/__init__.py` | Modify | Update exports |
| `peerpedia_core/protocols/lifecycle.py` | Modify | `action_review` uses review content storage |
| `peerpedia_core/peerpedia.py` | Modify | Accept `UserStorage` directly |
| `tests/conftest.py` | Modify | `MemReviewContentStorage`, update `MemArticleStorage` |
| `tests/test_reference.py` | Modify | Update tests for new structure |

---

### Task 1: Create `ReviewContentStorage` protocol

**Files:**
- Create: `peerpedia_core/protocols/review_content_storage.py`
- Modify: `peerpedia_core/protocols/__init__.py`

**Interfaces:**
- Produces: `ReviewContentStorage` protocol class

- [ ] **Step 1: Create the file**

```python
# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Review content storage protocol — git SOT for peer evaluations.

Reviews live inside the article git repository under
``reviews/{dir_id}/``::

    reviews/{dir_id}/scores.json
    reviews/{dir_id}/threads/001.md
    reviews/{dir_id}/threads/002.md

This protocol provides file-level read/write access.  Semantic
operations (submit, reply) live in lifecycle actions.
"""

from __future__ import annotations

from typing import Protocol

from peerpedia_core.types.entities import ArticleId, UserId, Version


class ReviewContentStorage(Protocol):
    """File-level operations on review content in the article git repo.

    Each method targets the reviewer's directory under
    ``reviews/{dir_id}/`` within the article repository.
    """

    def write_scores(
        self, article_id: ArticleId, reviewer_id: UserId, scores: str
    ) -> Version:
        """Write ``scores.json`` for *reviewer_id*.  *scores* is JSON text."""
        ...

    def read_scores(
        self, article_id: ArticleId, reviewer_id: UserId
    ) -> str | None:
        """Read ``scores.json`` — return JSON text or None."""
        ...

    def write_thread_entry(
        self, article_id: ArticleId, reviewer_id: UserId,
        content: str, marker: str,
    ) -> Version:
        """Append a numbered ``threads/NNN.md`` with *marker* as commit prefix.

        *marker* is ``"[review]"`` for the initial review or
        ``"[reply]"`` for follow-up messages.
        """
        ...

    def read_thread(
        self, article_id: ArticleId, reviewer_id: UserId,
    ) -> list[str]:
        """Return all thread entry contents, ordered by filename."""
        ...

    def delete_review_dir(
        self, article_id: ArticleId, reviewer_id: UserId,
    ) -> Version:
        """Remove the entire ``reviews/{dir_id}/`` directory."""
        ...
```

- [ ] **Step 2: Register in `__init__.py`**

In `peerpedia_core/protocols/__init__.py`, add the import and export:

```python
# Add import (after review_storage import, before it gets removed in Task 2):
from peerpedia_core.protocols.review_content_storage import ReviewContentStorage

# Add to __all__:
"ReviewContentStorage",
```

- [ ] **Step 3: Commit**

```bash
git add peerpedia_core/protocols/review_content_storage.py peerpedia_core/protocols/__init__.py
git commit -m "feat: add ReviewContentStorage protocol — git SOT for review files"
```

---

### Task 2: Rename `ReviewStorage` → `ReviewMetaStorage`

**Files:**
- Create: `peerpedia_core/protocols/review_meta_storage.py`
- Delete: `peerpedia_core/protocols/review_storage.py`
- Modify: `peerpedia_core/protocols/__init__.py`

**Interfaces:**
- Produces: `ReviewMetaStorage` protocol class (same interface as old `ReviewStorage`)

- [ ] **Step 1: Create the renamed file**

```python
# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Review meta storage protocol — DB index for peer evaluations.

The source of truth for review content lives in the article git repo
(see ``ReviewContentStorage``).  This protocol provides a fast-query
index rebuilt via ``reconcile_reviews()``.
"""

from __future__ import annotations

from typing import Protocol

from peerpedia_core.types.entities import ArticleId, Review, UserId, Version


class ReviewMetaStorage(Protocol):
    """Indexed review cache — fast reads, queryable.

    Typically DB-backed.  Git is the source of truth; this cache
    is rebuilt via ``reconcile_reviews()``.
    """

    def create(self, article_id: ArticleId, reviewer_id: UserId) -> Review:
        """Allocate a new review index row for *article_id* and *reviewer_id*."""
        ...

    def read(self, article_id: ArticleId, reviewer_id: UserId) -> Review:
        """Return the cached review by *reviewer_id* on *article_id*."""
        ...

    def update(
        self, article_id: ArticleId, reviewer_id: UserId, review: Review
    ) -> Version:
        """Replace the cached review — returns the article version."""
        ...

    def delete(self, article_id: ArticleId, reviewer_id: UserId) -> Version:
        """Remove the review index row — returns the article version."""
        ...

    def list(self, article_id: ArticleId) -> list[Review]:
        """Return all cached reviews for *article_id*."""
        ...
```

- [ ] **Step 2: Update `__init__.py`**

```python
# Replace the old import:
# OLD: from peerpedia_core.protocols.review_storage import ReviewStorage
# NEW:
from peerpedia_core.protocols.review_meta_storage import ReviewMetaStorage

# Replace in __all__:
# OLD: "ReviewStorage",
# NEW: "ReviewMetaStorage",
```

- [ ] **Step 3: Delete old file**

```bash
rm peerpedia_core/protocols/review_storage.py
```

- [ ] **Step 4: Commit**

```bash
git add peerpedia_core/protocols/review_meta_storage.py peerpedia_core/protocols/__init__.py
git rm peerpedia_core/protocols/review_storage.py
git commit -m "refactor: rename ReviewStorage → ReviewMetaStorage (parallel to ArticleMetaStorage)"
```

---

### Task 3: Update `ArticleStorage` — split user, add review meta/content

**Files:**
- Modify: `peerpedia_core/protocols/storage.py`

**Interfaces:**
- Removes: `get_user()`, `read_user()`, `get_review()`, `read_review()`
- Adds: `get_review_meta()`, `get_review_content()`, `read_review_meta()`, `read_review_content()`
- Adds: `reconcile_reviews()` module-level function

- [ ] **Step 1: Update imports in storage.py**

Replace the import block at the top of `peerpedia_core/protocols/storage.py`:

```python
from peerpedia_core.types.entities import (
    Article,
    ArticleDiff,
    ArticleId,
    ContentRef,
    Format,
    HistoryEntry,
    UserId,
    Version,
)
from peerpedia_core.protocols.review_meta_storage import ReviewMetaStorage
from peerpedia_core.protocols.review_content_storage import ReviewContentStorage
from peerpedia_core.types.queries import ArticleQuery
```

Remove these old imports:
```python
# REMOVE:
from peerpedia_core.protocols.review_storage import ReviewStorage
from peerpedia_core.protocols.user_storage import UserStorage
# REMOVE from entities imports: Review, User
```

- [ ] **Step 2: Replace `ArticleStorage` class**

Replace the entire `ArticleStorage` class definition (lines 117-174) with:

```python
class ArticleStorage(Protocol):
    """Composed storage — meta cache + content SOT for articles and reviews.

    Article and review each follow the same meta/content split::

        ArticleMetaStorage     /  ArticleContentStorage
        ReviewMetaStorage      /  ReviewContentStorage

    ``reconcile()`` rebuilds article meta from content.
    ``reconcile_reviews()`` rebuilds review meta from content.
    """

    # ── Article sub-storage ────────────────────────────────────────────

    def get_meta(self, key: ArticleId | None = None) -> ArticleMetaStorage:
        """Return the article-meta sub-storage for *key*.

        When *key* is ``None`` (not yet created), returns a global
        meta store for id-allocation operations like ``create()``.
        """
        ...

    def get_content(self, key: ArticleId | None = None) -> ArticleContentStorage:
        """Return the article-content sub-storage for *key*."""
        ...

    def read_meta(self, key: ArticleId) -> Article:
        """Convenience — delegates to ``get_meta(key).read(key)``."""
        return self.get_meta(key).read(key)

    def read_content(self, key: ArticleId) -> ContentRef:
        """Convenience — delegates to ``get_content(key).read(key)``."""
        return self.get_content(key).read(key)

    # ── Review sub-storage ─────────────────────────────────────────────

    def get_review_meta(self, key: ArticleId) -> ReviewMetaStorage:
        """Return the review-meta sub-storage for *key*."""
        ...

    def get_review_content(self, key: ArticleId) -> ReviewContentStorage:
        """Return the review-content sub-storage for *key*."""
        ...

    def read_review_meta(
        self, key: ArticleId, reviewer_id: UserId
    ) -> Review:
        """Convenience — delegates to ``get_review_meta(key).read(key, reviewer_id)``."""
        return self.get_review_meta(key).read(key, reviewer_id)

    def read_review_content(
        self, key: ArticleId, reviewer_id: UserId
    ) -> list[str]:
        """Convenience — delegates to ``get_review_content(key).read_thread(key, reviewer_id)``."""
        return self.get_review_content(key).read_thread(key, reviewer_id)

    # ── Source-of-truth extraction ─────────────────────────────────────

    def extract(self, key: ArticleId) -> Article:
        """Extract metadata from content source-of-truth.

        Reads content history and reconstructs metadata fields:
        - ``authors`` ← git commit authors
        - ``status`` ← git commit message transitions
        - ``created_at`` / ``updated_at`` ← git commit timestamps
        - ``title`` / ``abstract`` ← YAML frontmatter

        The caller composes this with ``meta.update()`` to rebuild
        the cache — see ``reconcile()``, the derived helper.
        """
        ...
```

- [ ] **Step 3: Add `reconcile_reviews()` function**

After the `reconcile()` function (after line 183), add:

```python
def reconcile_reviews(storage: ArticleStorage, key: ArticleId) -> None:
    """Rebuild review meta cache from review content SOT.

    Extracts review metadata from the git content store and writes
    it to ``ReviewMetaStorage``.  Run after review content changes.
    """
    rmeta = storage.get_review_meta(key)
    rcontent = storage.get_review_content(key)
    # For each reviewer directory in the git repo, extract scores and
    # build/update the meta index.  The implementation is backend-specific
    # (the protocol does not prescribe the extraction algorithm), but the
    # pattern is: git content → meta cache.
    ...
```

- [ ] **Step 4: Commit**

```bash
git add peerpedia_core/protocols/storage.py
git commit -m "refactor: split UserStorage from ArticleStorage; add ReviewMeta/ReviewContent sub-storage"
```

---

### Task 4: Update `lifecycle.py` — action_review uses review content storage

**Files:**
- Modify: `peerpedia_core/protocols/lifecycle.py`

**Interfaces:**
- Consumes: `ReviewContentStorage`, `ReviewMetaStorage` from `ArticleStorage`

- [ ] **Step 1: Update `action_review` to write through content storage**

Replace `action_review` (lines 135-153) with:

```python
def action_review(
    extra: Extra, context: ArticleId, storage: ArticleStorage,
) -> ArticleId:
    """Submit a peer review on *context*.

    *extra* must contain ``"review"`` (Review) with ``article_id``
    matching *context*, and ``"scores"`` (str, JSON) with the review
    scores.
    """
    review: Review = _require(extra, "review", Review)  # type: ignore[assignment]
    scores_json: str = _require(extra, "scores", str)    # type: ignore[assignment]
    if review.article_id != context:
        raise BadRequestError(
            f"Review article_id {review.article_id.id!r} does not match context {context.id!r}",
            field="review.article_id",
            bad_value=review.article_id.id,
        )

    # Write to git SOT (content storage)
    rcontent = storage.get_review_content(context)
    rcontent.write_scores(context, review.reviewer_id, scores_json)
    rcontent.write_thread_entry(context, review.reviewer_id,
                                review.content_ref.deref(storage.get_content(context))
                                if review.content_ref else "",
                                "[review]")

    # Rebuild meta index from content
    reconcile_reviews(storage, context)
    return context
```

Add the `reconcile_reviews` import at the top (after the `reconcile` import on line 36):

```python
from peerpedia_core.protocols.storage import reconcile, reconcile_reviews
```

- [ ] **Step 2: Commit**

```bash
git add peerpedia_core/protocols/lifecycle.py
git commit -m "feat: action_review writes through ReviewContentStorage + reconcile"
```

---

### Task 5: Update `Peerpedia` facade — independent UserStorage

**Files:**
- Modify: `peerpedia_core/peerpedia.py`

**Interfaces:**
- Consumes: `UserStorage` as standalone parameter
- Removes: dependency on `ArticleStorage.get_user()`

- [ ] **Step 1: Update `Peerpedia.__init__`**

Replace `peerpedia_core/peerpedia.py` with:

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add peerpedia_core/peerpedia.py
git commit -m "refactor: Peerpedia accepts UserStorage independently"
```

---

### Task 6: Update reference implementation — MemReviewContentStorage

**Files:**
- Modify: `tests/conftest.py`

**Interfaces:**
- Produces: `MemReviewContentStorage` class
- Modifies: `MemArticleStorage` — split users, add review content

- [ ] **Step 1: Add `MemReviewContentStorage`**

Insert after `MemReviewStorage` in `tests/conftest.py` (after line 195):

```python
class MemReviewContentStorage:
    """In-memory ReviewContentStorage — simulates git repo review files."""

    def __init__(self):
        self._scores: dict[str, str] = {}       # "aid/uid" → JSON
        self._threads: dict[str, list[str]] = {} # "aid/uid" → [entry, ...]

    def _key(self, article_id: ArticleId, reviewer_id: UserId) -> str:
        return f"{article_id.id}/{reviewer_id.id}"

    def write_scores(self, article_id: ArticleId, reviewer_id: UserId,
                     scores: str) -> Version:
        self._scores[self._key(article_id, reviewer_id)] = scores
        return Version(id=f"v-{time.monotonic_ns()}")

    def read_scores(self, article_id: ArticleId, reviewer_id: UserId) -> str | None:
        return self._scores.get(self._key(article_id, reviewer_id))

    def write_thread_entry(self, article_id: ArticleId, reviewer_id: UserId,
                           content: str, marker: str) -> Version:
        k = self._key(article_id, reviewer_id)
        self._threads.setdefault(k, []).append(content)
        return Version(id=f"v-{time.monotonic_ns()}")

    def read_thread(self, article_id: ArticleId, reviewer_id: UserId) -> list[str]:
        return self._threads.get(self._key(article_id, reviewer_id), [])

    def delete_review_dir(self, article_id: ArticleId, reviewer_id: UserId) -> Version:
        k = self._key(article_id, reviewer_id)
        self._scores.pop(k, None)
        self._threads.pop(k, None)
        return Version(id=f"v-{time.monotonic_ns()}")
```

- [ ] **Step 2: Update `MemArticleStorage`**

Replace `MemArticleStorage` class (lines 105-139) with:

```python
class MemArticleStorage:
    def __init__(self):
        self.meta = MemMetaStorage()
        self.content = MemContentStorage()
        self.review_meta: dict[str, MemReviewStorage] = {}
        self.review_content: dict[str, MemReviewContentStorage] = {}

    # ── Article sub-storage ──────────────────────────────────────────

    def get_meta(self, key: ArticleId | None = None) -> ArticleMetaStorage:
        return self.meta

    def get_content(self, key: ArticleId | None = None) -> ArticleContentStorage:
        return self.content

    def read_meta(self, key: ArticleId) -> Article:
        return self.meta.read(key)

    def read_content(self, key: ArticleId) -> ContentRef:
        return self.content.read(key)

    # ── Review sub-storage ───────────────────────────────────────────

    def get_review_meta(self, key: ArticleId) -> ReviewMetaStorage:
        if key.id not in self.review_meta:
            self.review_meta[key.id] = MemReviewStorage()
        return self.review_meta[key.id]

    def get_review_content(self, key: ArticleId) -> ReviewContentStorage:
        if key.id not in self.review_content:
            self.review_content[key.id] = MemReviewContentStorage()
        return self.review_content[key.id]

    def read_review_meta(self, key: ArticleId, reviewer_id: UserId) -> Review:
        return self.review_meta[key.id].read(key, reviewer_id)

    def read_review_content(self, key: ArticleId, reviewer_id: UserId) -> list[str]:
        return self.review_content[key.id].read_thread(key, reviewer_id)

    def extract(self, key: ArticleId) -> Article:
        return self.read_meta(key)
```

Update imports at the top of conftest.py — replace:

```python
from peerpedia_core.protocols.storage import (
    ArticleContentStorage, ArticleMetaStorage, ArticleStorage,
)
from peerpedia_core.protocols.review_storage import ReviewStorage
from peerpedia_core.protocols.user_storage import UserStorage
```

With:

```python
from peerpedia_core.protocols.review_content_storage import ReviewContentStorage
from peerpedia_core.protocols.review_meta_storage import ReviewMetaStorage
from peerpedia_core.protocols.storage import (
    ArticleContentStorage, ArticleMetaStorage, ArticleStorage,
)
from peerpedia_core.protocols.user_storage import UserStorage
```

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: add MemReviewContentStorage; update MemArticleStorage for review meta/content split"
```

---

### Task 7: Update tests for new protocol structure

**Files:**
- Modify: `tests/test_reference.py`

- [ ] **Step 1: Update `test_full_lifecycle` — user path**

Replace the user + review section of `test_full_lifecycle` (lines 56-77 in current `test_reference.py`):

```python
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
```

- [ ] **Step 2: Remove `storage.users` reference in `test_full_lifecycle`**

The test currently accesses `storage.users` (line 57). Change to use standalone `MemUserStorage()`.

- [ ] **Step 3: Update `test_userid_deref` — use standalone MemUserStorage**

(Basically unchanged — already uses standalone `MemUserStorage`, just verify it still works.)

- [ ] **Step 4: Update `test_review_sync` — uses `ReviewSync` protocol**

No changes needed — `ReviewSync` is unchanged.

- [ ] **Step 5: Add `test_review_reconcile` — new test**

Add after existing tests:

```python
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
```

- [ ] **Step 6: Run tests**

```bash
python3 -m pytest tests/test_reference.py -v
```

Expected: 11 passed (8 original + 1 new).

- [ ] **Step 7: Commit**

```bash
git add tests/test_reference.py
git commit -m "test: update tests for review content storage + standalone UserStorage"
```

---

### Task 8: Clean up stale `Review` import in `storage.py`

**Files:**
- Modify: `peerpedia_core/protocols/storage.py`

- [ ] **Step 1: Remove unused imports**

In `peerpedia_core/protocols/storage.py`, the `Review` and `User` imports are no longer needed after Task 3. Verify they're gone from the entities import:

```python
from peerpedia_core.types.entities import (
    Article,
    ArticleDiff,
    ArticleId,
    ContentRef,
    Format,
    HistoryEntry,
    UserId,      # still needed for read_review_meta
    Version,
)
```

(If `Review` or `User` are still in the import list, remove them.)

- [ ] **Step 2: Run full test suite**

```bash
python3 -m pytest tests/ -v
```

- [ ] **Step 3: Commit**

```bash
git add peerpedia_core/protocols/storage.py
git commit -m "chore: remove stale Review/User imports from storage.py"
```

---

## Self-Review

**1. Spec coverage:**
- ✅ `get_user()` removed from `ArticleStorage` — Task 3, Task 5
- ✅ `ReviewStorage` → `ReviewMetaStorage` rename — Task 2
- ✅ `ReviewContentStorage` created — Task 1
- ✅ `get_review_meta`/`get_review_content` on `ArticleStorage` — Task 3
- ✅ `reconcile_reviews()` — Task 3
- ✅ `Peerpedia` accepts `UserStorage` independently — Task 5
- ✅ Reference implementation updated — Task 6
- ✅ Tests updated — Task 7

**2. Placeholder scan:** No TBDs, no "implement later", no vague steps. All code shown inline.

**3. Type consistency:**
- `ReviewMetaStorage` → same interface as old `ReviewStorage` (create/read/update/delete/list) ✅
- `ReviewContentStorage` → write_scores/read_scores/write_thread_entry/read_thread/delete_review_dir ✅
- `ArticleStorage.get_review_meta() -> ReviewMetaStorage` ✅
- `ArticleStorage.get_review_content() -> ReviewContentStorage` ✅
- `Peerpedia.__init__(storage, lifecycle, user_storage, compiler=None)` ✅
