# T09 — API, auth, worker process

**Wave 3 · depends on T05, T07a, T08 · runs in parallel with T07b · covers PRD §11 T12–T13**

```bash
git worktree add ../wt-t09-api -b task/t09-api-worker master
```

**Owns:** `apps/api/**`, `apps/worker/**`, their `CONTEXT.md`s, their tests.

Both surfaces share one composition root shape, which is why they are one task:
splitting them means two branches editing `deps.py` in the same wave.

Inside the task the order is: **auth → routers → composition root → worker**. The
worker is small once the engine and the workflow exist; it is a consumer loop and
a shutdown handler.

## Reference in this repo

| Read | For |
|---|---|
| `apps/admin-api/src/ama_admin_api/deps.py` | a composition root: settings behind `lru_cache`, expensive clients built once and reused, a dependency that returns `None` instead of raising when the caller must **decide**, and a permission dependency factory whose returned callable is introspectable by a route-audit test |
| `apps/admin-api/src/ama_admin_api/services/auth_service.py` | token encode/decode kept in one service, away from the routers |
| `apps/admin-api/src/ama_admin_api/security/` | permission codes as an enum, and the guard that turns a missing one into a typed 403 |
| `apps/admin-api/src/ama_admin_api/routers/`, `schemas/` | thin routers over request/response schemas: validate at the boundary, delegate, never compute |
| `apps/admin-api/src/ama_admin_api/settings.py` | per-app settings subclass, queue names shared with the worker as configuration rather than as a repeated literal |
| `apps/worker/src/ama_worker/run.py`, `worker.py`, `settings.py` | worker entrypoint, the queue it drains, and per-job structured logging |
| `packages/shared-py/src/ama_shared/logging.py` | binding context (`trace_id`, `run_id`) so a run is greppable end to end |

## Deliverables

### Auth (PRD §8)

**Two principals, and the difference is the point** (PRD §8): an **admin** with
an account, and a **candidate** with a passkey and no account.

- bcrypt password hashing; JWT HS256 with `sub`, `role`, `exp`.
- **One** dependency extracts and validates the bearer token; a
  `require_role("admin")` factory guards the configuration and review routes
  (areas, personas, invites, `/admin/*`).
- **The candidate token is session-scoped**: HS256 carrying `session_id` and
  `role="candidate"`, expiring at `CANDIDATE_TOKEN_TTL_MINUTES`. A separate
  dependency resolves it **into the session itself**, so every `/session/*`
  handler receives the session it is allowed to touch and there is no id in the
  URL to check, forget, or tamper with.
- **`POST /i/{slug}/claim`** is the only public write. It: verifies the passkey
  against `passkey_hash` through bcrypt (never `==`), claims the invite
  atomically (T05), creates the session in phase `intake`, and returns the token
  plus the persona's **authored** greeting, intake prompt and question count. No
  run is started and no model is called — the candidate's first screen is instant
  and free.
- **Rate limit and lockout** on that route: `PASSKEY_MAX_ATTEMPTS` failures per
  slug within the window locks it for `PASSKEY_LOCKOUT_MINUTES`. A wrong passkey,
  an expired invite, a retired invite and an exhausted one return **the same
  typed error** — the endpoint must not become an oracle for which links exist.
- **The passkey is generated server-side**, returned **once** in the `POST
  /invites` response with the URL, and never again. It is never logged (T02's
  redaction covers `passkey`), never put in a query string, never mailed by this
  service.
- **Ownership is structural, not checked ad hoc.** A candidate token reaches five
  routes and one session; an admin token reaches the rest. Two live sessions and
  a candidate token that must fail against the other one is a test, not a
  comment.
- Redaction already configured in T02 covers `authorization`, `passkey` and
  `*_key`; add a test that a request log line for a login contains no password
  and no token, and one for a claim that contains no passkey.
- `REGISTRATION_OPEN=false` closes `/auth/register`; a seeded admin exists
  instead. **`/auth/register` never creates a candidate** — candidates have no
  accounts at all, which is why the route stays admin-shaped and closed.

### Routers (PRD §7)

Every route in the table, uniform envelope
`{success, data, error, metadata}` — including errors, including 422.

The hand-off that defines the product:

