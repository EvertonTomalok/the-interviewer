# interviewer_adapters/storage

**Responsibility** — every provider behind `interviewer_core.ports.storage.BlobStore`.
Currently `local_fs`, a directory on disk with HMAC-signed short-lived URLs.
`s3`/`gcs` (PRD §3.2, P1) are not yet built in this branch.

**Public surface** — nothing here is imported by name outside this package
and its tests. A caller reaches a provider through
`interviewer_core.registry.require_spec("storage", settings.storage_provider).build(settings)`.

**Depends on** — `interviewer_core.ports.storage`, `interviewer_core.errors`,
`interviewer_core.registry`; stdlib `pathlib`/`hmac`/`hashlib`/`time` only.

**Invariants** — `get()` on a missing key raises `PortError(transient=False,
status=404)`, never a bare `FileNotFoundError` — the workflow layer only
ever sees the port's own error shape. `signed_url()` tokens are verified by
the same HMAC key material the store signed with (`verify()`); an expired or
tampered token fails closed.

**Where to change what** — add a provider → one new module in this
directory that builds a `BlobStore` and calls `register(ProviderSpec(...))`
at import time, plus one import line appended to this package's
`__init__.py` and to `interviewer_adapters/__init__.py`. Never add an
`if/elif` on a provider slug anywhere.

**Traps** — `local_fs`'s signature secret defaults to a hardcoded dev value
(`"local-fs-dev-secret"`); it is a `local_fs`-only concern, not a shared
app secret, and must not be reused for anything else. `root` is created
(`mkdir(parents=True, exist_ok=True)`) at construction time, so a bad path
in config fails at first write, not at boot.
