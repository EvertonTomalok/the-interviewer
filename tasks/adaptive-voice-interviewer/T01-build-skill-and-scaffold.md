# T01 — `build` skill, documentation system, scaffold

**Wave 0 · depends on nothing · parallel with nothing · covers PRD §14 + §11 T1–T2**

```bash
git worktree add ../wt-t01-build -b task/t01-build-skill master
```

**Owns:** `.claude/skills/build/**`, `README.md`, `ARCHITECTURE.md`, `AGENTS.md`,
`docs/**`, `scripts/docs_check.py`, `Makefile`, root `pyproject.toml`,
`docker-compose.yml`, `Dockerfile`, `.env.example`, package skeletons.

## Why this is first

The `build` skill is the procedure **every later task is executed with**. Writing
it after the code would make it a description of what happened instead of a rule
that shaped it. Same for the docs: a `CONTEXT.md` template that exists on day one
gets filled by each lane in its own branch; one written at the end gets filled by
whoever is left, from memory.

## Reference in this repo

| Read | For |
|---|---|
| `.claude/skills/debugger/SKILL.md`, `.claude/skills/dev-seed-from-prod/SKILL.md` | the shape of a skill: front-matter, a numbered procedure, and the refusal to skip steps |
| root `Makefile` | targets that compose (`check` chaining lint + types + tests), a single entrypoint for every command a person or CI runs; keep the habit, add `docs-check` to the chain |
| root `pyproject.toml` | `uv` workspace declaration with Python-only members, shared `ruff`/`mypy`/`pytest` config in one place |
| `docker-compose.yml` | postgres + redis for local dev: named volumes, healthchecks, and app services that wait on `service_healthy` rather than on luck |
| `CLAUDE.md` (this repo, root) | what an `AGENTS.md` is for: the rules an assistant must not rediscover — English identifiers, no direct `os.environ`, ports before adapters |

## Deliverables

### 1. Workspace scaffold

```
pyproject.toml            # uv workspace: packages/core, packages/adapters, apps/api, apps/worker
Makefile                  # the only entrypoint anyone types (§3 below)
docker-compose.yml        # postgres + redis + api + worker (§2 below)
.env.example              # PRD §6, every key present, values empty except
                          # LLM_PROVIDER=fake, STT_PROVIDER=fake (a keyless first run),
                          # REPLY_MODE=text, TTS_PROVIDER=none (the PoC shape),
                          # STORAGE_PROVIDER=local_fs and the passkey limits
.dockerignore .gitignore
packages/core/            # empty package + CONTEXT.md
packages/adapters/        # empty package + CONTEXT.md
apps/api/  apps/worker/               # each with a CONTEXT.md
apps/web/                 # CONTEXT.md + interview.html (public) + admin.html
docs/adr/0001-hexagonal-at-this-size.md
scripts/docs_check.py
alembic.ini               # migration config only; the chain itself is T05's
Dockerfile                # one image, two commands (api / worker) — same code, same deps
```

Config fixed now, once, for everyone: Python 3.12+, `from __future__ import
annotations` everywhere, `ruff` line length 100, `mypy --strict`,
`pytest-asyncio` in auto mode, `T | None` over `Optional[T]`, `uv` for every
install. Each worktree gets its own `.venv` — that is why `make install` exists.

**The workspace enforces the boundary before any test does.** `packages/core`
declares exactly one runtime dependency — `pydantic` — and `packages/adapters`
is where `sqlmodel`, `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `httpx` and
`redis` live. Core cannot import SQLModel because core cannot resolve SQLModel:
the AST purity test of T02 then catches the day somebody adds it to the wrong
`pyproject.toml`.

### 2. `docker-compose.yml` — run it locally

Two service groups. **Dependencies come up alone by default**; the app services
sit behind a profile, because the normal inner loop is `make dev` on the host
against containerised Postgres and Redis, and the full stack is for the
end-to-end drills.

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment: [POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB=interviewer]
    ports: ["5432:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck: pg_isready -U $$POSTGRES_USER      # interval 5s, retries 10

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes          # AOF: a restart must not lose a pending entry
    ports: ["6379:6379"]
    volumes: [redisdata:/data]
    healthcheck: redis-cli ping

  api:
    profiles: ["app"]
    build: .
    command: uvicorn interviewer_api.main:app --host 0.0.0.0 --port 8000
    env_file: .env
    environment:
      DATABASE_URL: postgresql+asyncpg://.../interviewer   # container hostnames, not localhost
      REDIS_URL: redis://redis:6379/0
      STORAGE__LOCAL_FS__ROOT: /var/blobs
    ports: ["8000:8000"]
    volumes: [blobs:/var/blobs]                     # shared with the worker on purpose
    depends_on: {postgres: {condition: service_healthy}, redis: {condition: service_healthy}}

  worker:
    profiles: ["app"]
    build: .
    command: python -m interviewer_worker
    env_file: .env
    environment: (same three overrides as api)
    volumes: [blobs:/var/blobs]
    depends_on: {postgres: ..., redis: ..., }

  minio:
    profiles: ["storage"]                           # only the swap drill needs it
    image: minio/minio
    command: server /data --console-address ":9001"
    environment: [MINIO_ROOT_USER, MINIO_ROOT_PASSWORD]
    ports: ["9000:9000", "9001:9001"]
    volumes: [miniodata:/data]
    healthcheck: mc ready local

volumes: {pgdata: {}, redisdata: {}, blobs: {}, miniodata: {}}
```

