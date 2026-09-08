from __future__ import annotations

import pytest

from interviewer_adapters.storage.in_memory import InMemoryBlobStore
from interviewer_core.errors import PortError


async def test_put_get_round_trip() -> None:
    store = InMemoryBlobStore()
    uri = await store.put("sessions/s1/turn-0.wav", b"audio-bytes", mime="audio/wav")
    assert uri == "memory://sessions/s1/turn-0.wav"
    assert await store.get(uri) == b"audio-bytes"


async def test_get_missing_raises_port_error() -> None:
    store = InMemoryBlobStore()
    with pytest.raises(PortError):
        await store.get("memory://missing.wav")


async def test_signed_url_verifies_and_expires() -> None:
    store = InMemoryBlobStore()
    await store.put("a.wav", b"x", mime="audio/wav")

    url = await store.signed_url("memory://a.wav", expires_in_seconds=60)
    query = url.split("?", 1)[1]
    params = dict(p.split("=") for p in query.split("&"))

    assert store.verify("a.wav", expires_at=int(params["expires"]), signature=params["sig"])
    assert not store.verify("a.wav", expires_at=int(params["expires"]), signature="bad")
    assert not store.verify("a.wav", expires_at=0, signature=params["sig"])
