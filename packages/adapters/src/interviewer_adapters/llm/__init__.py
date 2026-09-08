"""LLM adapters: importing this package registers every LLM provider.

Add a provider -> one new module here, self-registering a `ProviderSpec` at
import time (see `openrouter.py`), plus one import line appended below.
Never add a branch to a factory; the registry is the dispatch.
"""

from __future__ import annotations

from interviewer_adapters.llm import fake, openai_compat, openrouter  # noqa: F401
