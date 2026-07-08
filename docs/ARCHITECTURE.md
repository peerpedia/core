# Architecture — the five-package split

```
┌─────────────────────────────────────────────────────────────┐
│                    peerpedia-app                             │
│   CLI, server, REPL — wires everything together             │
│   Depends on: core, storage, transport, compute, social     │
└────────────────────┬───────────────────────┬────────────────┘
                     │                       │
         ┌───────────┴───────────┐   ┌───────┴───────────┐
         │                       │   │                   │
         ▼                       ▼   ▼                   ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────┐
│ peerpedia-storage │  │peerpedia-transport│  │  peerpedia-compute    │
│ SQL + Git backends│  │  HTTP / P2P sync │  │  scoring & reputation │
│ ArticleStorage    │  │  ArticleSync     │  │  ScoringEngine impl   │
│ UserStorage       │  │  AuthProvider    │  │  SedimentationEngine  │
│ ...               │  │  ...             │  │  ArticleScore         │
└──────────┬────────┘  └────────┬─────────┘  └───────────┬──────────┘
           │                    │                         │
           ▼                    ▼                         ▼
┌──────────────────────────────────────────────────────────────────┐
│                     peerpedia-social                              │
│  Notifications, shares, bookmarks, social graph, peer discovery  │
│  Depends on: core, storage                                        │
└──────────────────────────────────────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────────────────┐
│                     peerpedia-core                                │
│  Protocols, types, exceptions, lifecycle, crypto interfaces      │
│  Zero dependencies                                               │
└──────────────────────────────────────────────────────────────────┘
```

## The rule

**Every package depends on `peerpedia-core`.  No package depends on another
package's concrete classes.**  If package A needs something from package B,
the interface goes in `peerpedia-core` and both import it from there.

This eliminates circular dependencies and makes every backend swappable.

---

## Package breakdown

### `peerpedia-core` (this repository)

- **Types**: `Article`, `Review`, `User`, `ArticleId`, `Version`, `Scores`,
  `ArticleWrite`, `ReviewWrite`, `ArticleQuery`, etc. — all frozen dataclasses,
  no IO.
- **Protocols**: `typing.Protocol` for every backend concern — storage, lifecycle,
  sync, auth, authorization, compilation, scoring.
- **Exceptions**: semantic hierarchy with machine-readable codes.
- **Crypto**: abstract `SigningKey` / `PublicKey` protocols — no concrete impl.
- **Lifecycle dispatcher**: `execute(action, extra, context, lifecycle) -> ArticleId`.
- **Sync orchestrators**: `sync_article()` and `sync_review()` — transport-agnostic
  merge-base discovery and push/pull logic.
- **Peerpedia facade**: dependency-injection class that wires backends together.

Has **zero dependencies** — pure Python 3.11+.

### `peerpedia-storage` (separate package)

Implements the storage protocols against real backends:

| Protocol | Primary backend | Secondary backend |
|---|---|---|
| `ArticleMetaStorage` | SQLAlchemy (SQLite/Postgres) | none |
| `ArticleContentStorage` | GitPython (bare repos) | none |
| `ReviewMetaStorage` | SQLAlchemy | none |
| `ReviewContentStorage` | GitPython (article repo sub-dir) | none |
| `UserStorage` | SQLAlchemy | none |

Contains the reconcile logic that synchronises meta cache (DB) with content
SOT (git).  Every write goes to git first; the DB cache is rebuilt on demand
via `ArticleStorage.reconcile_article()`.

### `peerpedia-transport` (separate package)

Implements the sync and auth protocols for P2P communication:

| Protocol | Implementation |
|---|---|
| `ArticleSync` | HTTP client/server (httpx) over git bundles |
| `ReviewSync` | HTTP client/server over JSON payloads |
| `AuthProvider` | Ed25519 request signing |

Also provides the HTTP server middleware (rate limiting, request ID, security
headers, body limit) and client factories.

