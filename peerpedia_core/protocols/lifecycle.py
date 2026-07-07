# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Lifecycle protocol — the morphism plugin.

The core engine pipeline for every article action::

    action: str, extra: Extra, context: ArticleId | None
        -> lifecycle.actions must include action          // universal or plugin-defined
        -> lifecycle.compatible(action, context, extra)   // domain check
        -> evaluate = lifecycle.resolve(action)           // pick the morphism
        -> evaluate(extra, context)                       // reduction -> new ArticleId

CLI, REPL, and server never hardcode allowed transitions.
They inject a Lifecycle plugin and let ``execute()`` do the work.

Universal actions
-----------------
Every Lifecycle MUST support these five morphisms::

    create    — persist a new article (meta + content)
    revise    — update an existing article
    publish   — make public
    delete    — remove / archive
    review    — create a peer review on the article
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TYPE_CHECKING

from peerpedia_core.exceptions import BadRequestError, ConflictError
from peerpedia_core.types.entities import Article, ArticleId

if TYPE_CHECKING:
    from peerpedia_core.protocols.storage import ArticleStorage

# ── Universal actions ───────────────────────────────────────────────────────
# Every Lifecycle plugin MUST support these.

_UNIVERSAL_ACTIONS: frozenset[str] = frozenset(
    {"create", "revise", "publish", "delete", "review"}
)

# ── Types ───────────────────────────────────────────────────────────────────

# Extra data injected for this operation (content body, metadata delta, etc.).
Extra = dict[str, object]

# Evaluation = morphism reduction: extra * context -> new context.
# *context* is ``None`` for the ``create`` action (no pre-existing article).
Evaluation = Callable[[Extra, ArticleId | None], ArticleId]


# ── Universal action implementations ───────────────────────────────────────


def action_publish(
    article_id: ArticleId, article: Article, storage: ArticleStorage,
) -> None:
    """Publish an article — update meta status, then reconcile from SOT.

    *publish* is a business-level status transition, not a storage
    primitive.  It exists here because "publishing" is a PeerPedia
    lifecycle concept, not a universal storage operation.
    """
    storage.meta.update(article_id, article)
    storage.reconcile_article(article_id)


# ── Lifecycle protocol ─────────────────────────────────────────────────────


class Lifecycle(Protocol):
    """A set of named actions (morphisms) with domain-compatibility rules.

    The ``actions`` property MUST include all universal actions
    (``create``, ``revise``, ``publish``, ``delete``, ``review``)
    plus any plugin-specific extensions.

    Each plugin decides, for a given ``(action, context, extra)``,
    whether the morphism applies via ``compatible()``.

    ``resolve()`` returns an ``Evaluation`` — callers have already
    checked ``compatible()``.
    """

    @property
    def actions(self) -> frozenset[str]:
        """All valid action names — universal actions + plugin extensions."""
        ...

    def compatible(
        self, action: str, context: ArticleId | None, extra: Extra
    ) -> bool:
        """Return True if *action* can apply to *context* with *extra*."""
        ...

    def resolve(self, action: str) -> Evaluation:
        """Return the evaluation function for *action*.

        The caller MUST have already checked ``compatible()``.
        """
        ...


# ── Dispatcher ──────────────────────────────────────────────────────────────


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
    # Universal invariant: create has no context; all others must have one
    if action == "create" and context is not None:
        raise BadRequestError(
            f"Action 'create' must have context=None, got {context!r}",
            field="context", bad_value=str(context),
        )
    if action != "create" and context is None:
        raise BadRequestError(
            f"Action '{action}' requires a context (article id), got None",
            field="context", bad_value="None",
        )
    if not lifecycle.compatible(action, context, extra):
        raise ConflictError(
            f"Action '{action}' is not compatible with the current context",
            conflicting_entity=action,
        )
    evaluate = lifecycle.resolve(action)
    return evaluate(extra, context)
