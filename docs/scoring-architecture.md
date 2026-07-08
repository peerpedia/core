# Scoring architecture — compute as a read-side projection

## Separation of concerns

Core owns the **vocabulary**; compute owns the **algorithms**.

```
peerpedia-core (zero-dep protocol layer):
  Scores(dimensions=Mapping[str, float])     ← value object, shared vocabulary
  ScoringEngine.compute(reviews) -> Scores   ← protocol, contract only
  Review.scores: Scores                      ← authored input data

peerpedia-compute (depends on core + storage):
  ArticleScore                               ← enriched aggregate result
  AverageEngine / WeightedEngine             ← algorithm implementations
  ScoringService                             ← orchestrator: read reviews, run engine, return
  ScoreCache (optional)                      ← read-through cache, explicit staleness
```

The wall between them is intentional. Core never imports from compute. Compute never modifies storage. Aggregate scores are a read-side projection over review data, not an article attribute.

## What core provides

### `Scores` — generic key-value wrapper

```python
@dataclass(frozen=True)
class Scores:
    dimensions: Mapping[str, float]
```

Generic by design. The core does not know what dimensions exist — that is a plugin concern. Five dimensions, three dimensions, LLM latent embeddings — they all fit `Mapping[str, float]`.

### `ScoringEngine` — protocol, not implementation

```python
class ScoringEngine(Protocol):
    def compute(self, reviews: list[Review]) -> Scores: ...
```

This is the contract that compute engines implement. Core does not ship any implementation — not even a simple average. That belongs in the compute module.

### `Review.scores` — the authored data

Each `Review` carries `scores: Scores`. This is **user input**, written at review creation time and stored in the git SOT. It is authority data, not derived. It stays on the Review entity permanently.

## What compute provides

### `ArticleScore` — enriched aggregate

```python
@dataclass(frozen=True)
class ArticleScore:
    """Computed aggregate — provenance metadata alongside the scores."""
    article_id: ArticleId
    scores: Scores                    # aggregated dimension values
    review_count: int                 # number of reviews that contributed
    scope_counts: dict[str, int]      # e.g. {"sedimentation": 3, "published": 1}
    computed_at: datetime
```

The aggregate is a **derived value with provenance**. `review_count` and `scope_counts` distinguish "aggregated from 10 sedimentation reviews" from "aggregated from 1 casual review" — without them, `Scores({"originality": 4.0})` is ambiguous.

`ArticleScore` is NOT stored on `Article`. It lives only in the compute module's return types and optionally in a read-through cache. It never enters core.

### Engines — one interface, multiple algorithms

```python
class AverageEngine:
    """Simple mean — equal weight per review, no adjustments."""
    def compute(self, reviews: list[Review]) -> Scores:
        dims: dict[str, list[float]] = {}
        for r in reviews:
            for dim, val in r.scores.dimensions.items():
                dims.setdefault(dim, []).append(val)
        return Scores(dimensions={
            d: sum(vals) / len(vals) for d, vals in dims.items()
        })

class WeightedEngine:
    """Supports reviewer reputation weights and scope weights."""
    def __init__(self, reviewer_weights: dict[UserId, float] | None = None,
                 scope_weights: dict[str, float] | None = None):
        self._reviewer_weights = reviewer_weights
        self._scope_weights = scope_weights

    def compute(self, reviews: list[Review]) -> Scores: ...

class SedimentationEngine:
    """Applies no-review penalty when an article has zero reviews in the pool."""
    def compute(self, reviews: list[Review]) -> Scores: ...
```

Engines are **pure functions wrapped as classes** for configuration injection. No storage access, no side effects. Testing an engine means constructing `list[Review]` and calling `compute()`.

### ScoringService — the orchestrator

```python
class ScoringService:
    """Reads reviews from storage, runs the engine, returns ArticleScore."""

    def __init__(self, storage: ArticleStorage, engine: ScoringEngine):
        self._storage = storage
        self._engine = engine

    def aggregate(self, article_id: ArticleId) -> ArticleScore:
        reviews = self._storage.review_meta.list(article_id)
        scores = self._engine.compute(reviews)
        scope_counts: dict[str, int] = {}
        for r in reviews:
            scope_counts[r.scope] = scope_counts.get(r.scope, 0) + 1
        return ArticleScore(
            article_id=article_id,
            scores=scores,
            review_count=len(reviews),
            scope_counts=scope_counts,
            computed_at=datetime.now(timezone.utc),
        )
```

The caller decides when and how often to call `aggregate()`. No writes, no side effects — just a read-side projection.

### ScoreCache (optional)

```python
class ScoreCache:
    """Read-through cache.  Caller invalidates explicitly on events that
    change the aggregate (review created, deleted, synced)."""

    def __init__(self, service: ScoringService, backend: ...): ...

    def get(self, article_id: ArticleId) -> ArticleScore:
        """Returns cached or computes fresh."""

    def invalidate(self, article_id: ArticleId) -> None:
        """Call after create_review / delete_review / sync_review."""
```

The cache is **explicitly managed** — no write-through, no magic. If the caller never invalidates, the cache becomes stale. This is intentional: it forces awareness that the aggregate is a snapshot, not ground truth.

## Data flow

```
    write side                              read side
    ──────────                              ─────────

    User submits review
    │
    ▼
pp.review(aid, review=Review(scores=...))     UI / API wants scores
    │                                              │
    ▼                                              ▼
ArticleStorage.create_review()             ScoringService.aggregate(aid)
    │                                              │
    ├── review_meta.create()                      ├── review_meta.list(aid)
    ├── review_content.write_review()             ├── review_content available
    └── _reconcile_reviews()                      │    for thread display
                                                  │
    (no scoring computation)                      ├── engine.compute(reviews)
    (no Article.score mutation)                   └── → ArticleScore
```

Write path: as fast and simple as possible — just persist the review. No O(n) aggregate recomputation.

Read path: caller pays the cost of aggregation when they need it. If they call twice for the same result, they add caching (opt-in).

## Why this is correct

**1. The aggregate is a projection, not an attribute.**

`Article.score` would be stale the moment after you write it. Every `create_review`, `delete_review`, `update_review`, or `sync_review` can change it. Storing it on the entity creates an implicit synchronization contract that is impossible to enforce across distributed peers.

**2. Scoring algorithms are pluggable.**

`AverageEngine` is the simplest possible default. But the system is designed to support `WeightedEngine` (reputation-weighted), `SedimentationEngine` (penalty-aware), or even an ML-based engine that takes review text embeddings as input — without changing a single line in core or storage.

**3. The provenance makes the aggregate interpretable.**

`ArticleScore(review_count=1)` is very different from `ArticleScore(review_count=10)`. Without review_count and scope_counts, consumers can't tell whether a 4.5 average is robust or fragile.

**4. No silent cache invalidation.**

Write-through cache invalidation is a hidden dependency graph. The explicit `ScoreCache.invalidate()` call makes the cache boundary visible: the caller knows they're reading a cached value and knows when it was last refreshed.

## Migration from the original model

The original `peerpedia-core` stored `Article.score: Scores | None` and computed it synchronously inside `ArticleStorage.create_review()`. Migration:

1. Drop the `score` column from the article meta table (storage migration)
2. `ScoringService` becomes the canonical read path for aggregate scores
3. Optional `ScoreCache` replaces the stored column — trade write-time O(n) for read-time O(n) with cache TTL

Old code that reads `article.score` must change to `service.aggregate(article_id).scores`. This is a breaking change, but it's mechanical and confined to the read side.
