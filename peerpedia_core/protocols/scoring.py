# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""ScoringEngine protocol — the scoring plugin.

Core does not define what dimensions exist or how scores are aggregated.
The scoring plugin (in peerpedia-compute) implements this.
"""

from __future__ import annotations

from typing import Protocol

from peerpedia_core.types.entities import Review
from peerpedia_core.types.scores import Scores


class ScoringEngine(Protocol):
    """Compute aggregate scores from a collection of reviews."""

    def compute(self, reviews: list[Review]) -> Scores:
        """Aggregate *reviews* into a single Scores value."""
        ...
