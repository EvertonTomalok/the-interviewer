from __future__ import annotations

from pathlib import Path

import pytest

from interviewer_adapters.storage.local_fs import LocalFsBlobStore
from interviewer_adapters.storage.local_fs import _build as build_storage
from interviewer_core.config import Settings
from interviewer_core.errors import PortError


async def test_put_get_round_trip(tmp_path: Path) -> None:
    store = LocalFsBlobStore(root=tmp_path)
    uri = await store.put("sessions/s1/turn-0.wav", b"audio-bytes", mime="audio/wav")
    assert uri == "local_fs://sessions/s1/turn-0.wav"
    assert await store.get(uri) == b"audio-bytes"


async def test_get_missing_raises_port_error(tmp_path: Path) -> None:
    store = LocalFsBlobStore(root=tmp_path)
    with pytest.raises(PortError):
        await store.get("local_fs://missing.wav")


async def test_signed_url_verifies_and_expires(tmp_path: Path) -> None:
    store = LocalFsBlobStore(root=tmp_path)
    await store.put("a.wav", b"x", mime="audio/wav")

    url = await store.signed_url("local_fs://a.wav", expires_in_seconds=60)
    query = url.split("?", 1)[1]
    params = dict(p.split("=") for p in query.split("&"))

    assert store.verify("a.wav", expires_at=int(params["expires"]), signature=params["sig"])
    assert not store.verify("a.wav", expires_at=int(params["expires"]), signature="bad")
    assert not store.verify("a.wav", expires_at=0, signature=params["sig"])


def test_build_reads_root_from_settings(tmp_path: Path) -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://x/db",
        redis_url="redis://localhost:6379/0",
    )
    settings.storage.local_fs.root = str(tmp_path / "blobs")

    store = build_storage(settings)

    assert isinstance(store, LocalFsBlobStore)
    assert store.root == (tmp_path / "blobs").resolve()


async def test_put_rejects_key_that_escapes_root_via_dotdot(tmp_path: Path) -> None:
    store = LocalFsBlobStore(root=tmp_path / "root")
    with pytest.raises(PortError):
        await store.put("../../etc/passwd", b"pwned", mime="text/plain")


async def test_put_rejects_absolute_key(tmp_path: Path) -> None:
    store = LocalFsBlobStore(root=tmp_path / "root")
    outside = tmp_path / "outside.wav"
    with pytest.raises(PortError):
        await store.put(str(outside), b"pwned", mime="audio/wav")
    assert not outside.exists()


async def test_get_rejects_key_that_escapes_root(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret")
    store = LocalFsBlobStore(root=tmp_path / "root")

    with pytest.raises(PortError):
        await store.get("local_fs://../secret.txt")
