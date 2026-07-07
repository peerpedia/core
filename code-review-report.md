下面是基于你贴出的 source dump 的静态审阅。整体看，方向是好的：你在试图把 **entity / protocol / storage adapter / lifecycle / facade** 分清楚，并且 “meta cache + git source of truth” 的 split 也合理。但目前这个包还处在 **架构草图 / protocol sketch** 阶段，离一个可稳定扩展的 core package 还有几个关键问题要先解决。

我按严重程度说。

---

## 总体评价

### 优点

1. **边界意识不错**
   - `types` 基本无 IO。
   - `protocols` 只定义接口。
   - `ArticleMetaStorage` 和 `ArticleContentStorage` 分离是正确方向。
   - review 也试图区分 meta index 和 content SOT。

2. **插件化方向合理**
   - lifecycle plugin。
   - scoring plugin。
   - compiler plugin。
   - crypto / auth protocol。
   - sync protocol。

3. **核心 domain 概念比较清楚**
   - `ArticleId`, `ReviewId`, `UserId`, `Version`, `ContentRef` 这些 wrapper 类型有助于避免裸字符串混用。
   - `Scores` 不硬编码 dimension，这点对后续 peer review 模型很有用。

4. **测试覆盖了主路径**
   - 至少验证了 create / revise / publish / review / delete 的 happy path。
   - 也有 sync、auth、compiler、review content 的最小集成测试。

---

# P0：如果这些是实际源码，会直接无法 import

你贴出来的代码里大量出现：

```python
from **future** import annotations
```

```python
def **init**(...)
```

```python
**all** = [...]
```

这不是合法 Python。应该是：

```python
from __future__ import annotations
```

```python
def __init__(...)
```

```python
__all__ = [...]
```

如果这是 source dump 的渲染问题，可以忽略。但如果实际仓库也是这样，测试不会跑起来，属于最高优先级修复。

---

# P0：`Article.encode()` / `decode()` 目前不可靠

你在 docstring 里写的是 canonical JSON：

```python
def encode(self) -> bytes:
    """Article → transport bytes (canonical JSON)."""
```

但实际不是 canonical，也不是稳定的 round-trip。

目前：

```python
"score": self.score,
```

然后：

```python
json.dumps(self.to_dict(), ensure_ascii=False, default=str)
```

这会把 `Scores(...)` 直接转成字符串，例如：

```python
"Scores(dimensions={'clarity': 4.0})"
```

然后 `from_dict` 里又是：

```python
score=d.get("score")
```

所以 decode 之后 `score` 可能变成 `str`，不是 `Scores`。

这会破坏类型不变量。

建议改成显式序列化：

```python
def to_dict(self) -> dict:
    d: dict[str, object] = {
        "id": self.id.id,
        "title": self.title,
        "status": self.status,
        "authors": list(self.authors),
        "abstract": self.abstract,
        "keywords": list(self.keywords),
        "content_ref": self.content_ref.ref if self.content_ref else None,
        "format": self.format.name if self.format else None,
        "score": dict(self.score.dimensions) if self.score else None,
    }
    ...
```

然后：

```python
score = Scores(dimensions=d["score"]) if d.get("score") else None
```

并且 canonical JSON 应该至少用：

```python
json.dumps(
    self.to_dict(),
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
)
```

不要用 `default=str`，因为它会掩盖序列化 bug。

---

# P0：review scoring 逻辑是错的

`ArticleStorage.create_review()` 里：

```python
scores = Scores(dimensions=json.loads(scores_json))
...
article = self._meta.read(article_id)
self._meta.update(article_id, replace(article, score=scores))
```

这只是把 **当前这一条 review 的 scores** 写成 article aggregate score。

但你的系统设计里有：

```python
class ScoringEngine(Protocol):
    def compute(self, reviews: list[Review]) -> Scores:
        ...
```

也就是说 aggregate score 应该是由所有 review 计算出来的。

目前如果有两个人 review：

```python
Alice: clarity = 5
Bob: clarity = 1
```

article score 会变成最后一次 review 的分数，而不是平均值或插件定义的 aggregate。

建议：

1. `ArticleStorage` 构造函数接受可选 `ScoringEngine`。
2. 每次 create/update/delete review 后：
   - `_reconcile_reviews(article_id)`
   - `reviews = self._review_meta.list(article_id)`
   - `article_score = scoring.compute(reviews)`
   - update article meta

