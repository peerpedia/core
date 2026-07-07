# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""P2P sync protocols — transport-agnostic.

Core does not know whether sync travels over HTTP, gRPC, or smoke signals.
It only knows this interface.  Each transport backend implements these
protocols.

Serialization lives on the entity types: ``Article.encode()`` /
``Article.decode()``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TYPE_CHECKING

from peerpedia_core.types.entities import ArticleId, UserId, Version

if TYPE_CHECKING:
    from peerpedia_core.protocols.storage import ArticleStorage


# ── Monotonic boundary search ─────────────────────────────────────────────


def search_monotonic_boundary(
    probe: Callable[[int], bool | None],
    max_idx: int,
    k: int = 5,
) -> int | None:
    """k-exponential search for the first index where *probe* returns False.

    The predicate is monotonic: *probe(i)* is True for all i < boundary,
    and False for all i >= boundary.  Returns the boundary index, or
    *max_idx*+1 if all True, or ``None`` on probe failure.

    This is a generic algorithm — no domain-specific types.  Use it to
    build higher-level merge-base or bisect functions.
    """
    if max_idx < 0:
        return None

    # ── Exponential phase — find an upper bound where probe fails ──
    upper = 1
    while upper <= max_idx:
        r = probe(upper)
        if r is True:
            upper *= k
        elif r is False:
            break
        else:
            return None
    # All probes succeeded — boundary is beyond max_idx
    if upper > max_idx:
        upper = max_idx
        if probe(upper) is True:
            return max_idx + 1

    # ── Binary refinement ──
    lower = upper // k
    while lower + 1 < upper:
        mid = (lower + upper) // 2
        r = probe(mid)
        if r is True:
            lower = mid
        elif r is False:
            upper = mid
        else:
            return None
    return upper


# ── Merge-base search ─────────────────────────────────────────────────────


def find_merge_base(
    local_versions: list[Version],
    probe: Callable[[Version], bool | None],
    k: int = 5,
) -> Version | None:
    """Find the newest version shared by local and remote.

    *local_versions* is ordered newest-first (from ``history()``).
    Built on ``search_monotonic_boundary``.

    The monotonic property: "once a version is present on remote, all
    older versions are also present".  So *probe(v)* returning False
    is the "still missing" phase, and True is "present from here on".
    """
    n = len(local_versions)
    if n == 0:
        return None

    # Skip past versions remote doesn't have (local ahead of remote).
    while n > 0:
        r = probe(local_versions[0])
        if r is None:
            return None
        if r:
            break
        local_versions = local_versions[1:]
        n -= 1
    if n == 0:
        return None  # no common ancestor

    # Now local_versions[0] IS on remote.  Use the monotonic search from
    # here: True (present) → False (missing) as index increases.
    def _present(i: int) -> bool | None:
        return probe(local_versions[i])

    boundary = search_monotonic_boundary(_present, n - 1, k=k)
    if boundary is None:
        return None
    if boundary > n - 1:
        return local_versions[0]            # all present — newest is merge base
    if boundary == 0:
        return None                         # first probe after skip failed
    return local_versions[boundary - 1]     # just before first missing


# ── ArticleSync protocol ──────────────────────────────────────────────────


class ArticleSync(Protocol):
    """Bi-directional article sync between peers.

    *since* is a content version for incremental sync (``None`` = full pull).
    """

    def fetch_version(
        self, peer_url: str, article_id: ArticleId
    ) -> Version | None:
        """Get the HEAD version from *peer_url* (ultra-light probe)."""
        ...

    def push(
        self,
        peer_url: str,
        article_id: ArticleId,
        data: bytes,
        since: Version | None = None,
    ) -> Version:
        """Push *data* to *peer_url*.  *since* is the base version;
        returns the new version assigned by the receiver."""
        ...

    def pull_meta(
        self,
        peer_url: str,
        article_id: ArticleId,
        since: Version | None = None,
    ) -> bytes | None:
        """Pull metadata only from *peer_url*."""
        ...

    def pull_all(
        self,
        peer_url: str,
        article_id: ArticleId,
        since: Version | None = None,
    ) -> bytes | None:
        """Pull full article (meta + content) from *peer_url*."""
        ...


# ── ReviewSync protocol ───────────────────────────────────────────────────


class ReviewSync(Protocol):
    """Bi-directional review sync between peers.

    Reviews are synced per article — *article_id* scopes the reviews
    being pushed or pulled.
    """

    def push(
        self,
        peer_url: str,
        article_id: ArticleId,
        reviewer_id: UserId,
        data: bytes,
        since: Version | None = None,
    ) -> Version:
        """Push review *data* to *peer_url*."""
        ...

    def pull(
        self,
        peer_url: str,
        article_id: ArticleId,
        reviewer_id: UserId,
        since: Version | None = None,
    ) -> bytes | None:
        """Pull review data from *peer_url*."""
        ...


# ── Sync orchestrator ─────────────────────────────────────────────────────


def sync_article(
    sync: ArticleSync,
    storage: ArticleStorage,
    article_id: ArticleId,
    peer_url: str,
) -> Version:
    """Sync *article_id* with *peer_url* — three-way merge.

    Returns the new local HEAD version after sync.  Composes
    ``ArticleSync`` + ``ArticleContentStorage`` + ``reconcile``.
    """
    content = storage.get_content(article_id)
    local_history = content.history(article_id)
    local_head = local_history[0].version if local_history else None

    # ── Probe remote ──
    remote_head = sync.fetch_version(peer_url, article_id)
    if remote_head is None:
        # Remote doesn't have this article — push everything
        if local_head:
            bundle = content.create_bundle(article_id, since=None)
            return sync.push(peer_url, article_id, bundle)
        raise ValueError("sync_article: no local or remote content")

    if local_head and local_head.id == remote_head.id:
        return local_head  # already in sync

    # ── Find merge base ──
    def _probe(v: Version) -> bool | None:
        return sync.pull_all(peer_url, article_id, since=v) is not None

    merge_base = find_merge_base(
        [e.version for e in local_history], _probe,
    )

    # ── Three-way decision ──
    if merge_base is None or merge_base.id == local_head.id if local_head else False:
        # Local behind — pull remote
        bundle = sync.pull_all(peer_url, article_id, since=local_head)
        if bundle:
            new_head = content.ingest_bundle(article_id, bundle)
            from peerpedia_core.protocols.storage import reconcile
            reconcile(storage, article_id)
            return new_head
    elif merge_base.id == remote_head.id:
        # Local ahead — push
        if local_head:
            bundle = content.create_bundle(article_id, since=remote_head)
            return sync.push(peer_url, article_id, bundle, since=remote_head)
    else:
        # Diverged — pull remote, local stays on top
        bundle = sync.pull_all(peer_url, article_id, since=merge_base)
        if bundle:
            content.ingest_bundle(article_id, bundle)
            from peerpedia_core.protocols.storage import reconcile
            reconcile(storage, article_id)
    return local_head or Version(id="unknown")


