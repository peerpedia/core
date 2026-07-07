# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""PeerPedia Core — engine protocols, types, and exceptions.

Zero dependencies.  No IO.  All other PeerPedia packages depend on this one.
"""

from peerpedia_core.peerpedia import Peerpedia

__all__ = ["Peerpedia"]
