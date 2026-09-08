# T07 — Durable workflow: contract suite, `inline`, `redis_streams`

**Wave 2 · depends on T02, T05 · split into T07a (blocking) and T07b (not) · covers PRD §11 T9–T10**

> **T07a is on the critical path — start it first in wave 2.** The API, the
> worker and the whole unit suite run on `inline`; T09 blocks on it. **T07b
> blocks nothing in wave 3** — it lands inside wave 2 against the same contract
> suite, and T09 is built and demoed on `inline`. It is still not optional: T09's
> last done-when is one turn end to end on `WORKFLOW_PROVIDER=redis`, and that is
> the criterion this half makes tickable. Splitting them is what keeps the
> critical path one wave shorter.

```bash
# T07a — the blocker: template method, invariants, contract suite, inline engine
git worktree add ../wt-t07a-inline -b task/t07a-workflow-inline master

# T07b — opened once T07a has landed; the second half of wave 2
git worktree add ../wt-t07b-redis  -b task/t07b-workflow-redis  master
```

**Owns:** T07a — `packages/adapters/src/interviewer_adapters/workflow/{base,inline}.py`,
`tests/contract/workflow/**`, the module `CONTEXT.md`. T07b —
`workflow/redis_streams.py`, `workflow/temporal.py`. Both **append only** to
`interviewer_adapters/__init__.py` and `.env.example`.

Build `inline` **first**, with the whole contract suite green, and only then
`redis_streams` against the *same* suite. Writing the Redis adapter first means
debugging determinism and a stream protocol at once.

## Reference in this repo

| Read | For |
|---|---|
| `packages/shared-py/src/ama_shared/queues.py` | queue names as configuration shared by producer and consumer — a divergent name sends jobs to a queue nobody drains, silently |
| `packages/shared-py/src/ama_shared/dlq.py` | a dead letter that is a place a human reads, with the failing step and the error kept, never auto-drained |
| `packages/shared-py/src/ama_shared/db/leases.py` | claiming work with a lease and reclaiming it after a timeout — the Postgres shape of what `XAUTOCLAIM` does over Redis |
| `packages/shared-py/src/ama_shared/retry.py` | exponential backoff with jitter, and a retry that decides from a classified error rather than a status code |
| `apps/worker/src/ama_worker/worker.py`, `run.py`, `reply_worker.py` | a long-running consumer: startup, the drain loop, structured logging per job, graceful shutdown |
| `packages/agentkit-py/src/agentkit/ports/clock.py` | why the clock is injected: a step that reads wall time is a step that cannot be replayed |

## Deliverables

### The step template (Template Method) — **T07a**

`WorkflowStep.execute()` is written **once**, in the base, and no step overrides
it:

```
execute(ctx):
    record = load_step_record(run_id, self.name)
    if record.status == "succeeded":
        return record.output          # memoized — never re-paid
    output = await self.run(ctx)      # the only part a step author writes
    checkpoint(run_id, self.name, output)   # committed BEFORE any ack
    return output
```

That is where determinism is enforced for every step, forever.

### The four invariants (PRD §5.2), each with a test — **T07a**

1. **Idempotent start** — the same `idempotency_key` returns the same run. For a
   turn the key is `f"{session_id}:{turn_index}"`.
2. **Deterministic replay** — a step reads only `ctx.input` and `ctx.outputs`.
   No clock, no random, no repository read a previous step could have written.
   `Clock` is injected; "now" arrives as a value.
3. **Checkpoint before ack** — the step record is committed to Postgres before
   the message is acknowledged. On restart the engine replays from the first
   step with no record. This is what makes at-least-once delivery safe.
4. **Classified failure** — `PortError.transient` retries with backoff and jitter
   up to `max_attempts`; anything else fails the run at once and lands in the DLQ
   with the step name and the error.

### The five steps of PRD §5.4 — **T07a**

`persist_audio` → `transcribe` → `compose` → `synthesize` → `commit_turn`.

`persist_audio` does **not** upload anything: the API already wrote the bytes
inside the request, under a staging key built from `session_id` and `turn_index`
(T09), because that is the only moment they exist. The step turns that reference
into the durable `Artifact` row — mime, size, checksum — and returns its id, so a
replay finds the row memoized instead of writing a second one for the same bytes.

