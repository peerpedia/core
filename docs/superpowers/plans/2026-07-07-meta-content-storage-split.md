# Meta/Content Storage Split — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `ArticleStorage` into `ArticleMetaStorage`, `ArticleContentStorage`, and a composed `ArticleStorage` with `reconcile`.

**Architecture:** Three protocols in one file — two domain-specific sub-protocols (meta CRUD, content versioning) plus a composed top-level protocol that aggregates them and adds `reconcile`.

**Tech Stack:** Python 3.11+, `typing.Protocol`, zero runtime dependencies.

## Global Constraints

- Zero runtime dependencies (`dependencies = []` in pyproject.toml)
- All protocols use `typing.Protocol`
- All entity types remain frozen dataclasses
- Imports at top of file (no lazy imports)
- No implementation code — protocols only

---

### Task 1: Rewrite `protocols/storage.py` with three protocols

**Files:**
- Modify: `peerpedia_core/protocols/storage.py`

**Interfaces:**
- Consumes: `Article`, `ArticleDiff`, `ArticleId`, `ContentRef`, `HistoryEntry`, `Version` from `peerpedia_core.types.entities`
- Consumes: `ArticleQuery` from `peerpedia_core.types.queries`
- Produces: `ArticleMetaStorage`, `ArticleContentStorage`, `ArticleStorage` (three Protocol classes)

- [ ] **Step 1: Write the full file**

```python
# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Article storage protocols — meta, content, and composed.

Meta and content are universally separate storage concerns::

    ArticleMetaStorage    — indexed cache (DB), fast reads, queryable
    ArticleContentStorage — versioned source-of-truth (git), lazy body access
    ArticleStorage        — composed, adds ``reconcile``

Reconcile rebuilds the meta cache from content history.
Writes go through lifecycle actions, not storage methods directly.
"""

from __future__ import annotations

from typing import Protocol

from peerpedia_core.types.entities import (
    Article,
    ArticleDiff,
    ArticleId,
    ContentRef,
    HistoryEntry,
    Version,
)
from peerpedia_core.types.queries import ArticleQuery


class ArticleMetaStorage(Protocol):
    """Indexed metadata cache — fast reads, queryable.

    Typically DB-backed.  Git is the source of truth; this cache
    is rebuilt via ``ArticleStorage.reconcile()``.
    """

    def create(self) -> ArticleId:
        """Allocate a new article id with empty metadata (git init)."""
        ...

    def read(self, key: ArticleId) -> Article:
        """Return cached metadata for *key*."""
        ...

    def update(self, key: ArticleId, meta: Article) -> Version:
        """Replace cached metadata for *key*.  Returns content version."""
        ...

    def delete(self, key: ArticleId) -> Version:
        """Remove metadata row for *key*."""
        ...

    def query(self, q: ArticleQuery | None = None) -> list[Article]:
        """Search metadata with optional filters."""
        ...


class ArticleContentStorage(Protocol):
    """Versioned content store — git-backed source of truth.

    Body text, commit history, and authorship live here.
    Content is lazy-loaded via ``deref_body``.
    """

    def create(self) -> ArticleId:
        """Initialize an empty content repo (git init)."""
        ...

    def read(self, key: ArticleId) -> ContentRef:
        """Return the content locator for *key*."""
        ...

    def deref_body(self, ref: ContentRef) -> str:
        """Resolve *ref* to raw body text (lazy, potentially large)."""
        ...

    def update(self, key: ArticleId, content: str) -> Version:
        """Append a new version of *content* to *key* (git commit)."""
        ...

    def delete(self, key: ArticleId) -> Version:
        """Mark content as deleted, retaining history."""
        ...

    def history(
        self, key: ArticleId, since: Version | None = None
    ) -> list[HistoryEntry]:
        """Version log for *key*, newest first."""
        ...

    def diff(
        self, key: ArticleId, version_a: Version, version_b: Version
    ) -> ArticleDiff:
        """Unified diff between two versions."""
        ...


class ArticleStorage(Protocol):
    """Composed storage — meta cache + content source-of-truth.

    Access sub-protocols via ``get_meta()`` / ``get_content()``
    for domain-specific operations, or use ``read_meta`` /
    ``read_content`` for common access patterns.
    ``reconcile`` rebuilds the meta cache from content history.
    """

    def get_meta(self) -> ArticleMetaStorage:
        """Return the metadata sub-storage."""
        ...

    def get_content(self) -> ArticleContentStorage:
        """Return the content sub-storage."""
        ...

    def read_meta(self, key: ArticleId) -> Article:
        """Convenience — delegates to ``get_meta().read(key)``."""
        return self.get_meta().read(key)

    def read_content(self, key: ArticleId) -> ContentRef:
        """Convenience — delegates to ``get_content().read(key)``."""
        return self.get_content().read(key)

    def reconcile(self, key: ArticleId) -> None:
        """Rebuild meta cache from content source-of-truth.

        Reads git history from content storage and updates the
        corresponding metadata fields in meta storage:
        - ``authors`` ← git commit authors
        - ``status`` ← git commit message transitions
        - ``created_at`` / ``updated_at`` ← git commit timestamps
        - ``title`` / ``abstract`` ← YAML frontmatter in content
        """
        ...
```