Five things that are decisions, not boilerplate:

- **Healthchecks with `depends_on: condition: service_healthy`.** Without them
  the API boots before Postgres accepts connections and the first `make dev`
  after a `compose up` fails for a reason that has nothing to do with the code.
- **Redis with AOF on.** Redis is transport and lease (PRD §5.3), and a restart
  that drops pending stream entries turns the durability drill into a test of
  luck. Postgres stays the truth either way.
- **`blobs` is one volume mounted by both app services.** The API writes the
  candidate's upload inside the request and the worker writes anything the run
  produces (the reply audio in voice mode); either process may stream a file
  back. With `STORAGE_PROVIDER=local_fs` they must see the same directory, or
  every playback 404s. Write that reason in a comment — it is the first thing
  someone breaks when they split the services.
- **MinIO sits behind the `storage` profile.** It is off in the normal loop and
  up for one job: `STORAGE_PROVIDER=s3` with `STORAGE__S3__ENDPOINT_URL` pointed
  at it (T06), so the adapter-swap drill of PRD §12.5 is something a reviewer runs
  in a minute instead of something they take on faith with an AWS account.
- **The app services are behind the `app` profile**, so `docker compose up -d`
  starts only Postgres and Redis. The full stack is `--profile app`, which is
  what the durability drill (`docker kill` on the worker) needs.

### 3. `Makefile` — the only entrypoint anyone types

Every command in the README is a `make` target. Nobody memorises a `uv run
pytest -k ...` incantation, and CI runs the same targets a person runs.

| Target | Does | Notes |
|---|---|---|
| `install` | `uv sync --all-packages` | per-worktree `.venv`; run it right after `git worktree add` |
| `fmt` | `ruff format` + `ruff check --fix` | the only formatter |
| `lint` | `ruff format --check` + `ruff check` | what CI runs; never rewrites files |
| `types` | `mypy --strict` over packages and apps | |
| `test` | `pytest -q` | **no network, no containers** — the port layer is what makes this true |
| `cov` | `pytest --cov --cov-fail-under=80` | the 80% floor is enforced here, not by review |
| `itest` | `pytest -m integration` | real Postgres + Redis; **never part of `check`** |
| `docs-check` | `python scripts/docs_check.py` | §6 below |
| `check` | `lint types cov docs-check` | the gate. Green before every merge to `master` |
| `up` / `down` | `docker compose up -d` / `down` | dependencies only |
| `stack` | `docker compose --profile app up -d --build` | api + worker + deps, for the drills |
| `migrate` | `alembic upgrade head` | needs `up` first |
| `seed` | create the admin user, a demo area, one persona version (greeting + intake + farewell + questions + expected answers + rubric) **and one invite — printing the public link and its passkey** | what makes `make dev` usable in one minute: the last line of output is the URL you paste into a browser to be interviewed |
| `dev` | api with `--reload` **and** the worker, on the host | one command, two processes; Ctrl-C stops both |
| `demo` | `python scripts/demo.py` | the headless interview (T10) |
| `logs` | `docker compose logs -f` | |
| `clean` | drop `.venv`, caches, `var/blobs` | never touches the volumes |

Rules for the file itself: `.PHONY` on every target; one target does one thing
and composes the others; **no target hides a failure** (`set -e` semantics, no
`|| true`); `check` must be runnable on a clean clone with nothing but `uv` and
Python installed.