- `GET /session` is the page's resume: phase, `question_number` of
  `question_total`, the current question text and the turns so far — all resolved
  from the token's `session_id`. A reload mid-interview must land exactly where
  the candidate was, which is why the count is server-side (T08) and not a
  counter in the browser.
- `POST /session/turns` accepts `multipart/form-data`, validates at the
  boundary (`UPLOAD_ALLOWED_MIME`, `UPLOAD_MAX_BYTES`, `UPLOAD_MAX_SECONDS`,
  `SESSION_MAX_TURNS`)
  **and validates the phase** — an answer is accepted only in `intake` or
  `questioning`, so a request replayed after the farewell is a typed `409` and
  not a stray sixth turn. It starts a workflow run with
  `idempotency_key = f"{session_id}:{turn_index}"` and returns
  **`202 {run_id, turn_index}`**. It does not wait.
  **The route computes nothing.** It writes the uploaded bytes to the blob store
  under a staging key derived from `session_id` and `turn_index` — the request is
  the only moment those bytes exist — then enqueues and answers. The `Artifact`
  row is written by the run's `persist_audio` step (PRD §5.4), never here. No
  transcription, no LLM call inside a request — that work belongs to the worker
  draining the Redis stream, which is the whole point of the durable workflow. An
  API that transcribes in-request is an API that loses a paid turn on every
  deploy.
- `POST /session/finish` follows the same rule: it moves the phase to
  `evaluating`, starts the **evaluation** run with
  `idempotency_key = f"{session_id}:report"` and returns **`202 {run_id}`**.
  Scoring a whole interview is the most expensive model call in the product;
  doing it inside a request would tie the report to a connection that a proxy
  timeout can drop after the money is spent.
- `GET /session/runs/{id}` reports `queued | running | succeeded | failed` plus
  the result: `{transcript, question_text, question_number, question_total,
  phase, audio_artifact_id | null, coverage, degraded}`. This is what the browser
  polls. **`audio_artifact_id` is `null` in the PoC** — the interviewer replies
  in text (`REPLY_MODE=text`) — and the field exists from day one so
  `REPLY_MODE=voice` needs no schema change. An **evaluation** run answers a
  candidate token with `{"status": "succeeded"}` and **nothing else**: no score,
  no report id.
- **No candidate route serves a report.** Not filtered, not redacted — absent.
  A field that is never serialised on that side cannot leak through a rewritten
  client, and the test for it asks the token, not the UI.
- `GET /session/artifacts/{id}` resolves the id through `ArtifactRepository`,
  checks the row belongs to the token's session, then streams the bytes from the
  blob store (or redirects to its `signed_url` on a cloud store):
  the candidate's own takes always, interviewer replies only when voice mode
  produced one. An artifact id from another session is a `404`.
- `POST /invites` (admin) generates a passkey server-side, stores only its bcrypt
  hash, and returns `{url, passkey}` **exactly once**. `GET /invites` afterwards
  shows the slug, the state and the usage — never the secret.
- `DELETE /invites/{id}` (admin) retires a link that must stop working now:
  `status="retired"`, checked by the same `claim` path, so a leaked URL dies in
  one request. Sessions already claimed under it are untouched — retiring a door
  is not deleting what came through it.
- `GET /admin/sessions` lists every interview — candidate name, area, persona
  version, phase, overall score, timestamp — filterable and paginated on the
  indexes T05 added. `GET /admin/sessions/{id}` returns the transcript turn by
  turn with artifact links **and** the report. This is the only place a score is
  ever served.
- `/healthz` is liveness (no dependency touched); `/readyz` checks database and
  the workflow engine and reports **which** one is down.

### Composition root

`apps/api/deps.py` and `apps/worker/deps.py` build the object graph once from
settings: providers resolved through `require_spec`, decorators composed
(`Instrumented(RateLimited(Retrying(adapter)))`), repositories, blob store,
workflow engine. **Every other module receives its dependencies.**

A slug nobody registered fails **at process start**, loud, naming the slug — not
at the first turn with a candidate waiting.

### Worker

Consumes the workflow stream through the `WorkflowEngine` adapter: claim, run the
step, checkpoint, ack. **Both** workflows — the turn and the evaluation — are
drained by the same loop; the worker knows workflow names, not what they mean.
Structured log per run and per step (`run_id`, `step`,
`attempt`, `latency_ms`, `outcome`). Graceful shutdown: stop claiming new
entries, finish the current step, checkpoint, then exit — the visibility timeout
covers whatever was mid-flight, so a deploy costs a re-delivery, never a lost
turn.

