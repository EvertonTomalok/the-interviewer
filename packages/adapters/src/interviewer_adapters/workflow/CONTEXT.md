# interviewer_adapters/workflow

**Responsibility** — the durable-workflow port's adapters (PRD §5). `base.py`
is the step template every step is written through once; `inline.py` runs a
workflow's steps in-process (the test engine and the local-dev engine).
`turn_steps.py` and `evaluation_steps.py` are the two concrete workflows:
`turn` (`persist_audio -> transcribe -> compose -> synthesize ->
commit_turn`) and `evaluation` (`collect_answers -> score -> commit_report`),
registered beside each other, run by the exact same engine.
`redis_streams.py` and `temporal.py` (T07b) are not yet in this branch.

**Public surface** — `BaseStep`, `StepRecordStore`, `InMemoryStepRecordStore`,
`build_turn_steps(...)`, `build_evaluation_steps(...)`, `build_history(...)`,
and `InlineWorkflowEngine` (a composition root, not yet built, wires these).
A real `WorkflowEngine` is never imported by name — a caller reaches one
through `interviewer_core.registry.require_spec("workflow",
settings.workflow_provider).build(settings, workflows=..., run_repo=...,
records=..., clock=..., ids=..., fail_at=...)`. `workflow`'s `build` takes
more than `settings` (unlike every other adapter kind) because a workflow
engine needs the assembled steps and repositories, not just credentials —
that assembly is the composition root's job (T09), not this module's.

**Depends on** — `interviewer_core.ports.workflow`, `.repositories`,
`.speech`, `.storage`, `.llm`, `.clock`, `.ids`; `interviewer_core.domain`;
`interviewer_core.engine` (`TurnPipeline`, `evaluate`); `interviewer_core.errors`;
`interviewer_core.registry`.

**Invariants** — the four of PRD §5.2, each enforced in a specific place:

1. **Idempotent start** — `InlineWorkflowEngine.start()` looks up the run by
   `idempotency_key` first; a second `start()` with the same key returns the
   same run, never a second one. Prevents a double-tap on send from opening
   two runs for one turn.
2. **Deterministic replay** — `BaseStep.run()` reads only `ctx.input` and
   `ctx.outputs`; `reply_mode` is captured once into `ctx.input` at the
   caller's `start()`, never read live from `Settings` inside a step.
   Prevents a flag flip mid-flight from changing what a replay produces.
3. **Checkpoint before ack** — `BaseStep.execute()` (the template method)
   saves the step's output to `StepRecordStore` *before* returning it; the
   engine only advances past a step once that save has completed. Prevents
   at-least-once delivery from re-paying for (or re-writing) a step that
   already succeeded.
4. **Classified failure** — `InlineWorkflowEngine._drive()` catches
   `PortError` around `step.execute()`: `transient=True` and attempts under
   `step.max_attempts` retries with jittered backoff; anything else fails the
   run at once, `run.error` names the step. Prevents an unclassified retry
   loop from hammering a permanently-broken dependency.

**Where to change what** — add a workflow step → a new `BaseStep` subclass in
`turn_steps.py`/`evaluation_steps.py` (or a new file, for a third workflow),
appended to the matching `build_*_steps()` tuple; the template method never
changes. Add an engine → a new module here registering
`kind="workflow"`, plus one import line appended to this package's
`__init__.py` and to `interviewer_adapters/__init__.py`.

**Traps** — the two `Turn` rows a round produces share no speaker field on
the frozen domain (T02); this lane assigns them by index parity off
`ctx.input["turn_index"]` (n): candidate = `2n`, interviewer = `2n + 1`.
`build_history()` depends on this convention to reconstruct `HistoryTurn`
pairs — a caller that writes turns any other way breaks both the evaluator
and the next `compose` call's context. `commit_report` requires the session
already be in phase `evaluating` (`advance(..., "complete")` raises
otherwise) — the caller (T09's Finish endpoint) must apply
`start_evaluation` and persist it *before* starting the evaluation workflow.
`StepRecordStore` has only an in-memory implementation in this branch; a
worker restart against `WORKFLOW_PROVIDER=inline` does not survive across
process boundaries yet — a SQL-backed store is a T07b/T09 gap, not built
here. `SimulatedCrash` is a test-only escape hatch (`fail_at`); production
code never raises it and never catches it.
