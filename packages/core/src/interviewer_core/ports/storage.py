from __future__ import annotations

from typing import Protocol


class BlobStore(Protocol):
    async def put(self, key: str, content: bytes, *, mime: str) -> str:
        """Store `content` under `key`; return the uri other methods take."""
        ...

    async def get(self, uri: str) -> bytes: ...

    async def signed_url(self, uri: str, *, expires_in_seconds: int) -> str: ...