示意：

```python
class ArticleStorage:
    def __init__(
        self,
        meta: ArticleMetaStorage,
        content: ArticleContentStorage,
        review_meta: ReviewMetaStorage,
        review_content: ReviewContentStorage,
        scoring: ScoringEngine | None = None,
    ):
        ...
        self._scoring = scoring

    def _update_article_score(self, article_id: ArticleId) -> None:
        if self._scoring is None:
            return

        reviews = self._review_meta.list(article_id)
        score = self._scoring.compute(reviews)

        article = self._meta.read(article_id)
        self._meta.update(article_id, replace(article, score=score))
```

然后在 `create_review`, `update_review`, `delete_review` 后调用。

---

# P0：review content 和 article content 的边界混乱

在 `create_review()` 里：

```python
thread_content = (
    self._content.read_body(review.content_ref)
    if review.content_ref else ""
)
```

这里 `_content` 是 `ArticleContentStorage`，它负责 article body。

但 `review.content_ref` 表示 review body 的 content ref。这个 ref 不一定属于 article content storage。

也就是说你用 article content store 去 dereference review body，这在真实 backend 里很可能是错的。

现在的数据流也有点别扭：

```python
def create_review(
    self, article_id: ArticleId, review: Review, scores_json: str,
) -> None:
```

`review` 里有 `content_ref`，但实际 create review 又把 thread entry append 到 `ReviewContentStorage`。更自然的是：

```python
def create_review(
    self,
    article_id: ArticleId,
    review: Review,
    scores: Scores,
    body: str,
) -> None:
    ...
```

或者：

```python
def create_review(
    self,
    article_id: ArticleId,
    reviewer_id: UserId,
    scores: Scores,
    content: str,
) -> ReviewId:
    ...
```

序列化成 `scores.json` 应该是 adapter 层的事情，而不是 core service 接收一个 JSON string。

目前 `scores_json: str` 泄漏了存储格式。

---

# P0：`CommitData` 设计了但完全没用上

你有：

```python
@dataclass
class CommitData:
    signer: SigningKey
    message: str
    user: User
```

但所有 storage write methods 都没有接收 `CommitData`：

```python
def update(self, key: ArticleId, content: str) -> Version:
```

```python
def update(self, key: ArticleId, meta: Article) -> Version:
```

这和你的文档冲突：

> Everything a storage backend needs to record who wrote what and why.

如果 git 是 source of truth，你通常需要知道：

- author
- committer
- commit message
- signing key / signature
- timestamp perhaps
- semantic action marker, e.g. `[revise]`, `[publish]`, `[review]`

否则后面你说的：

```python
authors ← git commit authors
status ← git commit message transitions
created_at / updated_at ← git commit timestamps
```

没有足够数据来源。

建议所有 mutating SOT methods 接收 `CommitData`，例如：

```python
def update(
    self,
    key: ArticleId,
    content: str,
    commit: CommitData,
) -> Version:
    ...
```

review content 也一样：

```python
def append_thread_entry(
    self,
    article_id: ArticleId,
    reviewer_id: UserId,
    content: str,
    marker: str,
    commit: CommitData,
) -> Version:
    ...
```

如果你暂时不想在 core 里带签名，也应该删掉 `CommitData`，避免 API 设计和实现不一致。

---

# P1：`sync_article()` 的逻辑问题比较大

这一块目前最危险。主要问题如下。

---

## 1. 条件表达式优先级容易出错

当前：

```python
if merge_base is None or merge_base.id == local_head.id if local_head else False:
```

这在 Python 里等价于：

```python
if (merge_base is None or merge_base.id == local_head.id) if local_head else False:
```

这不是直观含义。

至少应该写成：

```python
if merge_base is None or (
    local_head is not None and merge_base.id == local_head.id
):
    ...
```

但就算修了括号，语义也未必对。

---

## 2. `merge_base is None` 不应该直接当成 “local behind”

当前：

```python
if merge_base is None or ...:
    # Local behind — pull remote
```

但 `merge_base is None` 可能表示：

1. 本地没有历史；
2. 远端没有共同祖先；
3. probe 失败；
4. 历史不连通；
5. remote 是完全不同 fork。

