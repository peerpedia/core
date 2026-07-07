# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""User storage protocol — CRUD for peer identities."""

from __future__ import annotations

from typing import Protocol

from peerpedia_core.types.entities import User, UserId


class UserStorage(Protocol):
    """CRUD for users — peer identities in the network.

    Matches the pattern of ``ArticleMetaStorage``: ``create()``
    allocates an id, ``update()`` fills in the data.
    """

    def create(self) -> UserId:
        """Allocate a new user id."""
        ...

    def read(self, key: UserId) -> User:
        """Return the user for *key*."""
        ...

    def update(self, key: UserId, user: User) -> None:
        """Replace the user record for *key*."""
        ...

    def delete(self, key: UserId) -> None:
        """Remove a user."""
        ...

    def search(self, query: str) -> list[User]:
        """Full-text search by name."""
        ...

    def list(self) -> list[User]:
        """Return all active users."""
        ...
