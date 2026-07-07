# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Abstract query types — storage-agnostic, no IO.

Storage backends translate these into their native query language
(SQL, filesystem globs, API calls).  Fields are optional and AND-ed
together.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ArticleQuery:
    """Filter conditions for listing articles.

    All fields are optional AND-ed together.  An empty query returns
    recent articles.  Each storage backend translates this into its
    native query mechanism.

    Examples::

        ArticleQuery()                                          # all, recent first
        ArticleQuery(statuses={"published", "sedimentation"})   # multiple statuses
        ArticleQuery(search="quantum")                          # full-text search
        ArticleQuery(statuses={"published"}, search="gravity", limit=10)
    """

    statuses: frozenset[str] | None = None
    """Filter by status values (OR within set, AND with other filters)."""

    search: str | None = None
    """Case-insensitive substring match in title and abstract."""

    id_prefix: str | None = None
    """Filter articles whose ID starts with this prefix."""

    limit: int | None = None
    """Max results to return."""

    offset: int = 0
    """Results offset for pagination."""