这些情况不应该都静默 pull。尤其如果本地和远端都有内容但没有共同祖先，那应该是 conflict / unrelated histories。

应该区分：

```python
if local_head is None and remote_head is not None:
    # local empty, pull full
elif local_head is not None and remote_head is None:
    # remote empty, push full
elif merge_base is None:
    raise MergeConflictError("No common ancestor")
```

---

## 3. `_probe` 不是一个真正的 “remote has version” check

当前：

```python
def _probe(v: Version) -> bool | None:
    return sync.pull_all(peer_url, article_id, since=v) is not None
```

但 `pull_all(..., since=v)` 的语义是“从版本 v 之后拉增量”，不是“远端是否包含版本 v”。

如果远端已经有版本 `v`，但没有更新，可能返回 `None`。这不能说明它没有 `v`。

需要一个明确的 protocol method：

```python
def has_version(
    self,
    peer_url: str,
    article_id: ArticleId,
    version: Version,
) -> bool | None:
    ...
```

或者：

```python
def fetch_history(
    self,
    peer_url: str,
    article_id: ArticleId,
    since: Version | None = None,
) -> list[Version]:
    ...
```

否则 `find_merge_base()` 的假设不成立。

---

## 4. `sync_article()` 文档和返回值不一致

文档说：

```python
Returns the new local HEAD version after sync.
```

但这里：

```python
return sync.push(peer_url, article_id, bundle)
```

返回的是 remote receiver assigned version，不一定是 local HEAD。

如果 local push 不改变 local content，那么应该返回 `local_head`。

---

## 5. diverged 分支没有真正 merge

当前：

```python
else:
    # Diverged — pull remote, local stays on top
    bundle = sync.pull_all(peer_url, article_id, since=merge_base)
    if bundle:
        content.ingest_bundle(article_id, bundle)
        storage.reconcile_article(article_id)
```

这只是 ingest bundle。具体是 merge、fetch、fast-forward、overwrite，完全取决于 backend。core 文档说 three-way merge，但没有暴露冲突处理。

建议这里不要假装 merge。要么：

1. core 只做 transport orchestration，不声称 merge；
2. 或者 `ArticleContentStorage` 增加明确方法：

```python
def merge_bundle(
    self,
    key: ArticleId,
    data: bytes,
    base: Version,
) -> Version:
    ...
```

并且可能抛：

```python
MergeConflictError
```

---

# P1：`search_monotonic_boundary()` 有边界 bug

你定义的是：

```python
probe(i) is True for all i < boundary
probe(i) is False for all i >= boundary
```

但当前 exponential phase 从 `upper = 1` 开始 probe：

```python
upper = 1
while upper <= max_idx:
    r = probe(upper)
```

如果 boundary 是 `0`，也就是 `probe(0) is False`，当 `max_idx > 0` 时你会先 probe `1`，然后返回 `1`，而不是 `0`。

示例：

```python
probe = lambda i: False
search_monotonic_boundary(probe, max_idx=10)
```

期望返回 `0`，目前会返回 `1`。

可以先检查 index 0：

```python
r0 = probe(0)
if r0 is None:
    return None
if r0 is False:
    return 0
```

然后再从 `upper = 1` 开始。

---

# P1：`ArticleStorage` 的事务性和 SOT/cache 顺序问题

你的设计是：

- git content = source of truth
- meta DB = cache

但很多操作顺序和这个设计不完全一致。

---

## `delete_article()`

当前：

```python
self._meta.delete(article_id)
self._content.delete(article_id)
```

如果 content delete 失败，meta 已经删了，但 SOT 还在。

如果 git 是 SOT，通常应该：

```python
self._content.delete(article_id)
self.reconcile_article(article_id)
```

或者 tombstone 后再更新 meta。

---

## `update_article()`

当前：

```python
self._content.update(article_id, content_str)
self._meta.update(article_id, article)
self.reconcile_article(article_id)
```

如果真实 `extract()` 从 git 读取 frontmatter，那么中间的 `_meta.update(article_id, article)` 只是临时写缓存，随后又被 `reconcile_article()` 覆盖。

更好的模型是：

1. 把 metadata 和 content 一起写入 SOT；
2. 从 SOT extract；
3. 更新 meta cache。

即：

```python
self._content.update_article_bundle(article_id, article, content_str, commit)
self.reconcile_article(article_id)
```

