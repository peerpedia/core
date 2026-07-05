# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Engine protocols — interfaces the core understands.

Each protocol is a ``typing.Protocol`` — no implementation, just
structural contracts.  Plugins in other packages implement these.
"""

from peerpedia_core.protocols.lifecycle import Lifecycle
from peerpedia_core.protocols.storage import ArticleStorage
from peerpedia_core.protocols.scoring import ScoringEngine

__all__ = ["Lifecycle", "ArticleStorage", "ScoringEngine"]
