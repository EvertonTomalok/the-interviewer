# T10 — Web pages, demo script, closing docs sweep

**Wave 4 · depends on T09 · covers PRD §11 T14–T16**

Two sub-lanes that **run in parallel** if there are two people, then a sweep that
needs both merged:

```bash
git worktree add ../wt-t10-web  -b task/t10-web  master   # lane 1: apps/web
git worktree add ../wt-t10-demo -b task/t10-demo master   # lane 2: scripts/demo.py
# after both merge:
git worktree add ../wt-t10-docs -b task/t10-docs master   # lane 3: the sweep
```

**Owns:** lane 1 `apps/web/**`; lane 2 `scripts/demo.py`; lane 3 `README.md`,
`ARCHITECTURE.md`, `docs/**`, and every `CONTEXT.md` that drifted.

Lane 1 builds against the **OpenAPI schema** from T09, not against T09's code —
which is what lets it start the moment T09 merges its routers.

## Reference in this repo

| Read | For |
|---|---|
| `apps/admin-web/` | only for the shape of a client that holds a token, polls a job and renders its result. The new page is plain HTML + one JS module — **no framework, no bundler, no build step** |
| `packages/shared-py/src/ama_shared/media.py` | why the browser is handed a signed URL or a proxied stream rather than a storage path |
| `README.md` and `CLAUDE.md` at this repo's root | the difference between a page a reviewer reads in twenty minutes and a page that lists everything |
| `tasks/*.md` in this repo | prior PRDs whose diagrams named real modules — a diagram that describes a structure the code does not have is worse than no diagram |

## Lane 1 — two pages (PRD §9)

`interview.html` for the candidate and `admin.html` for the reviewer, both
static, both served by the API. They exist to demo the loop, not to be a product.

**Page copy is English**, on both pages, like everything else in this repository.
The persona's own text — greeting, questions, farewell — is data and may be in
any language; the buttons, labels and error lines around it are not.

### 1a. `interview.html` — the public link

1. **passkey screen** at `/i/{slug}` — the area, the persona's name and the
   question count come from `GET /i/{slug}`, which needs no credential and
   reveals nothing else. `POST /i/{slug}/claim` returns the session token, held
   **in memory** (never `localStorage`: a shared laptop is the normal case here).
   A wrong passkey and a locked slug say only that, never which;
2. **greeting** — the persona's authored introduction and its request for the
   candidate's name, rendered from the claim response. No run, no poll, no
   spinner: this screen is instant because the server did no work to produce it;
3. **camera toggle** — `getUserMedia({video: true})` renders a local preview and
   nothing else. No frame is read, uploaded or stored. Say so in the page copy
   and in `apps/web/CONTEXT.md`, so nobody later assumes video analysis exists;
4. **record → listen → re-record → send** — `MediaRecorder` produces a take, the
   candidate plays it back and re-records as often as they like, and **only the
   sent take is uploaded**. Discarded takes never leave the browser: revoke the
   old blob URL on each retake, so a long interview does not quietly grow a pile
   of abandoned recordings in memory. The send button is the only commitment on
   the page and must look like one;
5. the answer goes to `POST /session/turns` (no id in the URL — the token carries
   it). The reply is `202`, so the turn shows as *processing*: a worker has it
   now, and the page says that rather than pretending to be busy;
6. poll `GET /session/runs/{id}` until terminal, then **render `question_text`**
   with its position — **`3 of 8`** from `question_number` / `question_total`,
   both server-sent, so a reload does not restart the count. If the result
   carries an `audio_artifact_id` (voice mode), play it under the text. **One
   page, both modes** — the audio branch is `if (result.audio_artifact_id)`, not
   a build flag, so `REPLY_MODE=voice` needs no edit here;
7. the thread grows turn by turn — the candidate's transcript above, the
   interviewer's written question below, each of their own takes replayable from
   `/session/artifacts/{id}`;
8. when a run comes back with `phase: "closing"`, **the recorder disappears** and
   the persona's farewell is on screen. **Finish** → `202`, poll that run, and
   end on *sent for review*. **No score, no rationale, no report** — and nothing
   in the page's code that would render one if a server ever sent it.