现在 `ArticleContentStorage.update()` 只接收 `content: str`，没有 metadata，所以真实 backend 不知道 title/status/abstract 怎么进 git。

这和你的 `extract()` 注释冲突：

```python
title / abstract ← YAML frontmatter
```

因为 core 没有任何地方把 frontmatter 写入 content store。

---

# P1：`extract()` 默认实现会让 `content_ref` 永远是 `None`

`create_article()`：

```python
article_id = self._meta.create()
self._content.create(article_id, Format(name="markdown"))
self.reconcile_article(article_id)
```

默认 `extract()`：

```python
return self._meta.read(key)
```

所以 meta 里的 `content_ref` 还是 `None`。

这和 `Article` 设计中：

```python
content_ref: ContentRef | None = None
format: Format | None = None
```

不太一致。

如果默认 storage 是 composed storage，最起码应该：

```python
def extract(self, key: ArticleId) -> Article:
    article = self._meta.read(key)
    try:
        content_ref = self._content.read(key)
    except Exception:
        content_ref = article.content_ref

    return replace(
        article,
        content_ref=content_ref,
        format=article.format or Format(name="markdown"),
    )
```

当然真实 git backend 应该 override。

---

# P1：`_reconcile_reviews()` 会吞掉所有异常

当前：

```python
try:
    existing = rmeta.read(key, review.reviewer_id)
except Exception:
    existing = None
```

这会把数据库连接失败、序列化错误、bug 等全部当成 “not found”。

应该只 catch `NotFoundError`。

```python
from peerpedia_core.exceptions import NotFoundError

try:
    existing = rmeta.read(key, review.reviewer_id)
except NotFoundError:
    existing = None
```

如果你的 storage backend 现在用 `KeyError`，那也应该统一 protocol exception。

---

# P1：`MemReviewStorage` 的 key 设计是错的

测试里的 in-memory review meta：

```python
self._rows: dict[str, Review] = {}
...
self._rows[reviewer_id.id] = r
```

这意味着同一个 reviewer 对两个 article 的 review 会互相覆盖。

应该用 composite key：

```python
def _key(self, article_id: ArticleId, reviewer_id: UserId) -> tuple[str, str]:
    return (article_id.id, reviewer_id.id)
```

或者 string key：

```python
f"{article_id.id}/{reviewer_id.id}"
```

否则测试会掩盖真实 bug。

---

# P1：`Review` 的很多字段在 reconcile 时丢失

`_reconcile_reviews()` 里：

```python
updated = Review(
    id=existing.id,
    article_id=key,
    reviewer_id=review.reviewer_id,
    scores=review.scores,
)
```

这会丢掉：

```python
scope
content_ref
created_at
```

如果这些字段有意义，应该保留：

```python
updated = replace(
    existing,
    article_id=key,
    reviewer_id=review.reviewer_id,
    scope=review.scope,
    scores=review.scores,
    content_ref=review.content_ref,
    created_at=review.created_at,
)
```

或者 `extract_reviews()` 应该返回完整 `Review`，然后直接使用其字段，只保留 existing id。

---

# P1：lifecycle 和 authorization 没有接上

你定义了：

```python
class Authorizer(Protocol):
    def authorize(self, user: User, article: Article, action: str) -> bool:
        ...
```

但 `execute()` 完全不处理 user / auth / permission。

现在实际 pipeline 是：

```python
action -> lifecycle.compatible -> resolve -> execute
```

没有：

```python
user -> authorizer.authorize
```

文档里写：

> Handlers call this BEFORE execute()

那意味着 facade 或 server 要负责。但 `Peerpedia` facade 目前也没有 `user` 参数：

```python
def publish(self, article_id: ArticleId, article: Article) -> ArticleId:
    return execute("publish", {"article": article}, article_id, self.lifecycle)
```

所以现在 core facade 没法做权限控制。

你需要二选一：

### 方案 A：authorization 不属于 core facade

那就明确写：

> `Peerpedia` facade assumes authorization has already been performed by the caller.

并且不要让人误以为 core 保证权限。

### 方案 B：把 authorizer 注入 facade

例如：

```python
class Peerpedia:
    def __init__(
        self,
        storage: ArticleStorage,
        lifecycle: Lifecycle,
        user_storage: UserStorage,
        authorizer: Authorizer | None = None,
        ...
    ):
        ...
```

