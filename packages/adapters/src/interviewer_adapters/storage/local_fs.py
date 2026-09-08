"""`STORAGE_PROVIDER=local_fs`: a directory on disk. `signed_url` is a
short-lived HMAC token the API validates itself, since there is no cloud
signer to ask."""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from pathlib import Path

from interviewer_core.config import Settings
from interviewer_core.errors import PortError
from interviewer_core.ports.storage import BlobStore
from interviewer_core.registry import ProviderSpec, register


@dataclass
class LocalFsBlobStore:
    root: Path
    secret: str = "local-fs-dev-secret"

    def __post_init__(self) -> None:
        self.root = self.root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    async def put(self, key: str, content: bytes, *, mime: str) -> str:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return f"local_fs://{key}"

    async def get(self, uri: str) -> bytes:
        key = _strip_scheme(uri)
        path = self._resolve(key)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise PortError(f"no blob at {uri!r}", transient=False, status=404) from exc

    def _resolve(self, key: str) -> Path:
        """Join `key` onto `root`, refusing anything that would escape it.

        `Path(root) / "/etc/passwd"` silently discards `root` in pathlib, and
        `..` segments walk back out of it -- both are a path-traversal write
        or read if the key comes from a caller. `key` is always an artifact
        id, never user-supplied text, but this stays a hard boundary, not a
        trust call.
        """
        candidate = (self.root / key).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise PortError(
                f"blob key {key!r} escapes the storage root", transient=False, status=400
            )
        return candidate

    async def signed_url(self, uri: str, *, expires_in_seconds: int) -> str:
        key = _strip_scheme(uri)
        expires_at = int(time.time()) + expires_in_seconds
        signature = self._sign(key, expires_at)
        return f"/blobs/{key}?expires={expires_at}&sig={signature}"

    def verify(self, key: str, *, expires_at: int, signature: str) -> bool:
        if int(time.time()) > expires_at:
            return False
        return hmac.compare_digest(self._sign(key, expires_at), signature)

    def _sign(self, key: str, expires_at: int) -> str:
        message = f"{key}:{expires_at}".encode()
        return hmac.new(self.secret.encode(), message, hashlib.sha256).hexdigest()


def _strip_scheme(uri: str) -> str:
    return uri.removeprefix("local_fs://")


def _build(settings: Settings) -> BlobStore:
    return LocalFsBlobStore(root=Path(settings.storage.local_fs.root))


register(ProviderSpec(kind="storage", name="local_fs", build=_build, label="Local filesystem"))
