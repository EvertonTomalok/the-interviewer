from __future__ import annotations

from interviewer_adapters.storage import local_fs  # noqa: F401  -- registers providers
from interviewer_adapters.storage.in_memory import InMemoryBlobStore

__all__ = ["InMemoryBlobStore"]
