# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Score abstraction — a set of named dimensions with float values.

Dimension names are NOT hardcoded here.  The scoring plugin defines
which dimensions exist (e.g. five dimensions, three dimensions, etc.).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Scores:
    """A multi-dimensional score with named dimensions.

    >>> s = Scores(dimensions={"originality": 4.0, "rigor": 3.5})
    >>> s.average()
    3.75
    """

    dimensions: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "dimensions", dict(self.dimensions))

    def average(self) -> float:
        if not self.dimensions:
            return 0.0
        return sum(self.dimensions.values()) / len(self.dimensions)

    def get(self, dim: str, default: float = 0.0) -> float:
        return self.dimensions.get(dim, default)
