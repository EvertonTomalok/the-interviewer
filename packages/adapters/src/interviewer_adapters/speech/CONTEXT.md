# interviewer_adapters/speech

**Responsibility** — every provider behind `interviewer_core.ports.speech`:
`SpeechToTextPort` and `TextToSpeechPort`. `openai_compat` STT is the one
speech call the PoC makes against a real provider; `openai_compat` TTS is
built and fully tested but ships unconfigured (`TTS_PROVIDER=none` is the
default, `tts_none.py`). `fake` STT and `FakeTTS` are what every other
lane's unit suite runs on. `boundary.py` validates an upload once, at the
edge, before anything downstream trusts its shape.

**Public surface** — a real provider is never imported by name; a caller
reaches it through `interviewer_core.registry.require_spec("stt" | "tts",
settings.stt_provider | settings.tts_provider).build(settings)`.
`validate_upload` and `FakeTTS` are re-exported from
`interviewer_adapters.speech` for the API layer and a voice-mode test to
import directly — `FakeTTS` is a test double, not a registered slug, the
same way the only *configured* way to have no voice is `TTS_PROVIDER=none`.

**Depends on** — `interviewer_core.ports.speech`, `interviewer_core.errors`,
`interviewer_core.config`, `interviewer_core.registry`; `httpx.AsyncClient`
for the two real adapters; stdlib `struct` for `FakeTTS`'s WAV header.

**Invariants** — `fake` STT refuses to build under `APP_ENV=prod` (a silent
fake transcript would be worse than a missing key); `none` TTS is **never**
refused in prod — it is a deliberate Null Object, not a dev shortcut, so a
missing speech key degrades the reply to text instead of crashing the turn.
`none.synthesize()` does not return silence if it is ever called — it raises
`ConfigError` naming `TTS_PROVIDER` and `REPLY_MODE`, because a PoC that
quietly plays an empty clip looks like a working feature instead of the bug
it is (the `synthesize` workflow step should have skipped before reaching
it). No adapter lets an `httpx` exception escape; every failure maps onto
`PortError(transient, status)`. A missing credential raises `ConfigError`
naming the exact env var, at `build()` time. `validate_upload` raises
`DomainError` naming what was wrong (mime, size, or duration) and never lets
an oversized or unsupported upload reach a provider call.

**Where to change what** — add a provider → one new module in this
directory that builds an `SpeechToTextPort`/`TextToSpeechPort` and calls
`register(ProviderSpec(...))` at import time, plus one import line appended
to this package's `__init__.py` and to `interviewer_adapters/__init__.py`.
Never add an `if/elif` on a provider slug anywhere. Boundary rules (mime
allowlist, max bytes, max duration) change in `boundary.py` and in
`Settings` (`UPLOAD_*`), never inline at a call site.

**Traps** — `none` and `fake` look interchangeable (both stand in for a real
provider) but are not: `fake` stands in for a real STT under test/dev and is
refused in prod, `none` stands in for "no TTS at all" and stays legal in
prod — don't refuse `none` in prod by copying the `fake` pattern. Mime comes
from the boundary the API declares on upload, never from sniffing bytes.
STT transcribes; it never translates — `language` is a hint passed straight
through to the provider, and no translate route is ever selected.
`openai_compat` TTS is exercised by tests and by `REPLY_MODE=voice`, never
by the default PoC run — `.env.example` deliberately ships no
`TTS__OPENAI_COMPAT__*` key filled in. `validate_upload`'s
`duration_seconds` is optional and skipped when the caller has no cheap way
to know it (real duration requires decoding the container, which this
module does not do) — a caller that has the browser-reported duration
should pass it, but its absence is not itself a rejection.
