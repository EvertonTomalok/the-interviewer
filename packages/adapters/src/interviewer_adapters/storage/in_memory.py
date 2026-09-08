"""Dict-backed twin of `BlobStore` -- same port, same semantics as `local_fs`,
including the id-derived key. This is what every other lane's unit suite
stores audio through."""

from __future__ import annotations

import hashlib
import hmac
import time

from interviewer_core.errors import PortError


class InMemoryBlobStore:
    def __init__(self, *, secret: str = "in-memory-dev-secret") -> None:
        self._blobs: dict[str, tuple[bytes, str]] = {}
        self._secret = secret

    async def put(self, key: str, content: bytes, *, mime: str) -> str:
        self._blobs[key] = (content, mime)
        return f"memory://{key}"

    async def get(self, uri: str) -> bytes:
        key = uri.removeprefix("memory://")
        if key not in self._blobs:
            raise PortError(f"no blob at {uri!r}", transient=False, status=404)
        return self._blobs[key][0]

    async def signed_url(self, uri: str, *, expires_in_seconds: int) -> str:
        key = uri.removeprefix("memory://")
        expires_at = int(time.time()) + expires_in_seconds
        signature = self._sign(key, expires_at)
        return f"/blobs/{key}?expires={expires_at}&sig={signature}"

    def verify(self, key: str, *, expires_at: int, signature: str) -> bool:
        if int(time.time()) > expires_at:
            return False
        return hmac.compare_digest(self._sign(key, expires_at), signature)

    def _sign(self, key: str, expires_at: int) -> str:
        message = f"{key}:{expires_at}".encode()
        return hmac.new(self._secret.encode(), message, hashlib.sha256).hexdigest()
