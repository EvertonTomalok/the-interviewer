# interviewer_adapters/storage

**Responsibility** — every provider behind `interviewer_core.ports.storage.BlobStore`.
Currently `local_fs`, a directory on disk with HMAC-signed short-lived URLs,
plus `InMemoryBlobStore`, the dict-backed twin the rest of the unit suite
stores audio through. `s3`/`gcs` (PRD §3.2) are not yet built in this branch.

**Public surface** — a real provider is never imported by name; a caller
reaches it through
`interviewer_core.registry.require_spec("storage", settings.storage_provider).build(settings)`.
`InMemoryBlobStore` is the one exception — it is not registered (there is no
`STORAGE_PROVIDER=in_memory` slug, same as the in-memory persistence repos)
and is re-exported from `interviewer_adapters.storage` for a test or
composition root to import directly.

**Depends on** — `interviewer_core.ports.storage`, `interviewer_core.errors`,
`interviewer_core.registry`; stdlib `pathlib`/`hmac`/`hashlib`/`time` only.

**Invariants** — `get()` on a missing key raises `PortError(transient=False,
status=404)`, never a bare `FileNotFoundError` — the workflow layer only
ever sees the port's own error shape. `signed_url()` tokens are verified by
the same HMAC key material the store signed with (`verify()`); an expired or
tampered token fails closed. Every key is resolved against `root` and checked
with `is a descendant of root` before any read or write; a key that escapes
(`../`, an absolute path) raises `PortError(status=400)` instead of touching
the filesystem outside `root`.

**Where to change what** — add a provider → one new module in this
directory that builds a `BlobStore` and calls `register(ProviderSpec(...))`
at import time, plus one import line appended to this package's
`__init__.py` and to `interviewer_adapters/__init__.py`. Never add an
`if/elif` on a provider slug anywhere.

**Traps** — `local_fs`'s signature secret defaults to a hardcoded dev value
(`"local-fs-dev-secret"`); it is a `local_fs`-only concern, not a shared
app secret, and must not be reused for anything else. `root` is created
(`mkdir(parents=True, exist_ok=True)`) at construction time, so a bad path
in config fails at first write, not at boot. `Path(root) / key` alone is not
safe: pathlib silently discards `root` when `key` looks absolute
(`Path("/root") / "/etc/passwd" == Path("/etc/passwd")`), and a `../`-laced
key walks back out — `_resolve()` exists precisely to close both, and any new
method that turns a key into a filesystem path must go through it, never
build the path inline. With `STORAGE_PROVIDER=local_fs` the API and the
worker must share one `root` (one volume in `docker compose`) — split them
and every playback 404s.
