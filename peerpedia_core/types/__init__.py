# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Shared types — pure, no IO."""

from peerpedia_core.types.entities import Article, Review, User
from peerpedia_core.types.scores import Scores

__all__ = ["Article", "Review", "User", "Scores"]
