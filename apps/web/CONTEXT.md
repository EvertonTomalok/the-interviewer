# apps/web

**Responsibility** — two static pages served by the API, no build step, no
framework, no bundler: `interview.html` (the public, passkey-gated candidate
flow — camera preview, record/listen-back/re-record/send, poll, read the
farewell) and `admin.html` (the reviewer's login, session list, transcript
and report view). They exist to demo the loop, not to be a product.

**Public surface** — the two HTML files themselves; each is a single page
with one inline `<script type="module">`, no shared JS module between them.

**Depends on** — the API's HTTP contract only (its OpenAPI schema), not any
Python package in this repository. Nothing here imports `interviewer_core`
or `interviewer_adapters`.

**Invariants** — the camera toggle in `interview.html` is preview-only:
`getUserMedia({video: true})` renders a local `<video>` element and nothing
else. No frame is read, uploaded, or stored. `admin.html` never renders a
score anywhere a candidate's token could reach it — it is served from an
admin-only route.

**Where to change what** — candidate-facing recording/playback flow →
`interview.html`; anything the admin reads (transcript, report, session
list) → `admin.html`. Both pages are plain HTML/JS; there is no shared
component layer to route a change through.

**Traps** — both files are placeholders today. They exist so `docs-check`
and the compose wiring have something real to point at; the recording flow,
the polling loop and the report view are built once the API's routes exist.