### `peerpedia-compute` (separate package)

Implements the scoring protocol and defines its own enriched types:

| Protocol / Type | Implementation |
|---|---|
| `ScoringEngine` | `AverageEngine`, `WeightedEngine`, `SedimentationEngine` |
| `ArticleScore` (new) | Enriched aggregate with provenance metadata |
| `ReputationScores` | Per-user reputation computation |
| `ScoreCache` | Optional read-through cache |

Pure computation — no storage access in the engine layer.  The
`ScoringService` orchestrator reads reviews from storage and passes them
to the engine, then enriches the result.

### `peerpedia-social` (separate package)

Social features that interact with users but don't fit the article/review
lifecycle:

- Notifications
- Shares / reshare graph
- Bookmarks
- Social graph (follow / followers / following)
- Peer discovery

The social layer may define its own storage protocols or reuse existing ones.

### `peerpedia-app` (separate package)

The end-user application — depends on every other package:

- **CLI**: rich command-line interface with `argcomplete` shell completion
- **REPL**: interactive shell with `prompt-toolkit` TUI
- **Server**: Starlette HTTP server with `uvicorn`

Wires everything together at the composition root.  Contains the lifecycle
plugin that knows what state transitions are valid (draft → sedimentation →
published, etc.).

## Data flow patterns

### Write path (create → revise → publish → review)

```
CLI command
    │
    ▼
peerpedia-app: call_spec()
    │
    ▼
Peerpedia facade method
    ├── _authorize()                ← Authorizer protocol (optional)
    └── execute()                   ← Lifecycle protocol
            │
            ▼
        lifecycle.resolve(action)
            │
            ▼
        ArticleStorage action method
            │
            ├── _content.write_article()   ← git SOT
            ├── _meta.update()             ← DB cache (via reconcile)
            └── ...                         ← no scoring computation
```

### Read path (fetch article scores)

```
API / CLI command
    │
    ▼
peerpedia-app: call scoring service
    │
    ▼
ScoringService.aggregate(aid)
    ├── _storage.review_meta.list(aid)     ← read reviews
    ├── _engine.compute(reviews)           ← pure algorithm
    └── → ArticleScore                     ← enriched result
```

### Sync path (P2P article exchange)

```
sync_article(sync, storage, aid, peer_url)
    │
    ├── content.history(aid)               ← local versions
    ├── sync.fetch_version(peer_url, aid)  ← remote HEAD
    ├── find_merge_base(local, probe)      ← common ancestor
    │
    ├── Local ahead  → content.create_bundle() → sync.push()
    ├── Remote ahead → sync.pull_all() → content.ingest_bundle() → reconcile
    └── Diverged     → MergeConflictError
```

## Design principles

1. **Zero dependencies in core.**  The protocol layer imports only from the
   Python standard library.  Heavy dependencies (SQLAlchemy, GitPython, httpx,
   rich) live in downstream packages where they belong.

2. **Protocols, not abstract base classes.**  `typing.Protocol` enables duck
   typing — backends don't inherit from core classes, they just implement the
   right methods.  This makes testing trivial (swap a real backend for a
   `Mem*` class) and keeps the coupling surface minimal.

3. **Entities are frozen dataclasses.**  No ORM base classes, no magic
   `__init__`, no lazy loading.  An `Article` is a bag of fields that
   round-trips through JSON.  Storage backends map these to their native
   representation.

4. **Aggregate scores are a read-side projection.**  `Article.score` is not
   stored on the entity.  It is computed on demand from review data by
   `peerpedia-compute`.  This eliminates write-time O(n) recomputation and
   stale-read problems.

5. **Exceptions carry structured context.**  Every `PeerpediaError` has a
   machine-readable `.code`, a human-readable `.detail`, and arbitrary
   `.context` key-value pairs.  Callers can catch `NotFoundError` and read
   `.resource_id` without parsing the error message.