然后操作接收 `user`：

```python
def publish(self, user: User, article_id: ArticleId, article: Article) -> ArticleId:
    current = self.storage.read_article(article_id)
    if self.authorizer and not self.authorizer.authorize(user, current, "publish"):
        raise NotAuthorizedError(...)
    return execute(...)
```

---

# P1：`Lifecycle.compatible()` 没有强制 context 合法性

现在 `execute("revise", {}, None, lifecycle)` 可以进入 lifecycle，除非 plugin 自己检查。

`MemLifecycle.compatible()` 更是：

```python
return action in self.actions
```

所以 revise/delete/review 可以接受 `context=None`，然后后面炸掉。

建议 core 的 `execute()` 对 universal action 做最基本检查：

```python
if action == "create" and context is not None:
    raise BadRequestError(...)
if action != "create" and context is None:
    raise BadRequestError(...)
```

或者在 lifecycle protocol 文档里明确所有 plugin 必须检查。

我更建议 core 做 universal invariant。

---

# P1：`AuthProvider` 的 TOFU 模型还不完整

你的 auth header：

```text
Authorization: Peerpedia <uid>:<pubkey>:<ts>:<body_hash>:<sig>
```

文档说：

> pubkey is embedded in the header so verification does not need a database lookup (TOFU model)

但真正的 TOFU 至少需要：

1. 第一次见到 `uid -> pubkey` 时 pin 住；
2. 后续同一个 uid 必须用同一个 pubkey；
3. timestamp 需要有效窗口；
4. 最好有 nonce 或 request id 防 replay；
5. body hash 必须明确 hash 算法；
6. path canonicalization 要定义清楚，包括 query string、trailing slash、percent encoding。

如果 verify 完全不查数据库或 trust store，那么攻击者可以自造：

```text
uid = alice
pubkey = attacker_pubkey
sig = attacker_signature
```

验证仍然能过。它只能证明“这个 header 是由 header 里给出的 pubkey 对应私钥签的”，不能证明 pubkey 属于 Alice。

所以 protocol 需要接入 trust store，或者文档明确这只是 cryptographic envelope，不是 identity binding。

---

# P2：类型和 API 设计上的细节

## 1. `Scores` 是 frozen dataclass，但内部 mapping 可能可变

```python
@dataclass(frozen=True)
class Scores:
    dimensions: Mapping[str, float] = field(default_factory=dict)
```

`frozen=True` 只冻结属性绑定，不冻结内部 dict。

例如：

```python
d = {"clarity": 4.0}
s = Scores(d)
d["clarity"] = 1.0
```

`s` 会变。

如果需要真正 immutable，可以在 `__post_init__` 里 copy 成 `MappingProxyType`，或者接受这个限制。

简单方案：

```python
from types import MappingProxyType

@dataclass(frozen=True)
class Scores:
    dimensions: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(
            self,
            "dimensions",
            MappingProxyType(dict(self.dimensions)),
        )
```

不过 `MappingProxyType` 不好 JSON serialize。另一种是内部存 tuple pairs。

---

## 2. `User.public_key` 写死 Ed25519，和 crypto “algorithm-agnostic” 冲突

`crypto.py` 文档说：

```python
Core does not know the concrete signature scheme.
```

但 `User` 写：

```python
public_key: str | None = None  # Ed25519 public key (hex)
```

`AuthProvider` 也写死：

```python
private_key: bytes         # Ed25519 private key
pubkey_hex: str            # Ed25519 public key
```

这不是 algorithm-agnostic。

可以改成：

```python
@dataclass(frozen=True)
class PublicKeyInfo:
    algorithm: str
    encoding: str
    value: str
```

或者至少：

```python
public_key: str | None = None
public_key_algorithm: str | None = None
```

---

## 3. `CommitData` 示例是错的

文档里：

```python
user=User(id="alice-1", name="Alice")
```

但 `User.id` 类型是 `UserId`，应该是：

```python
user=User(id=UserId(id="alice-1"), name="Alice")
```

---

## 4. `ArticleQuery` 没有验证 `limit` / `offset`

建议至少避免：

```python
limit=-1
offset=-100
```

可以加：

```python
def __post_init__(self):
    if self.limit is not None and self.limit < 0:
        raise ValueError("limit must be non-negative")
    if self.offset < 0:
        raise ValueError("offset must be non-negative")
```