**One workflow for every phase.** The intake turn (the candidate's name) and a
question turn run the *same* five steps; only what `compose` returns differs.
The **phase** is captured into `ctx.input` at `start()` alongside `reply_mode`,
for the same reason: a session that moved on while a run was in flight must not
change what a replay produces. A separate intake workflow would be a second set
of durability guarantees to test, for one prompt's difference.

Five, not six: there is **no `retrieve` step**, because the PoC has no corpus —
the persona's questions and expected answers travel in `ctx.input` with the run.
`compose` carries the degradation instead: if the composed question fails its
guardrails twice, the step ships the persona's scripted `text` for that question
and marks the turn `degraded`. The interview continues and the reason is
recorded. Expansion `E1` inserts `retrieve` between `transcribe` and `compose`;
adding a step is what the step template exists to make cheap, so do not reserve a
slot for it now.

`commit_turn` is an idempotent upsert on `(session_id, index)` — belt (the step)
and braces (the unique constraint from T05).

**`synthesize` is skipped in the PoC, not removed.** The product is audio-in /
text-out: the candidate speaks, the interviewer writes. The step stays in the
list and, when `reply_mode == "text"`, returns
`{"skipped": true, "reason": "reply_mode=text"}`, which is checkpointed like any
other output.

Two rules make that safe:

- **`reply_mode` is read once, at `start()`, into `ctx.input`** — never from
  settings inside the step. A flag flipped mid-flight must not change what a
  replay produces; a step that reads configuration is the cheapest way to break
  invariant 2, and this is the step most likely to try.
- **The step list is identical in both modes.** No conditional pipeline, no
  second workflow. `REPLY_MODE=voice` changes what `synthesize` returns, nothing
  else, which is why the flip is a drill (PRD §12.5) and not a change request.

`commit_turn` writes the candidate turn with its transcript and audio artifact,
and the interviewer turn with the question text and `audio_artifact_id = NULL`
in text mode. It also writes what the phase produced: on an **intake** turn the
session's `candidate_name` and `name_confidence` and the move to `questioning`;
on the turn where the completion rule fires, the farewell turn
(`kind="closing"`) and the move to `closing`. Every turn carries its `kind`, and
the phase transition goes through the domain's `advance()` (T02) — a step does
not assign a phase, it asks for one.

### The evaluation workflow (PRD §5.5) — **T07a**

The second workflow, three steps: `collect_answers` → `score` → `commit_report`.
Same engine, same template, same guarantees — it is registered beside the turn
workflow, not special-cased.

- `collect_answers` reads **only `kind="question"` turns**. The name the
  candidate spoke in intake is context on the report, never a scored answer, and
  the farewell is not an answer at all.
- `idempotency_key` is `f"{session_id}:report"`, so **Finish** pressed twice
  joins the existing run.
- `score` is the expensive one: one model call over every question ↔ answer pair
  with its `expected_answer` and `weight`. Checkpointed like any other step, so a
  worker killed during `commit_report` replays without paying for scoring twice.
  If this step is not memoized, a crash costs the most expensive call in the
  product.
- The persona version comes from the **session**, through `ctx.input`, never from
  a live read — a persona published while the evaluation is in flight must not
  change the report, for the same reason `reply_mode` is pinned.
- `commit_report` upserts on `session_id` and moves the session to `completed`.

### `inline.py` — **T07a**

Runs the steps in-process, in order, through the same `WorkflowStep` objects,
with an **injectable failure hook** (`fail_at(step, attempt)`). This is the test
engine and the local-dev engine — `WORKFLOW_PROVIDER=inline` runs a whole
interview with no Redis at all.

### `redis_streams.py` — **T07b**

Redis is **transport and lease**; Postgres is **the durable truth**. Flushing
Redis loses throughput, not history.

- one stream per workflow, a consumer group, `XADD` / `XREADGROUP` / `XACK`;
- lease recovery with `XAUTOCLAIM` on entries idle past
  `WORKFLOW_VISIBILITY_TIMEOUT_SECONDS`, so a worker killed mid-turn releases its
  work;
- delayed retry through a `ZSET` keyed by due timestamp, drained by the worker
  loop;
- a `:dlq` stream, never auto-drained;
- run and step state in `workflow_runs` / `workflow_step_records`.

### `temporal.py` — stub plus mapping doc — **T07b**

No implementation. A module docstring and an ADR recording the mapping:
`WorkflowStep` → Activity, `idempotency_key` → Workflow Id with a
reject-duplicate policy, `max_attempts` → RetryPolicy. It exists so the port
cannot quietly drift into something Temporal could not implement. Real
implementation is expansion `E2`.

## Tests

`tests/contract/workflow/` is parametrised over **both** engines. `inline` runs in
`make check`; `redis_streams` carries the `integration` marker.

- **Crash after step *k*, for every *k***: restart and assert (a) no completed
  step ran twice, (b) exactly one `Turn` at that index, (c) the terminal state
  equals the uninterrupted run's.
- Same `idempotency_key` twice → one run, one set of side effects.
- Transient failure retries to the ceiling then lands in the DLQ; permanent
  failure lands there on the first attempt, with the step name.
- A step that calls the real clock fails the determinism test — write that test
  so a future step author is caught.
- **Both workflows** run through the same contract suite: crash-after-step-*k*,
  idempotent start and DLQ behaviour are asserted for the evaluation workflow
  too. A second workflow that skips the suite is a second set of guarantees
  nobody checked.
- The evaluation run replayed after `commit_report` produces **one** report and
  does not call the model again.
- **Both reply modes, parametrised over the same suite**: `text` asserts
  `synthesize` checkpointed a skip and the interviewer turn has no artifact; `voice` (on
  `FakeTTS`) asserts the artifact exists. Same steps, same count, same terminal
  state.
- A run started under `text` and replayed after `REPLY_MODE` was flipped to
  `voice` still produces the text outcome — the mode came from `ctx.input`. This
  is the test that catches a step reading settings.
- **Phase**: an intake run writes `candidate_name` and moves the session to
  `questioning`; a run whose `compose` hits the completion rule writes a
  `closing` turn with the persona's farewell and moves the phase; replaying
  either one does neither twice. A run started in `intake` and replayed after the
  session already moved on still produces the intake outcome — same invariant,
  same failure mode as the reply mode above.
- `redis_streams` only: a consumer killed while holding an entry has it reclaimed
  by another after the visibility timeout, with no duplicate turn.

## Done when

- Both engines pass **the same** contract suite.
- Killing a worker mid-run and restarting it resumes with no re-run and no
  duplicate turn (drill in PRD §12.4).
- `workflow/CONTEXT.md` lists the four invariants under **Invariants**, each with
  the failure it prevents, and answers "add a workflow step → here".

## Land it — two merges, in order

**T07a first.** It is the blocker: nothing in wave 3 opens until it is on
`master`.

```bash
cd ../wt-t07a-inline
make check
git add -A && git commit -m "feat(workflow): durable step contract and inline engine (T07a)"

cd <repo>
git switch master
git merge --no-ff task/t07a-workflow-inline -m "feat(workflow): durable step contract and inline engine (T07a)"
make check
git worktree remove ../wt-t07a-inline && git branch -d task/t07a-workflow-inline
```

**T07b afterwards**, branched off the `master` that now carries T07a, and built
while wave 3 opens on `inline` — wave 2 closes when this lands:

```bash
git worktree add ../wt-t07b-redis -b task/t07b-workflow-redis master
# ... work, then:
cd ../wt-t07b-redis && make check
git add -A && git commit -m "feat(workflow): redis streams adapter with lease recovery and dlq (T07b)"

cd <repo>
git switch master
git merge --no-ff task/t07b-workflow-redis -m "feat(workflow): redis streams adapter with lease recovery and dlq (T07b)"
make check
git worktree remove ../wt-t07b-redis && git branch -d task/t07b-workflow-redis
```

Merged straight onto `master` — no pull request, no integration branch. The
`integration`-marked Redis suite is not part of `make check`; run it explicitly
against `docker compose` before landing T07b.
