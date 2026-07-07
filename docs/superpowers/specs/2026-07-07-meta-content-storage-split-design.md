# Meta/Content Storage Split — Design Spec

Date: 2026-07-07

## Problem

`ArticleStorage` currently bundles metadata and content operations into a single
protocol.  But metadata and content are universally distinct storage concerns:

| | Meta | Content |
|---|---|---|
| Size | Small (~KB) | Large (~MB) |
| Structure | Typed fields | Unstructured text |
| Versioning | Derived from content | Native (git commits) |
| Queryability | Indexable, filterable | Full-text only |
| Source of truth | Cache (DB) | Git repo |

A single protocol conflates two fundamentally different storage semantics,
making it impossible for a backend to optimize one without coupling to the
other.

## Design

Split `ArticleStorage` into three protocols:

```
ArticleContentStorage (git SOT)    ArticleMetaStorage (DB cache)
──────────────────────────────     ─────────────────────────────
create() → ArticleId               create() → ArticleId
read(key) → ContentRef             read(key) → Article
deref_body(ref) → str              update(key, meta) → Version
update(key, content) → Version     delete(key) → Version
delete(key) → Version              query(query) → list[Article]
history(key, since) → list[...]
diff(key, va, vb) → ArticleDiff

         └──────────── ArticleStorage ─────────────┘
              get_meta()  get_content()
              read_meta()  read_content()
              reconcile(key)
```

### `ArticleMetaStorage`

Indexed metadata cache (typically DB-backed).  Fast reads, queryable.
Git is the source of truth; this cache is rebuilt via `reconcile()`.

```python
class ArticleMetaStorage(Protocol):
    def create(self) -> ArticleId:
        """Allocate a new article id with empty metadata (git init)."""
        ...

    def read(self, key: ArticleId) -> Article:
        """Return cached metadata for *key*."""
        ...

    def update(self, key: ArticleId, meta: Article) -> Version:
        """Replace cached metadata for *key*. Returns content version."""
        ...

    def delete(self, key: ArticleId) -> Version:
        """Remove metadata row for *key*."""
        ...

    def query(self, q: ArticleQuery | None = None) -> list[Article]:
        """Search metadata with optional filters."""
        ...
```

### `ArticleContentStorage`

Versioned content store (typically git-backed).  Source of truth for body text,
commit history, and authorship.

```python
class ArticleContentStorage(Protocol):
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
```

### `ArticleStorage` (composed)

Aggregates the two sub-protocols and adds `reconcile` — the operation
that rebuilds the meta cache from content source-of-truth.

```python
class ArticleStorage(Protocol):
    def get_meta(self) -> ArticleMetaStorage:
        """Return the metadata sub-storage."""
        ...

    def get_content(self) -> ArticleContentStorage:
        """Return the content sub-storage."""
        ...

    def read_meta(self, key: ArticleId) -> Article:
        """Convenience — delegates to ``get_meta().read(key)``."""
        ...

    def read_content(self, key: ArticleId) -> ContentRef:
        """Convenience — delegates to ``get_content().read(key)``."""
        ...

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

## Lifecycle "write" action

The lifecycle `write` action composes both sub-storages + reconcile:

```
execute("write", extra, id, lifecycle):
    1. storage.get_content().update(id, extra["content"])  → Version
    2. storage.get_meta().update(id, extra["article"])      → Version
    3. storage.reconcile(id)                                → rebuild cache
```

Other lifecycle actions (`create`, `revise`, `publish`, `delete`, `review`)
follow the same pattern — they compose sub-storage operations through the
lifecycle morphisms, never calling sub-storage methods directly.

## Entity changes

No new entity types.  Existing types (`ArticleId`, `Article`, `ContentRef`,
`Version`, `HistoryEntry`, `ArticleDiff`) remain as-is.  The `BibData` and
`Article.deref()` accessor are unchanged.

## Files to modify

| File | Change |
|---|---|
| `protocols/storage.py` | Rewrite — 3 protocols replacing 1 |
| `types/entities.py` | No structural changes needed |
| `protocols/__init__.py` | Export `ArticleMetaStorage`, `ArticleContentStorage` |
| `protocols/lifecycle.py` | No changes (unchanged `execute` signature) |

## Non-goals

- This spec does NOT define concrete backend implementations
  (e.g., `GitContentStorage`, `SqliteMetaStorage`).
- `ReviewData` and `User` storage are out of scope.
- The `Authorizer` protocol is unchanged.
