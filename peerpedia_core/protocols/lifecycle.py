# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Lifecycle protocol — the state-machine plugin.

The core engine knows this pattern::

    article_action: Callable, article: Article
        -> s = get_status(article)
        -> next = lifecycle.next_step(article_action, s)
        -> next(article)

CLI, REPL, and server never hardcode status names or allowed transitions.
They call ``execute(action_name, article, lifecycle)`` and the lifecycle
plugin decides what is permitted.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol

from peerpedia_core.types.entities import Article

# An operation that can be performed on an article.
ArticleAction = Callable[[Article, dict[str, Any]], Article]


class Lifecycle(Protocol):
    """A state machine governing what actions an article may undergo.

    Each lifecycle implementation (jury, bazaar, editorial) defines its
    own states and transition rules.  The core engine does not know or
    care what states exist — it only calls ``execute``.
    """

    @property
    def states(self) -> tuple[str, ...]:
        """All valid status values defined by this lifecycle."""
        ...

    @property
    def initial_state(self) -> str:
        """The status assigned to a newly created article."""
        ...

    def next_step(
        self, action_name: str, status: str
    ) -> ArticleAction | None:
        """Return the function to execute for *action_name* from *status*.

        Returns ``None`` when the action is not allowed in this state.
        """
        ...


def execute(
    action_name: str,
    article: Article,
    lifecycle: Lifecycle,
    **kwargs: Any,
) -> Article:
    """Resolve and execute an action through the lifecycle plugin.

    This is the single entry point for all article operations.  CLI and
    server handlers call this instead of hardcoding status checks::

        article = execute("publish", article, lifecycle, db=db, path=rp)
    """
    action = lifecycle.next_step(action_name, article.status)
    if action is None:
        from peerpedia_core.exceptions import NotAuthorizedError
        raise NotAuthorizedError(
            f"Action '{action_name}' is not allowed in status '{article.status}'",
            permission=action_name,
            resource_type="article",
            resource_id=article.id,
        )
    return action(article, kwargs)
