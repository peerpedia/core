# Peerpedia Core

[![PyPI](https://img.shields.io/pypi/v/peerpedia-core)](https://pypi.org/project/peerpedia-core/)
[![Python](https://img.shields.io/pypi/pyversions/peerpedia-core)](https://pypi.org/project/peerpedia-core/)

Zero-dependency protocol layer for PeerPedia — the peer-reviewed academic
publishing platform built on Git.

```
peerpedia-core          ← this package: protocols, types, exceptions
├── peerpedia-storage   ← SQL + Git backends   (separate package)
├── peerpedia-transport ← HTTP / P2P transport  (separate package)
├── peerpedia-compute   ← scoring & reputation  (separate package)
├── peerpedia-social    ← notifications, shares (separate package)
└── peerpedia-app       ← CLI, server, REPL     (separate package)
```

## What this package is

**`peerpedia-core` defines the contracts** — every other PeerPedia package
depends on this one.  It contains:

- **Types** — frozen dataclasses for `Article`, `Review`, `User`, `Scores`,
  `Version`, query types, and write payloads.  All storage-agnostic, no IO.
- **Protocols** — `typing.Protocol` classes for storage backends, lifecycle
  state machines, sync, auth, authorization, compilation, and scoring.
- **Exceptions** — semantic exception hierarchy with machine-readable codes.
- **Crypto protocols** — algorithm-agnostic `SigningKey` / `PublicKey`
  interfaces.
- **Lifecycle dispatcher** — `execute()` reduces an action+context through
  a pluggable state machine.
- **Peerpedia facade** — dependency-injection wrapper that wires protocols
  into a usable engine.

The `Scores` type is a generic `Mapping[str, float]` wrapper — the compute
plugin (peerpedia-compute) defines which dimensions exist and how they are
aggregated.  Aggregate scores are a read-side projection over review data,
not an article attribute stored in core.

## What this package is NOT

- **Not a storage backend.**  See `peerpedia-storage` for SQLAlchemy and
  GitPython implementations of the storage protocols.
- **Not a scoring algorithm.**  See `peerpedia-compute` for average,
  reputation-weighted, and sedimentation engines.
- **Not a CLI, server, or REPL.**  See `peerpedia-app`.

## Quick start

```python
from peerpedia_core import Peerpedia
from peerpedia_core.types import Article, ArticleId, User, UserId

# Peerpedia needs concrete backends — swap these with real implementations
# from peerpedia-storage in production:
#
#   from peerpedia_storage import SqlArticleStorage, SqlUserStorage, SqlLifecycle
#
from tests.conftest import MemArticleStorage, MemLifecycle, MemUserStorage

storage = MemArticleStorage()
pp = Peerpedia(
    storage=storage,
    lifecycle=MemLifecycle(storage),
    user_storage=MemUserStorage(),
)

# Create an article
aid = pp.create()

# Revise it
article = Article(id=aid, title="My Paper", status="draft", authors=("Alice",))
pp.revise(aid, content="# Hello World", article=article)

# Read metadata back
meta = pp.read_meta(aid)
print(meta.title)  # "My Paper"
```

> **Note:** The `Mem*` backends above live in `tests/conftest.py` and are only
> available in editable/dev installs.  Production code imports from
> `peerpedia-storage` (SQLAlchemy + GitPython) or `peerpedia-transport`
> instead.

## Protocols

This table shows every protocol in core and which package implements it.

| Protocol | File | Implemented by |
|---|---|---|
| `ArticleMetaStorage` | `protocols/storage/article.py` | peerpedia-storage |
| `ArticleContentStorage` | `protocols/storage/article.py` | peerpedia-storage |
| `ArticleStorage` | `protocols/storage/article.py` | peerpedia-storage |
| `ReviewMetaStorage` | `protocols/storage/review.py` | peerpedia-storage |
| `ReviewContentStorage` | `protocols/storage/review.py` | peerpedia-storage |
| `UserStorage` | `protocols/storage/user.py` | peerpedia-storage |
| `Lifecycle` | `protocols/lifecycle.py` | peerpedia-app |
| `AuthProvider` | `protocols/auth.py` | peerpedia-transport |
| `Authorizer` | `protocols/authorizer.py` | peerpedia-app |
| `ScoringEngine` | `protocols/scoring.py` | peerpedia-compute |
| `Compiler` | `protocols/compiler.py` | peerpedia-app |
| `ArticleSync` | `protocols/sync.py` | peerpedia-transport |
| `ReviewSync` | `protocols/sync.py` | peerpedia-transport |

## Exceptions

All business-logic errors inherit from `PeerpediaError`:

```text
PeerpediaError            code="ERROR"
  ├── NotFoundError       code="NOT_FOUND"
  ├── NotAuthorizedError  code="NOT_AUTHORIZED"
  ├── ConflictError       code="CONFLICT"
  │   └── MergeConflictError  code="MERGE_CONFLICT"
  └── BadRequestError     code="BAD_REQUEST"
```

Each carries structured context (`permission`, `resource_type`,
`conflicting_entity`, etc.) for typed error handling.

## Requirements

- Python ≥ 3.11
- Zero dependencies

## License

AGPL-3.0 — see [LICENSE](LICENSE).
