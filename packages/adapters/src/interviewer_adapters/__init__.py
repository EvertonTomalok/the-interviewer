"""Adapter registration root.

Every adapter module registers its ``ProviderSpec`` at import time. Importing
this package (or any name below) must therefore import every adapter module so
that no caller has to remember which providers exist -- the registry is
populated as a side effect of import, once, here.

Each wave appends its own import at the end of this file. Never reorder the
existing lines -- a merge conflict here resolves by keeping both sides.
"""

from __future__ import annotations

__version__ = "0.1.0"

from interviewer_adapters import llm  # noqa: E402, F401  -- registers LLM providers (T03)
