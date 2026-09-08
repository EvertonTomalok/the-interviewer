# T02 — Settings, logging, errors, domain, ports, registry contract

**Wave 0 · depends on T01 · parallel with nothing · covers PRD §11 T3–T4**

```bash
git worktree add ../wt-t02-core -b task/t02-core master
```

**Owns:** `packages/core/src/interviewer_core/**` (`config`, `logging`, `errors`,
`domain`, `ports`, `registry`), `packages/core/CONTEXT.md`, `packages/core/tests/**`.

**This task freezes the port layer for waves 1–3.** Four lanes start compiling
against these Protocols the moment it merges, so a Protocol that changes later
costs four rebases. Spend the time here.

## Reference in this repo

| Read | For |
|---|---|
| `packages/agentkit-py/src/agentkit/ports/` (`llm.py`, `clock.py`, `channel.py`, `capabilities.py`) | a port package that a pure engine imports: narrow Protocols, dataclass results, no provider vocabulary, no `httpx` |
| `packages/shared-py/src/ama_shared/llm/schemas.py` | a structured LLM result declared as a schema the caller owns — the shape the evaluator's per-question score, verdict and rationale needs (T08) |
| `packages/agentkit-py/src/agentkit/domain/envelope.py`, `turn.py` | frozen domain dataclasses carrying a turn's inputs and outputs, with no I/O |
| `packages/shared-py/src/ama_shared/config.py` | `BaseAppSettings` on `pydantic-settings`, `env_file` chain, per-app subclass. The new project adds the `__` nested delimiter for per-adapter credential blocks |
| `packages/shared-py/src/ama_shared/logging.py` | `structlog` JSON configuration done once, bound context instead of `print` |
| `packages/shared-py/src/ama_shared/errors.py` | a small exception hierarchy that the layers above can catch narrowly |
| `packages/shared-py/src/ama_shared/llm/providers.py`, `registry.py` | `ProviderSpec` as a frozen dataclass, `register` refusing a duplicate name, `require_spec` raising with the unknown slug in the message, `known_providers` feeding a UI. **Copy the shape, not the file** |
| `packages/shared-py/src/ama_shared/llm/credentials.py` | one credential dataclass for every provider, with an `extra` mapping instead of per-provider fields |
| `packages/agentkit-py/src/agentkit/ports/clock.py` | why "now" is a port: it makes replay deterministic and tests frozen |

## Deliverables

### `core/errors`

`ConfigError` (names the missing variable or the unknown slug),
`PortError(transient: bool, status: int | None)`, `DomainError`. No adapter ever
lets a provider exception escape; each maps onto `PortError`, and the workflow
reads `transient`, never a guessed HTTP status.

### `core/config`

`pydantic-settings` base, nested delimiter `__`, the full shape of PRD §6. No
module anywhere reads `os.environ`. A missing credential fails **at process
start**, naming the exact variable — the adapter knows its variable name, the
factory does not.

### `core/logging`

`structlog`, JSON in production, key-value in dev. Redaction list covers
`authorization`, `api_key`, **`passkey`**, and any `*_key` / `*_token` field. A
test asserts a secret passed through a bound logger does not appear in the
output — one case per redacted key, `passkey` included, because that one is
typed by a human into a public form and will end up in someone's debug line.

### `core/domain`

Every entity of PRD §4, frozen dataclasses, immutable updates (`replace`, never
mutation): `User`, `Area`, `Persona`, `InterviewInvite`, `Session`, `Turn`,
`Artifact`, `Coverage`, `InterviewReport`, `WorkflowRun`, `WorkflowStepRecord`.

**`Persona` is the only configuration entity** — there is no `InterviewGuide` and
no knowledge document. It carries the voice, the **authored** `greeting_text` /
`intake_prompt_text` / `farewell_text`, the question list
(`ref`, `topic`, `text`, `expected_answer`, `weight`, `follow_up_depth`), the
coverage rules and the scoring rubric. Model the question as a frozen
`PersonaQuestion` dataclass rather than a raw dict: the policy reads one half of
it and the evaluator reads the other, and a typo in a key must fail at
construction, not two steps later inside a prompt.

### The session phase machine

`SessionPhase` is a domain enum with the transition function beside it — this is
the shape of the interview (PRD §1) and it lives here, not in a router and not in
the browser:

```
created → intake → questioning → closing → evaluating → completed
                 ↘ abandoned            ↘ failed
```

`created` is the value of a session nobody has persisted yet: the claim writes
the row **already in `intake`**, inside the transaction that spends the invite
(T09), so no client ever observes a session in `created`. It exists so the
transition into `intake` is a move the machine made, not a default someone typed.

`advance(session, event) -> Session` returns a new session or raises
`DomainError` naming the illegal move. `Turn.kind` is
`Literal["intake", "question", "closing"]`, and only `question` is ever scored.

`candidate_name` and `name_confidence` live on the session and are written by the
intake turn's outcome — the domain exposes no way for a request body to set them.

### `InterviewInvite`

`slug`, `passkey_hash`, `expires_at`, `max_sessions`, `used_count`, `status`. Two
rules the domain enforces, so no route can forget them:

- **The plaintext passkey never enters the domain.** The dataclass holds a hash;
  the only constructor takes an already-hashed value, and there is no field, no
  `repr` and no `to_dict` that could carry the secret onward. A dataclass that
  cannot hold a secret cannot leak one into a log line.
- `is_claimable(now)` answers with a **reason** — expired, retired, exhausted —
  and the API maps every reason to one identical error (PRD §8), so the domain
  can be honest while the endpoint stays opaque.

Three rules with teeth:

- **A persona is versioned, never edited in place**, and a `Session` pins the
  version id it started with — as does the `InterviewReport`, which records what
  it was scored under. Tuning a persona at 10:00 cannot change what a session
  that began at 09:30 meant, nor what its report says.
- The phase machine above is the only way a session moves, and every illegal
  transition raises. A client that posts an answer after the farewell is refused
  by the domain, before any route has an opinion.
- `Coverage` is keyed by the persona question's `ref`, not by its index. A
  persona version is immutable, so the refs of a running session are stable —
  keying by position would make a stored coverage map meaningless the moment
  anyone reordered a question in the next version.

### `core/ports`

Every Protocol of PRD §3.2: `LLMPort`, `SpeechToTextPort`, `TextToSpeechPort`,
`BlobStore`, the nine repositories (including `InviteRepository`,
`ArtifactRepository` and `ReportRepository`), `WorkflowEngine` + `WorkflowStep` +
`StepContext`, `Clock`, `IdGenerator`.

`ArtifactRepository` is the row beside the bytes: `BlobStore` keeps the audio,
this keeps `mime`, `size_bytes`, `checksum` and the session it belongs to, which
is what `GET /session/artifacts/{id}` checks before streaming anything. Two
ports, on purpose — the metadata is queryable and the bytes are not.

`InviteRepository` needs one method that is not CRUD:
`claim(slug, now) -> Invite | None`, which checks and increments `used_count`
**atomically**. Two candidates opening the last slot at once is the kind of race
that only shows up in production, and it is the adapter's job (T05), not the
router's, to make it impossible.

**No retrieval port.** The PoC retrieves nothing, and a Protocol with no adapter
and no caller is a signature frozen before anything used it. Expansion `E1` adds
`KnowledgeRetriever` together with its lexical adapter and the workflow step that
calls it. Do not leave a stub here for it.

- Narrow — one to three methods each.
- No port retries, rate-limits, or prices anything. Those are decorators around
  the port (T03), so they stay observable and testable on their own.
- Ship `FrozenClock` and `SeqIds` here: the whole test suite depends on them and
  they are pure.

### `core/registry`

`ProviderSpec`, `register`, `require_spec`, `known_providers` — the contract
only. T03 registers the first real provider through it. `require_spec` on an
unknown slug raises `ConfigError` **naming the slug and listing the known ones**;
a misspelling in an env file must not fall silently into a default.

## Tests

- **Architecture test**: walk the AST of `packages/core`; fail if it imports
  anything outside the standard library, `pydantic`, or itself. Name the
  offending module and import. A boundary nobody checks lasts until the first
  deadline. `sqlmodel` is the import to watch here: it *looks* like pydantic and
  the persistence lane lives on it, so the test names it in the failure message
  rather than leaving a reader wondering why a model library is banned from the
  model layer.
- Phase machine: every legal transition, every illegal one rejected by name —
  including an answer in `closing` and a second `intake` after the name landed.
- Invite: `is_claimable` says expired / retired / exhausted with a reason; an
  invite dataclass carries no plaintext passkey and its `repr` proves it.
- Persona: a question missing `expected_answer` or `ref` fails at construction;
  duplicate refs in one persona are refused; a published version is immutable
  (`replace` returns a new object and the original is unchanged).
- Settings: missing credential → `ConfigError` naming the variable; unknown
  provider slug → `ConfigError` naming the slug.
- Logging redaction, as above.
- Registry: duplicate registration refused; unknown slug names itself.

## Done when

- `make check` green; coverage on `packages/core` well above the floor (it is
  pure code — there is no excuse).
- The architecture test fails loudly if someone adds `import httpx` to the core.
- `packages/core/CONTEXT.md` lists the port catalogue under **Public surface**
  and states under **Invariants** that the core imports nothing.

## Land it — worktree → `master`

`make check` inside the worktree first. No network, no containers, so there is
no excuse to skip it.

```bash
cd ../wt-t02-core
make check                    # ruff, mypy --strict, tests, coverage, docs-check
git add -A && git commit -m "feat(core): settings, errors, domain, ports and registry contract (T02)"

cd <repo>                     # the main checkout, always on master
git switch master
git merge --no-ff task/t02-core -m "feat(core): settings, errors, domain, ports and registry contract (T02)"
make check                    # green on the trunk, not only on the branch

git worktree remove ../wt-t02-core
git branch -d task/t02-core
```

Merged straight onto `master` — no pull request, no integration branch. If
`make check` fails on the trunk after the merge, fix it on `master` at once:
every later lane branches off it.