## Tests

Through `httpx.ASGITransport`, on fakes and in-memory repositories, no container:

- auth: no token, malformed token, expired token, wrong role; a **candidate token
  against another session's artifact**, and against every `/admin` route;
- passkey: wrong passkey, expired invite, retired invite and exhausted invite all
  return the **same** typed error and the same status; the lockout engages after
  `PASSKEY_MAX_ATTEMPTS` and lifts after the window; a correct passkey during a
  lockout still fails;
- **the passkey never comes back**: it appears once in the `POST /invites`
  response and in no later read, no log line and no error body — assert on
  captured log output, not by eye;
- registration closed → 403 with the typed error, open → 201;
- upload guards: oversized, wrong mime, ceiling exceeded — each a typed 4xx in
  the envelope, never a 500;
- **phase guards**: an answer in `closing` is a `409`; `finish` before the intake
  turn is refused; a candidate cannot set `candidate_name` through any body;
- the full happy path, exactly as a candidate lives it: admin logs in → creates
  an area → publishes a persona version (greeting, intake, farewell, questions,
  expected answers, rubric) → publishes an invite → **claim with the passkey** →
  greeting comes back with no run started → post the name recording → poll →
  name registered, first question returned as `1 of N` → post an answer → poll →
  reach `closing` with the farewell → finish → poll → the candidate sees only
  `succeeded` → **the admin** reads the transcript and the report. All on
  `inline` + fakes;
- **finish is idempotent**: two `POST /session/finish` produce one run and one
  report;
- **double-tap**: two identical `POST /session/turns` produce one run and one
  turn;
- **the route did no work**: `POST /session/turns` with an LLM and an STT fake
  that fail on any call still returns `202`. If the route can be made to fail by breaking a
  provider, it is doing the worker's job;
- a succeeded run in text mode returns `question_text` and
  `audio_artifact_id: null`; the same path under `REPLY_MODE=voice` + `FakeTTS`
  returns an id that `/session/artifacts/{id}` serves;
- **no score reaches the candidate**: after a succeeded evaluation, every
  `/session/*` response is asserted to contain no `score`, no `verdict` and no
  `rationale` — asserted on the raw JSON, so a field added later fails the test;
- envelope shape asserted for a success, a validation error and a domain error;
- worker: a claimed entry whose handler raises transient is retried; permanent
  goes to the DLQ; shutdown mid-step leaves a replayable run.

## Done when

- The auth suite is green and the isolation tests are real: two live sessions,
  two candidate tokens, one admin — each reaching exactly what it should.
- A candidate completes an interview with **no account**: one link, one passkey,
  a name, the questions, a farewell, a confirmation — and no score anywhere on
  their side.
- Everything above is green on `WORKFLOW_PROVIDER=inline`, which is what this
  task builds against — T07a is its dependency, T07b is not.
- `docker compose up` runs api + worker + postgres + redis, and one turn
  completes end to end **with `WORKFLOW_PROVIDER=redis`** — the turn is executed
  by the worker process, and stopping the worker leaves the run `queued` rather
  than making the API do it. This last criterion is the one that needs **T07b on
  `master`**: if the Redis lane has not landed yet, tick it the day it does
  rather than pretending `inline` proved it.
- `apps/api/CONTEXT.md` and `apps/worker/CONTEXT.md` answer "add a route → here"
  and "add a dependency → here", and state under **Traps** that `deps.py` is
  append-only during parallel waves.

## Land it — worktree → `master`

`make check` inside the worktree first. No network, no containers, so there is
no excuse to skip it.

```bash
cd ../wt-t09-api
make check                    # ruff, mypy --strict, tests, coverage, docs-check
git add -A && git commit -m "feat(api): routes, auth, composition root and workflow worker (T09)"

cd <repo>                     # the main checkout, always on master
git switch master
git merge --no-ff task/t09-api-worker -m "feat(api): routes, auth, composition root and workflow worker (T09)"
make check                    # green on the trunk, not only on the branch

git worktree remove ../wt-t09-api
git branch -d task/t09-api-worker
```

Merged straight onto `master` — no pull request, no integration branch. If
`make check` fails on the trunk after the merge, fix it on `master` at once:
every later lane branches off it.