### 4. Four commands to a running interview

The README's second section promises this, so the scaffold must deliver it
before any feature exists:

```bash
cp .env.example .env && $EDITOR .env    # optional: one LLM key, one STT key
                                        # untouched, it runs on the `fake` slugs
make install && make up && make migrate && make seed
make dev                                # http://localhost:8000
# `make seed` printed an interview link and its passkey — open that link
```

Two accounts at most, and only one of them is required. The PoC is **audio-in,
text-out**: the candidate speaks (STT), the interviewer writes (no TTS), so
`.env.example` ships `REPLY_MODE=text` and `TTS_PROVIDER=none` with no TTS key to
fill.

`make dev` must work with **no provider account at all.** `.env.example` ships
`LLM_PROVIDER=fake` and `STT_PROVIDER=fake` (T03, T04 register both slugs), so a
clean clone conducts a whole scripted interview before anyone signs up for
anything; filling the two keys and flipping the slugs is what makes it a real
one. The page says which providers are fake, in a banner — that is **not** the
`degraded` flag, which means one thing only: a guardrail fallback fired (T08). A
setup path that requires three provider accounts before anything runs is a setup
path nobody completes.

`make dev` also starts the **worker**, not only the API. `POST /session/turns`
returns `202` and the work happens on the Redis stream; an API started alone
leaves every run `queued`, which is correct behaviour and a confusing first five
minutes — so the target starts both and says so.

**`make seed` ends by printing the invite.** The candidate has no account
(PRD §8), so the only way into an interview is a link plus a passkey; a setup
that leaves someone hunting for how to log in has failed at the last step. Print
the URL and the passkey once, plainly, and say in the same breath that the
passkey is not stored and will not be shown again.

### 5. `.claude/skills/build/`

```
SKILL.md
references/
  context-template.md        # PRD §14.2, verbatim
  diagram-recipes.md         # the five Mermaid diagrams, and how to regenerate each
  worktree.md                # the protocol from tasks/.../README.md, as a checklist
  adding-a-provider.md       # one file + one import; never an if/elif
  adding-a-workflow-step.md  # step class, memo key, checkpoint, contract test
```

`SKILL.md` prescribes the eight-step loop, none skippable:

1. **Worktree** — `task/t<NN>-<slug>`, branched off the previous wave's tip.
2. **Read the map** — the target module's `CONTEXT.md` before its code.
3. **Port first** — a new seam is a Protocol before it is an implementation, and
   its fake before its adapter.
4. **Tests before implementation** — red, then green, on in-memory adapters, no
   network.
5. **Adapter** — real implementation, registered as data.
6. **Wire** — composition root, appended to, never reordered.
7. **Document** — the module's `CONTEXT.md`, any diagram the change invalidated,
   the README configuration table if a variable or slug moved.
8. **`make check`** — green in the worktree, then merge.

Step 7 is written in `SKILL.md` in those words: *a change is not done until the
docs it touched move with it, in the same branch.*

### 6. Documentation skeletons

#### `README.md` — the reviewer's twenty minutes

Ten sections, in this order, no others. A reviewer reads top to bottom and
stops when convinced; a section out of order costs them the argument.

| # | Section | What goes in it |
|---|---|---|
| 1 | **What it is** | three sentences: a candidate opens a public link with a passkey and is interviewed **by voice**, the interviewer replies **in text**, one versioned persona per area configures the questions and the expected answers, and the admin reads the score. No feature list |
| 2 | **Run it** | the four commands of §4 above, copy-pasteable, ending in the seeded interview link, plus what to expect on screen |
| 3 | **The loop** | one `sequenceDiagram`: browser → API → Redis stream → worker → STT → LLM → (TTS, dashed — text mode skips it) → browser, with the `202 + poll` hand-off visible, and **Finish** taking the same route to the evaluation run. It must be obvious that the API returns before the work starts |
| 4 | **Architecture at a glance** | the hexagon diagram plus the port table: port, real adapters, test adapter. This is the section the whole project exists to earn |
| 5 | **Configuration** | one table, every `.env.example` key: name, what it does, default, required or not. `docs-check` fails if a key or a registered provider slug is missing here |
| 6 | **Swap an adapter** | the four env flips, with the drill commands: `LLM_PROVIDER` openrouter ⇄ openai_compat, `WORKFLOW_PROVIDER` redis ⇄ inline, `STORAGE_PROVIDER` local_fs ⇄ gcs ⇄ s3, `REPLY_MODE` text ⇄ voice. Same interview, no code change |
| 7 | **Add a provider** | one file, one import line, one row in the configuration table. Show the `register(ProviderSpec(...))` call |
| 8 | **Testing** | `make check` runs with no network and no containers, and why that is a property of the design rather than a convenience. `make itest` for the container suite |
| 9 | **Deliberately not built** | PRD §2 non-goals — video, streaming, multi-tenancy, Temporal, spoken replies in the PoC, translation, typed answers, a score the candidate can see, and the knowledge base / retrieval / embedder — each with one line of why. An absence must read as a decision |
| 10 | **What comes next** | the PRD §11 expansions, `E1` first: a knowledge base and lexical retrieval, then an embedder behind the same port. One line each on where it attaches — a reader must see that the cut was planned, not forgotten |