Handle the states an interview actually hits: microphone permission denied, a
run that fails (show the reason, keep the session), a turn that takes longer than
the poll budget, an expired session token mid-interview (say so plainly — the
link is spent), and the send button double-tapped (the run is idempotent — the UI
must not open a second one either).

### 1b. `admin.html` — the reviewer

Login → `GET /admin/sessions`: a table of candidate name, area, persona version,
phase, overall score, date. One click opens `GET /admin/sessions/{id}` — the
transcript turn by turn with every recording playable, and beside it the report:
overall score, then each question with its score, verdict and rationale,
unanswered ones included and marked as such.

Small, but not optional: this page is the reason the product stores anything.

**Verification is manual and it is real**: open the public link in a private
window, enter the passkey, hear the greeting, say your name, toggle the camera,
record an answer, **play it back, re-record it**, send, read two numbered
questions, reach the farewell, finish — and confirm the page shows *sent for
review* and no score. Then log in on the admin page and read that same interview
and its report. Repeat the candidate pass once with `REPLY_MODE=voice` and a TTS
slug set — same pages, same build, audio plays under each question. If that
second pass needed a code change, lane 1 built two clients instead of one.

## Lane 2 — `scripts/demo.py`

A headless interview that walks the **candidate's** path, not a private one:
seed an admin, an area and **one persona version** (greeting, intake prompt,
farewell, questions, expected answers, rubric); publish an **invite**; **claim it
with the passkey** exactly as the browser does; send the name recording and read
the name back; send an answer per question, printing each numbered question the
interviewer wrote; read the farewell; finish; then switch to the **admin** token
and print the report — overall score plus each question's score, verdict and
rationale. One command after `git clone` and a filled `.env`.

Printing the claim step matters: the script is the executable proof that the
public link plus a passkey is all a candidate needs.

The seeded persona is also the sample a reader copies: three or four questions
with real `expected_answer` text, not `"..."` placeholders. It is the clearest
documentation the project has of what configuring an interview means.

It must run against a **cheap real model** (`openai/gpt-4.1-mini` shape) and
against `WORKFLOW_PROVIDER=redis` like every other running process — it posts and
polls, so it exercises the same routes the browser does. `--reply-mode voice`
additionally writes the reply audio to disk; the default writes none, because the
PoC has none to write.

Degrade honestly: with no STT provider configured it runs on `FakeSTT` and
**says** it did, in the output, on the line before the transcript.

## Lane 3 — the sweep

Not a documentation phase. Every task already documented its own module in its
own branch — that is step 7 of the `build` skill. This lane reconciles only what
no single lane owned:

- regenerate the **five Mermaid diagrams** against the code as built — hexagon,
  turn sequence (with the `202 + poll` hand-off visible, and **Finish** taking
  the same route to the evaluation run), workflow state machine (including the
  replay arrow that skips memoized steps), **session lifecycle as the phase
  machine** (`intake → questioning → closing → evaluating → completed`), data
  model. Every diagram names paths that exist, and none of them names a
  retriever;
- fill the README **configuration table** from `known_providers()` and
  `.env.example` — `docs-check` fails if a registered slug or an env key is
  missing from it;
- write the ADRs for what the build actually decided: why hexagonal at this size,
  why Redis now and Temporal later, why checkpoints live in Postgres and not
  Redis, why personas are versioned and never edited, why the camera is
  preview-only, **why there is no knowledge base** — the persona carries the
  questions and the expectations, retrieval is expansion `E1`, and the ADR says
  what would make us build it — **why a candidate has a passkey instead of an
  account**, **why the candidate never sees the score**, and **why a SQLModel
  table never leaves the persistence adapter** — the one a reader who knows the
  library asks first, since SQLModel is sold on letting the table be the model;
- README sections in order: what it is → run it in four commands → the loop in
  one diagram → architecture at a glance → configuration table → how to swap an
  adapter → how to add a provider → testing → **what is deliberately not built**
  (PRD §2 non-goals, stated plainly, so an absence reads as a decision) → **what
  comes next** (the PRD §11 expansions, `E1` first: knowledge base + retrieval,
  then the embedder).

## Full verification (PRD §12) — run here, in this order

1. `make check` — ruff, mypy --strict, unit suite, coverage ≥ 80%, docs-check.
   **No network, no containers.**
