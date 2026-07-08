# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Lifecycle protocol — the morphism plugin.

The core engine pipeline for every article action::

    action: str, extra: Extra, context: ArticleId | None
        -> lifecycle.actions must include action          // universal or plugin-defined
        -> evaluate = lifecycle.resolve(action)           // pick the morphism (raises if incompatible)
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

__all__ = [
    "Extra",
    "Evaluation",
    "Lifecycle",
    "action_publish",
    "execute",
]

from collections.abc import Callable
from typing import Protocol, TYPE_CHECKING

from peerpedia_core.exceptions import BadRequestError
from peerpedia_core.types.entities import Article, ArticleId

if TYPE_CHECKING:
    from peerpedia_core.protocols.storage import ArticleStorage

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
    """A set of named actions (morphisms) for article lifecycle.

    The ``actions`` property MUST include::

        "create", "revise", "publish", "delete", "review"

    plus any plugin-specific extensions.  ``resolve()`` returns an
    ``Evaluation``.  If the action is incompatible with the current
    context, ``resolve()`` raises ``ConflictError``.
    """

    @property
    def actions(self) -> frozenset[str]:
        """All valid action names — universal actions + plugin extensions."""
        ...

    def resolve(self, action: str) -> Evaluation:
        """Return the evaluation function for *action*.

        Raise ``ConflictError`` if the action is not compatible.
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
    evaluate = lifecycle.resolve(action)
    return evaluate(extra, context)