- [ ] **Step 2: Verify imports**

Run: `python3 -c "from peerpedia_core.protocols.storage import ArticleMetaStorage, ArticleContentStorage, ArticleStorage; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add peerpedia_core/protocols/storage.py
git commit -m "refactor: split ArticleStorage into ArticleMetaStorage, ArticleContentStorage, and composed ArticleStorage"
```

---

### Task 2: Update `protocols/__init__.py` exports

**Files:**
- Modify: `peerpedia_core/protocols/__init__.py`

**Interfaces:**
- Consumes: `ArticleMetaStorage`, `ArticleContentStorage` from `peerpedia_core.protocols.storage`
- Produces: Updated `__all__` with three storage protocols

- [ ] **Step 1: Update the imports and __all__**

```python
# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Engine protocols — interfaces the core understands.

Each protocol is a ``typing.Protocol`` — no implementation, just
structural contracts.  Plugins in other packages implement these.
"""

from peerpedia_core.protocols.authorizer import Authorizer
from peerpedia_core.protocols.lifecycle import Lifecycle
from peerpedia_core.protocols.scoring import ScoringEngine
from peerpedia_core.protocols.storage import (
    ArticleContentStorage,
    ArticleMetaStorage,
    ArticleStorage,
)

__all__ = [
    "ArticleContentStorage",
    "ArticleMetaStorage",
    "ArticleStorage",
    "Authorizer",
    "Lifecycle",
    "ScoringEngine",
]
```

- [ ] **Step 2: Verify**

Run: `python3 -c "from peerpedia_core.protocols import ArticleMetaStorage, ArticleContentStorage, ArticleStorage; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add peerpedia_core/protocols/__init__.py
git commit -m "feat: export ArticleMetaStorage and ArticleContentStorage from protocols"
```

---

### Task 3: Verify full import chain and deref compatibility

**Files:**
- No file changes — verification only

- [ ] **Step 1: Full-chain integration check**

```bash
python3 -c "
from peerpedia_core.protocols import (
    ArticleMetaStorage, ArticleContentStorage, ArticleStorage,
    Lifecycle, Authorizer, ScoringEngine,
)
from peerpedia_core.types import (
    Article, ArticleId, ArticleDiff, ArticleQuery,
    BibData, ContentRef, HistoryEntry, Review, ReviewData,
    User, Version,
)

# Verify deref chain still works
assert hasattr(ArticleId, 'deref_meta')
assert hasattr(ArticleId, 'deref_content')
assert hasattr(Article, 'deref')
assert hasattr(ContentRef, 'deref')

# Verify protocol methods exist
meta_methods = ['create', 'read', 'update', 'delete', 'query']
content_methods = ['create', 'read', 'deref_body', 'update', 'delete', 'history', 'diff']
storage_methods = ['get_meta', 'get_content', 'read_meta', 'read_content', 'reconcile']

for m in meta_methods:
    assert m in ArticleMetaStorage.__dict__, f'missing ArticleMetaStorage.{m}'
for m in content_methods:
    assert m in ArticleContentStorage.__dict__, f'missing ArticleContentStorage.{m}'
for m in storage_methods:
    assert m in ArticleStorage.__dict__, f'missing ArticleStorage.{m}'

# read_meta and read_content should have concrete implementations (not ...)
assert ArticleStorage.read_meta(ArticleStorage) is not ...
assert ArticleStorage.read_content(ArticleStorage) is not ...

# ContentRef.deref calls storage.deref_body — signature check
import inspect
sig = inspect.signature(ContentRef.deref)
assert 'storage' in sig.parameters

# ArticleId.deref_meta calls storage.deref_meta
sig = inspect.signature(ArticleId.deref_meta)
assert 'storage' in sig.parameters

print('All checks passed!')
"
```
Expected: `All checks passed!`

- [ ] **Step 2: Commit (if no code changes, record verification)**

```bash
# No file changes — this is a pure verification step
git log --oneline -1
```

---

### Task 4: Run full test suite

**Files:**
- No file changes — test execution only

- [ ] **Step 1: Check for existing tests**

```bash
find tests -name '*.py' -type f
```

- [ ] **Step 2: Run any existing tests**

```bash
python3 -m pytest tests/ -v 2>&1 || echo "No tests yet — expected"
```

- [ ] **Step 3: Verify no import errors across the full package**

```bash
python3 -c "import peerpedia_core; print('Full import OK')"
```
Expected: `Full import OK`
