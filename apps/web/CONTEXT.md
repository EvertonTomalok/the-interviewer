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

**Depends on** — the API's HTTP contract only (built against the route
shapes T09 confirmed — `/i/{slug}/claim`, `/jobs`, `/jobs/{area_id}/start`,
`/session/turns`, `/session/runs/{id}`, `/session/artifacts/{id}`,
`/session/finish`, `/auth/login`, `/admin/sessions`,
`/admin/sessions/{id}` — not against T09's code), not any Python package in
this repository. Nothing here imports `interviewer_core` or
`interviewer_adapters`.

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

**Traps** — built against the route shapes T09 (`wt-t09-api`, still
unmerged as of this branch) described as stable, not against a live
server — **not yet run against a real API**; field names on
`GET /admin/sessions`' rows are read defensively (`field()` tries a couple
of plausible key names) since the exact listing schema wasn't pinned down
when this was written. Expect a short follow-up pass once T09 merges and
this can actually be exercised in a browser (PRD §12.7's manual pass is
still open). `<audio src="/session/artifacts/{id}">` cannot carry an
`Authorization` header, so the interviewer-reply playback in
`interview.html` fetches the blob itself and plays an object URL instead —
`admin.html`'s recording playback uses a plain `<audio src>` and will need
the same treatment if `/session/artifacts/{id}` turns out to require a
bearer token for admin reads too (worth confirming against T09's actual
auth scoping).