如果不想在 entity 层 raise，也应该在 storage query 层定义行为。

---

## 5. `peerpedia_core/__init__.py` 没有导出 facade

现在用户可能期望：

```python
from peerpedia_core import Peerpedia
```

但 `__init__.py` 是空的。

建议导出核心 API：

```python
from peerpedia_core.peerpedia import Peerpedia

__all__ = ["Peerpedia"]
```

或者连常用 types 一起导出。

---

# P2：tests 目前覆盖不够，而且有些测试会掩盖 bug

## 1. `MemMetaStorage.query()` 完全忽略 `ArticleQuery`

```python
def query(self, q: ArticleQuery | None = None) -> list[Article]:
    return list(self._rows.values())
```

但 `ArticleQuery` 的语义写得很具体：

- statuses
- search
- id_prefix
- limit
- offset

测试应该验证这些。

---

## 2. `test_full_lifecycle()` publish 的 meta 用的是旧 article

你先：

```python
article = meta_store.read(new_id)
```

这是空 title 的 draft。

后来 revise 用：

```python
revised_meta = Article(
    id=article.id,
    title="A Great Paper",
    ...
)
```

但 publish 的时候：

```python
pub_meta = Article(
    id=article.id,
    title=article.title,
    status="published",
    authors=article.authors,
    ...
)
```

这里 `article` 还是最早那个空 article，不是 revised article。

所以 publish 后 title 很可能被清空，但测试只检查：

```python
assert storage.meta.read(new_id).status == "published"
```

建议加：

```python
assert storage.meta.read(new_id).title == "A Great Paper"
```

并且 publish 应该基于当前 meta：

```python
current = storage.meta.read(new_id)
pub_meta = replace(current, status="published")
```

---

## 3. 异常测试应该用 `pytest.raises`

当前：

```python
try:
    execute(...)
    assert False
except BadRequestError:
    pass
```

建议：

```python
import pytest

with pytest.raises(BadRequestError):
    execute(...)
```

---

## 4. 没有测试 `Article.encode()` round-trip score

应该加：

```python
def test_article_encode_decode_preserves_score():
    a = Article(
        id=ArticleId(id="a1"),
        title="T",
        status="draft",
        score=Scores({"clarity": 4.0}),
    )

    b = Article.decode(a.encode())

    assert isinstance(b.score, Scores)
    assert b.score.get("clarity") == 4.0
```

这个测试目前应该会失败。

---

## 5. 没有测试多个 review 的 aggregate score

应该加：

```python
def test_multiple_reviews_update_aggregate_score():
    ...
```

目前这个会暴露 `create_review()` 只用最后一次 score 的问题。

---

## 6. 没有测试同一 reviewer review 多篇文章

应该加：

```python
def test_same_reviewer_can_review_multiple_articles():
    ...
```

目前 `MemReviewStorage` 会失败或覆盖。

---

## 7. `sync_article()` 没有真正被测

`test_sync_article()` 只是：

```python
v = sync.push(...)
assert sync.fetch_version(...)
```

没有调用：

```python
sync_article(...)
```

所以 `sync_article()` 里的复杂逻辑完全没被覆盖。

至少应该测：

1. local only -> push
2. remote only -> pull
3. same head -> no-op
4. local ahead -> push incremental
5. remote ahead -> pull incremental
6. diverged -> conflict or merge
7. no common ancestor -> conflict

---

# 建议的重构方向

我会建议你下一轮按下面顺序改。

---

## Step 1：先把 core 的数据模型打牢

优先修：

1. `Article.encode/decode`
2. `Scores` serialization
3. `Article.to_dict/from_dict`
4. `__all__`
5. `__future__`
6. `__init__`

并加 round-trip tests。

---

## Step 2：明确 SOT 写入 API

现在最大的架构矛盾是：

- 你说 git 是 SOT；
- 但 storage API 没有把 metadata、commit data、author、status transition 写进 git 的能力；
- reconcile 又声称从 git reconstruct metadata。

建议把 article write 设计成一个更完整的 object：

```python
@dataclass(frozen=True)
class ArticleWrite:
    article: Article
    content: str
    commit: CommitData
```

然后：

```python
class ArticleContentStorage(Protocol):
    def write_article(self, key: ArticleId, write: ArticleWrite) -> Version:
        ...
```