Sections 1–2 and 8–10 are written **now**, in full: they do not depend on code.
Sections 3–7 get the headings, the diagram fences and a `<!-- filled in T10 -->`
marker. T10 fills them from the code as built, and `docs-check` is what notices
if they were not.

Every command in the README is a `make` target (§3). A README that tells someone
to run `uv run pytest --cov ...` is a README that goes stale the first time the
flags change.

#### The rest

- `ARCHITECTURE.md` — long form of PRD §3: port catalogue, pattern map, and the
  rule that the core imports nothing.
- `AGENTS.md` — English identifiers; ports before adapters; no provider name in
  the engine; no `if/elif` on a provider slug; tests before implementation;
  in-memory adapters in unit tests; no `os.environ` outside settings.
- `docs/adr/0001` — why hexagonal at this size. One page: context, decision,
  consequences, what would make us reverse it.
- A `CONTEXT.md` in every package and app directory, on the six-heading template
  (Responsibility / Public surface / Depends on / Invariants / Where to change
  what / Traps).

### 7. `scripts/docs_check.py`

Fails, naming the offender, when:

- a package or app directory has no `CONTEXT.md`;
- a `CONTEXT.md` is missing one of the six headings;
- a path inside a code span in any `README.md` or `CONTEXT.md` does not exist on
  disk;
- a slug from `known_providers()` is absent from the README configuration table,
  or an `.env.example` key is absent from it (this is the check that catches the
  adapter someone added and never documented — it stays tolerant until T03
  registers the first provider);
- a Mermaid block does not parse.

## Done when

- `make check` is green on the empty tree, `docs-check` included in the chain,
  with **no network and no containers**.
- `make install && make up && make migrate` works on a clean clone, and
  `docker compose ps` shows Postgres and Redis **healthy**, not merely started.
- `make stack` brings up api + worker + dependencies; both containers reach a
  healthy state and `/healthz` answers. (The routes are stubs until T09 — the
  point here is that the compose file, the image and the env wiring are right.)
- `make dev` starts the API and the worker on the host against the containerised
  dependencies, and Ctrl-C stops both without orphans.
- Invoking the `build` skill on a throwaway module produces a `CONTEXT.md` that
  `docs-check` accepts.
- `.env.example` carries every key of PRD §6 with empty values **except the
  defaults that must be non-empty** — `LLM_PROVIDER=fake`, `STT_PROVIDER=fake`,
  `REPLY_MODE=text`, `TTS_PROVIDER=none`, `STORAGE_PROVIDER=local_fs`,
  `PUBLIC_BASE_URL`, the upload guards and the passkey limits — and
  `cp .env.example .env` is enough to conduct an interview on the fakes.
- `make seed` prints a working interview link and its passkey as its **last
  line**, and opening that link in a browser reaches the passkey screen.
- Every command in the README is a `make` target, and every one of them runs.

## Land it — worktree → `master`

`make check` inside the worktree first. No network, no containers, so there is
no excuse to skip it.

```bash
cd ../wt-t01-build
make check                    # ruff, mypy --strict, tests, coverage, docs-check
git add -A && git commit -m "chore(build): build skill, docs system and workspace scaffold (T01)"

cd <repo>                     # the main checkout, always on master
git switch master
git merge --no-ff task/t01-build-skill -m "chore(build): build skill, docs system and workspace scaffold (T01)"
make check                    # green on the trunk, not only on the branch

git worktree remove ../wt-t01-build
git branch -d task/t01-build-skill
```

Merged straight onto `master` — no pull request, no integration branch. If
`make check` fails on the trunk after the merge, fix it on `master` at once:
every later lane branches off it.
