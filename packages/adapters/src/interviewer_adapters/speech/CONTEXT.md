# interviewer_adapters/speech

**Responsibility** — every provider behind `interviewer_core.ports.speech`:
`SpeechToTextPort` and `TextToSpeechPort`. Currently the scripted `fake` STT
(used by every other lane's unit suite and by a clean clone with no API
key) and the `none` TTS Null Object (the PoC's real default, since the
demo's intended shape is text replies). A real `openai_compat` STT/TTS pair
is P0-scoped but not yet built in this branch.

**Public surface** — nothing here is imported by name outside this package
and its tests. A caller reaches a provider through
`interviewer_core.registry.require_spec("stt" | "tts", settings.stt_provider
| settings.tts_provider).build(settings)`.

**Depends on** — `interviewer_core.ports.speech`, `interviewer_core.errors`,
`interviewer_core.registry`.

**Invariants** — `fake` STT refuses to build under `APP_ENV=prod` (a silent
fake transcript would be worse than a missing key); `none` TTS is **never**
refused in prod — it is a deliberate Null Object, not a dev shortcut, so a
missing speech key degrades the reply to text instead of crashing the turn.

**Where to change what** — add a provider → one new module in this
directory that builds an `SpeechToTextPort`/`TextToSpeechPort` and calls
`register(ProviderSpec(...))` at import time, plus one import line appended
to this package's `__init__.py` and to `interviewer_adapters/__init__.py`.
Never add an `if/elif` on a provider slug anywhere.

**Traps** — `none` and `fake` look interchangeable (both return
placeholder-ish audio) but are not: `fake` stands in for a real STT under
test/dev, `none` stands in for "no TTS at all" and stays legal in prod.
Don't refuse `none` in prod by copying the `fake` pattern.