而不是：

```python
def update(self, key: ArticleId, content: str) -> Version:
```

这样 `extract()` 才真的有东西可提取。

---

## Step 3：review API 不要传 JSON string

把：

```python
scores_json: str
```

改成：

```python
scores: Scores
```

把 review body 改成明确参数：

```python
content: str
```

例如：

```python
def create_review(
    self,
    article_id: ArticleId,
    reviewer_id: UserId,
    scores: Scores,
    content: str,
    commit: CommitData,
) -> ReviewId:
    ...
```

JSON 是 backend adapter 的事情。

---

## Step 4：scoring engine 接入 `ArticleStorage`

让 article aggregate score 由 `ScoringEngine` 计算，而不是直接用单条 review。

---

## Step 5：sync protocol 重新设计

至少增加：

```python
def has_version(...) -> bool | None:
    ...
```

或：

```python
def fetch_history(...) -> list[Version]:
    ...
```

然后让 `sync_article()` 区分：

- local missing
- remote missing
- fast-forward
- local ahead
- diverged
- unrelated histories
- probe failure

并明确是否做 merge。如果不做，就抛 `MergeConflictError`。

---

# 一个比较干净的 review create/update 形状

你现在的 review path 可以收敛成这样：

```python
@dataclass(frozen=True)
class ReviewWrite:
    reviewer_id: UserId
    scores: Scores
    content: str
    scope: str = ""
    commit: CommitData | None = None
```

storage service：

```python
def create_review(self, article_id: ArticleId, write: ReviewWrite) -> ReviewId:
    self._review_content.create(article_id, write.reviewer_id)
    self._review_content.update_scores(article_id, write.reviewer_id, write.scores)
    self._review_content.append_thread_entry(
        article_id,
        write.reviewer_id,
        write.content,
        marker="[review]",
    )

    self._reconcile_reviews(article_id)
    self._update_article_score(article_id)

    return self._review_meta.read(article_id, write.reviewer_id).id
```

其中 `update_scores` 可以在 protocol 层接受 `Scores`，然后 backend 负责 JSON：

```python
class ReviewContentStorage(Protocol):
    def update_scores(
        self,
        article_id: ArticleId,
        reviewer_id: UserId,
        scores: Scores,
    ) -> Version:
        ...
```

这样 core 不再接触 JSON string。

---

# 最重要的测试清单

我建议你马上补这些测试：

```python
def test_article_score_serialization_roundtrip():
    ...
```

```python
def test_article_content_ref_set_after_create():
    ...
```

```python
def test_same_reviewer_reviews_two_articles():
    ...
```

```python
def test_two_reviews_aggregate_score():
    ...
```

```python
def test_review_article_id_mismatch_rejected():
    ...
```

```python
def test_update_review_reviewer_mismatch_rejected():
    ...
```

```python
def test_query_filters_status_search_limit_offset():
    ...
```

```python
def test_sync_article_remote_only_pulls():
    ...
```

```python
def test_sync_article_local_only_pushes():
    ...
```

```python
def test_sync_article_unrelated_histories_conflict():
    ...
```

---

# 最后总结

这个包的核心想法是好的：你已经把 PeerPedia 的几个关键抽象拆出来了：

- article metadata cache；
- git content SOT；
- review meta/content split；
- lifecycle morphism；
- scoring plugin；
- compiler plugin；
- sync protocol；
- auth protocol。

但是现在最大的问题是 **文档里的架构承诺比代码实际保证的东西更强**。尤其是：

1. 说 canonical JSON，但 serialization 不 canonical，也不能正确 round-trip。
2. 说 git 是 source of truth，但 write API 没有足够信息写入 git。
3. 说 review aggregate score，但实际只保存最后一条 review score。
4. 说 three-way merge sync，但 sync protocol 没有真正的 version-presence probe，也没有真正 merge/conflict 语义。
5. 说 auth 是 TOFU，但没有 trust pinning。
6. 说 clean architecture，但 storage protocol 层里混了不少 use-case logic。

我的建议是：**先不要继续扩展功能**，先把 Article serialization、review scoring、SOT write API、sync semantics 这四块打牢。否则后面 backend 一接 git/DB/HTTP，就会出现大量“protocol 看起来对，但实现不知道该怎么满足”的问题。