2. `docker compose up -d postgres redis && make migrate && make dev` — api and
   worker boot, `/healthz` and `/readyz` green.
3. `python scripts/demo.py` — a real interview on `redis`, claimed with a
   passkey: name registered, numbered questions printed, farewell printed, report
   printed through the admin routes, no audio written (text mode).
4. **Durability drill** — start a turn, `docker kill` the worker mid-run, restart.
   Assert in Postgres: completed steps kept their outputs, no step ran twice,
   exactly one `Turn` at that index, run reaches `succeeded`.
5. **Adapter swap drill** — flip `LLM_PROVIDER` between `openrouter` and
   `openai_compat`, `WORKFLOW_PROVIDER` between `redis` and `inline`,
   `STORAGE_PROVIDER` between `local_fs` and `s3` (MinIO in compose, so no AWS
   account is needed), and `REPLY_MODE` from `text` to `voice` with a TTS slug
   configured. The same interview completes with **no code change** each time.
   The storage flip proves the recordings can move to a bucket without the engine
   noticing; the reply-mode flip proves text-out was a configuration choice, not
   a missing feature. This is the architectural claim of the project, so it is
   verified, not asserted.
6. **Passkey drill** — wrong passkey `PASSKEY_MAX_ATTEMPTS` times → locked;
   expired, retired and exhausted invites answer identically to a wrong passkey;
   a candidate token from session A reads nothing of session B and nothing under
   `/admin`; grep the logs for the passkey and find nothing.
7. Browser pass, as above — the candidate journey end to end in text mode, then
   in voice mode, same build; the admin page shows both interviews and their
   reports.
8. **Evaluation replay** — finish a session, `docker kill` the worker between
   `score` and `commit_report`, restart. One report, and the model was not called
   twice (assert on the step records: `score` kept its output).

## Done when

- `make docs-check` is green on the whole tree and every diagram names a path
  that exists.
- All four drills (4, 5, 6 and 8) pass and are written down in the README, with
  the exact commands, so a reviewer can repeat them.
- The candidate pass leaks nothing: no score on screen, none in any
  `/session/*` response, no passkey in any log.
- The README's "deliberately not built" section covers video, streaming,
  multi-tenancy, Temporal, **spoken replies in the PoC**, **translation**,
  **typed answers** and **the knowledge base, retrieval and the embedder**, each
  with one line of why —
  an absence a reviewer can tell apart from an oversight — and is followed by the
  expansion list that says where each one would attach.

## Land it — three merges, web and demo first

Web and demo are independent lanes and land in either order. The sweep branches
off the `master` that already carries both, because it regenerates diagrams
against merged code.

```bash
# lane 1
cd ../wt-t10-web && make check
git add -A && git commit -m "feat(web): passkey interview client and admin review page (T10)"
cd <repo> && git switch master
git merge --no-ff task/t10-web -m "feat(web): passkey interview client and admin review page (T10)"
make check && git worktree remove ../wt-t10-web && git branch -d task/t10-web

# lane 2
cd ../wt-t10-demo && make check
git add -A && git commit -m "feat(demo): headless interview script (T10)"
cd <repo> && git switch master
git merge --no-ff task/t10-demo -m "feat(demo): headless interview script (T10)"
make check && git worktree remove ../wt-t10-demo && git branch -d task/t10-demo

# lane 3 — opened only now
git worktree add ../wt-t10-docs -b task/t10-docs master
# ... regenerate diagrams, fill the configuration table, write the ADRs
cd ../wt-t10-docs && make check
git add -A && git commit -m "docs: diagrams, configuration table and ADRs against the code as built (T10)"
cd <repo> && git switch master
git merge --no-ff task/t10-docs -m "docs: diagrams, configuration table and ADRs against the code as built (T10)"
make check && git worktree remove ../wt-t10-docs && git branch -d task/t10-docs
```

Merged straight onto `master` — no pull request, no integration branch. After the
sweep lands, run the full PRD §12 verification on `master` itself: the four
drills (durability, adapter swap, passkey, evaluation replay) are claims the
README makes, so they are proven on the trunk, not on a branch.

```bash
git worktree list             # expect only the main checkout
git branch                    # expect only master
```
