# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Engine protocols — interfaces the core understands.

Each protocol is a ``typing.Protocol`` — no implementation, just
structural contracts.  Plugins in other packages implement these.
"""

from peerpedia_core.protocols.auth import AuthProvider, AuthResult
from peerpedia_core.protocols.authorizer import Authorizer
from peerpedia_core.protocols.compiler import Compiler
from peerpedia_core.protocols.lifecycle import Lifecycle
from peerpedia_core.protocols.review_content_storage import ReviewContentStorage
from peerpedia_core.protocols.review_meta_storage import ReviewMetaStorage
from peerpedia_core.protocols.scoring import ScoringEngine
from peerpedia_core.protocols.storage import (
    ArticleContentStorage,
    ArticleMetaStorage,
    ArticleStorage,
)
from peerpedia_core.protocols.sync import ArticleSync, ReviewSync
from peerpedia_core.protocols.user_storage import UserStorage

__all__ = [
    "ArticleContentStorage",
    "ArticleMetaStorage",
    "ArticleStorage",
    "ArticleSync",
    "ReviewSync",
    "AuthProvider",
    "AuthResult",
    "Authorizer",
    "Compiler",
    "Lifecycle",
    "ReviewContentStorage",
    "ReviewMetaStorage",
    "ScoringEngine",
    "UserStorage",
]
