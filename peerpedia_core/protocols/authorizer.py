# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Authorizer protocol — permission checks.

Separated from Lifecycle because authorization (who are you?)
and state transitions (what status is this article in?) are
independent concerns.  Some actions don't need auth at all
(e.g. reading a published article).
"""

from __future__ import annotations

__all__ = ["Authorizer"]

from typing import Protocol

from peerpedia_core.types.entities import Article, User


class Authorizer(Protocol):
    """Decide whether *user* may perform *action* on *article*.

    Handlers call this BEFORE ``execute()`` — a failed auth check
    never reaches the lifecycle state machine.
    """

    def authorize(self, user: User, article: Article, action: str) -> bool:
        """Return True if *user* is allowed to perform *action*.

        The authorizer may inspect user identity, article ownership,
        maintainer status, or any other factor.  It does NOT inspect
        the article's lifecycle status — that is the lifecycle's job.
        """
        ...
