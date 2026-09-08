# apps/web

**Responsibility** — three static pages served by the API, no build step, no
framework, no bundler: `jobs.html` (the public landing page — no credential
at all, lists every published job from `GET /jobs` and starts one with
`POST /jobs/{area_id}/start`), `interview.html` (the candidate flow —
reachable either via a passkey-gated `/i/{slug}` invite link or, token
already in hand, straight from `jobs.html` — camera preview,
record/listen-back/re-record/send, poll, read the farewell) and
`admin.html` (the reviewer's login, session list, transcript and report
view). They exist to demo the loop, not to be a product.

**Public surface** — the three HTML files themselves; each is a single page
with one inline `<script type="module">`, no shared JS module between them.

**Depends on** — the API's HTTP contract only (`GET /i/{slug}`,
`POST /i/{slug}/claim`, `GET /jobs`, `POST /jobs/{area_id}/start`,
`POST /session/turns`, `GET /session/runs/{id}`,
`GET /session/artifacts/{id}`, `POST /session/finish`, `POST /auth/login`,
`GET /admin/sessions`, `GET /admin/sessions/{id}`,
`GET /admin/artifacts/{id}`), not any Python package in this repository.
Nothing here imports `interviewer_core` or `interviewer_adapters`. `main.py`
serves these three files itself via a `StaticFiles` mount — there is no
separate static server.

**Invariants** — the camera toggle in `interview.html` is preview-only:
`getUserMedia({video: true})` renders a local `<video>` element and nothing
else. No frame is read, uploaded, or stored. The candidate token lives in a
JS variable only, never `localStorage` — a shared laptop is the normal case
for this link. `admin.html` never renders a score, verdict or rationale
anywhere a candidate token could reach it; the report only ever comes back
through an admin-authenticated route. Only the *sent* take is uploaded — a
discarded re-record's blob URL is revoked (`resetTake()`) so a long
interview does not quietly pile up abandoned recordings in memory. The send
and finish buttons guard against a double-tap with a `sending` flag, since
the run underneath is idempotent but the UI must not open a second one
either.

**Where to change what** — the public job list and "start" click →
`jobs.html`; candidate-facing recording/playback flow → `interview.html`;
anything the admin reads (transcript, report, session list) →
`admin.html`. All three pages are plain HTML/JS; there is no shared
component layer to route a change through. The audio-branch for voice
replies is `if (state.audio_artifact_id)` inside `pollTurn()` — one page,
both `REPLY_MODE`s, no build flag. `jobs.html` hands `interview.html` its
issued token via `sessionStorage["pending_session"]`, read once and
removed immediately (`pendingSessionFromJobsPage()`) — never `localStorage`,
same rule as the passkey-flow token.

**Traps** — verified live against a real API, worker, Postgres and Redis
(`scripts/demo.py` end to end, plus a manual browser pass on both
`interview.html` and `admin.html`) — the two gaps below were found that way
and are fixed, not open. `<audio src="...">` cannot carry an `Authorization`
header, so **every** authenticated recording playback fetches the blob
itself and plays an object URL instead of a bare `<audio src>`:
`interview.html` for the interviewer's reply audio, `admin.html`'s
`loadAudio(artifactId)` for a session's recordings via `GET
/admin/artifacts/{id}`. `GET /i/{slug}` is one path serving two
representations by `Accept` header — the page's own `loadPreview()` fetch
gets JSON, a browser navigating there gets `interview.html` itself; do not
add a second URL for the preview, the server already content-negotiates
this one. `field()` on `admin.html`'s session table still reads a couple of
plausible key names defensively — cheap insurance, not a sign the schema is
still unstable.
