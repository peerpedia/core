# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Lifecycle protocol — the state-machine plugin.

The core engine pipeline for every article action::

    user: User, action_name: str, article: Article
        -> authorizer.authorize(user, article, action_name)   // are you allowed?
        -> s = article.status
        -> next = lifecycle.next_step(action_name, s)          // does state allow?
        -> next(article, user)                                 // execute

CLI, REPL, and server never hardcode status names or allowed
transitions.  They inject Authorizer and Lifecycle plugins and
let the protocols decide.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol

from peerpedia_core.types.entities import Article, User

# An operation on an article: takes article + user + kwargs, returns article.
ArticleAction = Callable[[Article, User, dict[str, Any]], Article]


class Lifecycle(Protocol):
    """A state machine governing what actions an article may undergo.

    Each lifecycle implementation (jury, bazaar, editorial) defines its
    own states and transition rules.  The core engine does not know or
    care what states exist.
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
        """Return the action function for *action_name* from *status*.

        Returns ``None`` when the action is not allowed in this state.
        """
        ...


def execute(
    user: User,
    action_name: str,
    article: Article,
    lifecycle: Lifecycle,
    **kwargs: Any,
) -> Article:
    """Execute an article action through the lifecycle plugin.

    Authorization must already have been performed by the handler
    using an :class:`Authorizer`.  This function only checks whether
    the lifecycle state permits the action, then executes it::

        article = execute(user, "publish", article, lifecycle, db=db, path=rp)
    """
    action = lifecycle.next_step(action_name, article.status)
    if action is None:
        from peerpedia_core.exceptions import ConflictError
        raise ConflictError(
            f"Action '{action_name}' is not allowed in status '{article.status}'",
            conflicting_entity=action_name,
        )
    return action(article, user, kwargs)
