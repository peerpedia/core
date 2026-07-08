# SPDX-FileCopyrightText: 2024-2026 Chenqi Meng and PeerPedia contributors
# SPDX-License-Identifier: AGPL-3.0

"""Compiler protocol — render article content to output formats."""

from __future__ import annotations

__all__ = ["Compiler"]

from typing import Protocol


class Compiler(Protocol):
    """Compile article content to an output format.

    The core does not know what formats are available — that is a
    plugin concern (``"html"``, ``"pdf"``, ``"latex"``, etc.).

    ::

        compiler.compile("# Title\n\nHello", "html")
        → b"<h1>Title</h1>..."
    """

    def compile(self, content: str, fmt: str) -> bytes:
        """Compile *content* to *fmt*, returning rendered bytes."""
        ...
