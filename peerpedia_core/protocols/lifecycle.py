# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Lifecycle protocol — the morphism plugin.

The core engine pipeline for every article action::

    action: str, extra: Extra, context: ArticleId
        -> lifecycle.actions must include action          // universal or plugin-defined
        -> lifecycle.compatible(action, context, extra)   // domain check
        -> evaluate = lifecycle.resolve(action)           // pick the morphism
        -> evaluate(extra, context)                       // reduction → new ArticleId

CLI, REPL, and server never hardcode allowed transitions.
They inject a Lifecycle plugin and let compose check do the work.

Universal actions
-----------------
Every Lifecycle MUST implement these five morphisms::

    create    — persist a new article (meta + content_ref)
    revise    — update an existing article
    publish   — make public
    delete    — remove / archive
    review    — create a peer review on the article
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TYPE_CHECKING

from peerpedia_core.exceptions import BadRequestError, ConflictError
from peerpedia_core.types.entities import Article, ArticleId, Format, Review

from peerpedia_core.protocols.storage import reconcile

if TYPE_CHECKING:
    from peerpedia_core.protocols.storage import ArticleStorage

# ── Universal actions ───────────────────────────────────────────────────────
# Every Lifecycle plugin MUST support these.

_UNIVERSAL_ACTIONS: frozenset[str] = frozenset({"create", "revise", "publish", "delete", "review"})

# ── Types ───────────────────────────────────────────────────────────────────

# Extra data injected for this operation (content from vim, metadata delta, etc.).
Extra = dict[str, object]

# Evaluation = morphism reduction: extra × context → new context.
# *context* is ``None`` for the ``create`` action (no pre-existing article).
#
# The action_* functions below take ``(extra, context, storage)`` — a
# plugin wraps them to match this signature::
#
#     lambda e, c: action_revise(e, c, self.storage)
Evaluation = Callable[[Extra, ArticleId | None], ArticleId]


# ── Universal action implementations ─────────────────────────────────────────


def _require(extra: Extra, key: str, expected_type: type) -> object:
    """Extract *key* from *extra* with a friendly error on mismatch."""
    try:
        value = extra[key]
    except KeyError:
        raise BadRequestError(
            f"Missing required key {key!r} in extra",
            field=key,
        ) from None
    if not isinstance(value, expected_type):
        raise BadRequestError(
            f"Expected {key!r} to be {expected_type.__name__}, got {type(value).__name__}",
            field=key,
            bad_value=str(type(value)),
        )
    return value


def action_create(
    extra: Extra, context: ArticleId | None, storage: ArticleStorage
) -> ArticleId:
    """Create a new article — allocate meta, init content, reconcile.

    *extra* and *context* are unused — the id is allocated by meta
    storage.  Plugins wrap this to match ``Evaluation``::

        lambda e, c: action_create(e, c, self.storage)
    """
    article_id = storage.get_meta(None).create()          # allocates id
    storage.get_content(article_id).create(article_id, Format(name="markdown"))
    reconcile(storage, article_id)
    return article_id


def action_revise(
    extra: Extra, context: ArticleId, storage: ArticleStorage
) -> ArticleId:
    """Revise an existing article — update content + meta, then reconcile.

    *extra* must contain ``"content"`` (str) and ``"article"`` (Article).
    """
    content: str = _require(extra, "content", str)       # type: ignore[assignment]
    article: Article = _require(extra, "article", Article)  # type: ignore[assignment]
    storage.get_content(context).update(context, content)
    storage.get_meta(context).update(context, article)
    reconcile(storage, context)
    return context


def action_publish(
    extra: Extra, context: ArticleId, storage: ArticleStorage
) -> ArticleId:
    """Publish an article — update meta status, then reconcile.

    *extra* must contain ``"article"`` (Article) with the new status.
    """
    article: Article = _require(extra, "article", Article)  # type: ignore[assignment]
    storage.get_meta(context).update(context, article)
    reconcile(storage, context)
    return context


def action_delete(
    extra: Extra, context: ArticleId, storage: ArticleStorage
) -> ArticleId:
    """Delete an article — remove meta and content."""
    storage.get_meta(context).delete(context)
    storage.get_content(context).delete(context)
    return context


def action_review(
    extra: Extra, context: ArticleId, storage: ArticleStorage,
) -> ArticleId:
    """Submit a peer review on *context*.

    *extra* must contain ``"review"`` (Review) with ``article_id``
    matching *context*.
    """
    review: Review = _require(extra, "review", Review)  # type: ignore[assignment]
    if review.article_id != context:
        raise BadRequestError(
            f"Review article_id {review.article_id.id!r} does not match context {context.id!r}",
            field="review.article_id",
            bad_value=review.article_id.id,
        )
    rstore = storage.get_review(context)
    rstore.create(context, review.reviewer_id)
    rstore.update(context, review.reviewer_id, review)
    return context


# ── Lifecycle protocol ───────────────────────────────────────────────────────


class Lifecycle(Protocol):
    """A set of named actions (morphisms) with domain-compatibility rules.

    The ``actions`` property MUST include all universal actions
    (``create``, ``revise``, ``publish``, ``delete``, ``review``)
    plus any plugin-specific extensions.

    Each plugin decides, for a given ``(action, context, extra)``,
    whether the morphism applies via ``compatible()``.
    """

    @property
    def actions(self) -> frozenset[str]:
        """All valid action names — universal actions + plugin extensions."""
        ...

    def compatible(
        self, action: str, context: ArticleId, extra: Extra
    ) -> bool:
        """Return True if *action* can apply to *context* with *extra*.

        Domain check — the morphism's source must match the object.
        Implementations may inspect the article's status, extra shape,
        or any other factor.
        """
        ...

    def resolve(self, action: str) -> Evaluation:
        """Return the evaluation function for *action*.

        The caller MUST have already checked ``compatible()``.
        """
        ...


def execute(
    action: str,
    extra: Extra,
    context: ArticleId | None,
    lifecycle: Lifecycle,
) -> ArticleId:
    """Reduce *action* against *extra* and *context* through *lifecycle*.

    *context* is ``None`` for ``create`` — there is no pre-existing article.

    ::

        new_id = execute("create", {}, None, lifecycle)
        new_id = execute("publish", {}, new_id, lifecycle)
    """
    if action not in lifecycle.actions:
        raise BadRequestError(
            f"Unknown action '{action}'",
            field="action",
            bad_value=action,
        )
    if not lifecycle.compatible(action, context, extra):
        raise ConflictError(
            f"Action '{action}' is not compatible with the current context",
            conflicting_entity=action,
        )
    evaluate = lifecycle.resolve(action)
    return evaluate(extra, context)
