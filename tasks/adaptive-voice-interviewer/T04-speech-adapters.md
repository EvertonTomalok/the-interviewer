# T04 — Speech adapters (STT live, TTS built and switched off)

**Wave 1 · lane B · depends on T02 · runs in parallel with T03, T05, T06 · covers PRD §11 T6**

> **The PoC is audio-in, text-out.** STT is the only speech call that runs
> against a real provider: the candidate speaks, the interviewer writes. TTS is
> written, registered and tested against a mock transport in this same lane, but
> ships **unconfigured** — `TTS_PROVIDER=none` builds a Null Object and the
> `synthesize` step of PRD §5.4 records itself skipped. Building it now and
> switching it off is what makes `REPLY_MODE=voice` a flag later instead of a
> project.

```bash
git worktree add ../wt-t04-speech -b task/t04-speech-adapters master
```

**Owns:** `packages/adapters/src/interviewer_adapters/speech/**`, its
`CONTEXT.md`, its tests. **Appends only** to `interviewer_adapters/__init__.py`,
`.env.example`, the README configuration table.

This lane does **not** import the LLM lane. It registers into the same registry
(`kind="stt"`, `kind="tts"`) that T02 froze and T03 fills — both lanes call
`register(...)`, neither reads the other's module.

## Reference in this repo

| Read | For |
|---|---|
| `apps/transcriber/src/ama_transcriber/tasks.py`, `worker.py` | a transcription job end to end: fetch the bytes, call the provider, store the text, record usage — and what it does when the provider is down |
| `packages/shared-py/src/ama_shared/transcription/` | where transcription concerns live as a module rather than inline in a worker: usage accounting, provider settings, result shape |
| `packages/shared-py/src/ama_shared/media.py` | mime handling, size limits, and the difference between a URL you may hand to a browser and bytes you must proxy |
| `packages/shared-py/src/ama_shared/llm/openai_compat.py` | the same OpenAI-shaped transport pattern this adapter reuses for `/audio/transcriptions` and `/audio/speech` |
| `packages/shared-py/src/ama_shared/errors.py` | typed failure instead of a bare `raise` from inside an HTTP call |

## Deliverables

### `stt_openai_compat.py` — the one that runs live

`SpeechToTextPort.transcribe(audio, mime, language?) -> Transcript`, whisper-shaped
multipart upload. Returns text plus provider usage (duration or tokens, whatever
the endpoint reports — an absent field is `None`, never a fabricated zero).

`language` is a **hint passed straight through**, from the session's pinned
language. This adapter transcribes; it never translates. An endpoint that offers
a translate route is not wired to one — a transcript in a language the session
did not pin is a silently different product (PRD §2, non-goals).

### `tts_openai_compat.py` — built now, configured later

`TextToSpeechPort.synthesize(text, voice, format) -> AudioBlob`. Returns bytes
plus mime; the caller (T07's `synthesize` step) is what puts them in the blob
store. The adapter does no storage.

Fully implemented and fully tested on the mock transport, with **no key in
`.env.example`**. It is exercised by tests and by `REPLY_MODE=voice`, never by
the default PoC run.

### `tts_none.py` — the Null Object

Registered under `kind="tts"`, `name="none"`, and it is the **default**.
`synthesize()` is never called in text mode — the workflow's `synthesize` step
skips before reaching it. If something does call it, it raises a `ConfigError`
naming `TTS_PROVIDER` and
`REPLY_MODE` together rather than returning silence a player would accept.
Silence that plays is a bug that takes a week to find.

Boot-time cross-check lives here too: `REPLY_MODE=voice` with
`TTS_PROVIDER=none` fails at process start, naming both variables.

### `fake.py`

`FakeSTT` returns a scripted transcript per call and registers as `kind="stt"`,
`name="fake"` — a real slug, not a test-only import, because `STT_PROVIDER=fake`
is half of what lets a clean clone run an interview with no provider account
(PRD §6). Like the LLM fake it is refused under `APP_ENV=prod`. `FakeTTS` returns
a valid, silent WAV of the right length and stays a **test double**: it is
injected by the voice-mode tests, not selected by a slug, because the only
configured way to have no voice is `TTS_PROVIDER=none`. The whole unit suite of
every other lane runs on these.

### Boundary validation

Audio is validated **once, at the boundary**, and the result is carried as data:

- content-type allowlist (`audio/webm`, `audio/ogg`, `audio/wav`, `audio/mpeg`);
- max bytes and max duration from settings — `UPLOAD_MAX_BYTES` and
  `UPLOAD_MAX_SECONDS`, with the allowlist above coming from `UPLOAD_ALLOWED_MIME`;
- anything else → a typed error naming what was wrong, never a 500.

Browsers disagree on format: Chrome hands you `audio/webm;codecs=opus`, Safari
hands you something else. The mime is **declared at the boundary and carried
through the workflow**, so the adapter never guesses from bytes. If the endpoint
cannot take that mime, the adapter converts or refuses with a typed error — it
does not send it and hope.

## Tests

Against a mock transport, no network:

- transcribe: success, 429 → transient `PortError`, 400 → permanent, malformed
  body, usage parsed.
- synthesize: success returns non-empty bytes with a declared mime; failure maps
  the same way.
- missing credential → `ConfigError` naming `STT__OPENAI_COMPAT__API_KEY` /
  `TTS__OPENAI_COMPAT__API_KEY`.
- boundary: oversized upload, over-long upload, unsupported mime — each rejected
  with a typed error carrying the reason.
- `STT_PROVIDER=fake` builds `FakeSTT` through the factory like any slug, and
  raises under `APP_ENV=prod`.
- `FakeTTS` output is a WAV a player accepts (header checked), because the
  voice-mode tests play it.
- `TTS_PROVIDER=none` builds without a key and **does not raise at build time**;
  it raises only if something calls `synthesize`, naming `TTS_PROVIDER` and
  `REPLY_MODE`.
- `REPLY_MODE=voice` + `TTS_PROVIDER=none` → `ConfigError` at settings load,
  naming both.
- A `language` hint reaches the provider payload unchanged, and no code path
  requests translation.

## Done when

- Transcribe green on the mock transport; synthesize green on the mock transport
  even though nothing configures it in the PoC.
- A default `.env.example` (`STT` key filled, `TTS_PROVIDER=none`) boots and runs
  an interview end to end.
- Fakes are good enough that another lane can build a whole interview on them.
- Speech blocks present in `.env.example` and the README configuration table,
  including `REPLY_MODE` and the `none` slug.
- `speech/CONTEXT.md` states under **Traps**: mime comes from the boundary, never
  from sniffing; the Null Object is `tts_none`, and it is *not* silent-on-call
  — it raises, because a PoC that quietly plays silence looks like a broken
  provider; and STT transcribes, never translates.

## Land it — worktree → `master`

`make check` inside the worktree first. No network, no containers, so there is
no excuse to skip it.

```bash
cd ../wt-t04-speech
make check                    # ruff, mypy --strict, tests, coverage, docs-check
git add -A && git commit -m "feat(speech): stt and tts adapters with fakes and boundary validation (T04)"

cd <repo>                     # the main checkout, always on master
git switch master
git merge --no-ff task/t04-speech-adapters -m "feat(speech): stt and tts adapters with fakes and boundary validation (T04)"
make check                    # green on the trunk, not only on the branch

git worktree remove ../wt-t04-speech
git branch -d task/t04-speech-adapters
```

Merged straight onto `master` — no pull request, no integration branch. If
`make check` fails on the trunk after the merge, fix it on `master` at once:
every later lane branches off it.
