# packages/core

**Responsibility** — the pure domain, the interview engine and the port
catalogue: `Session`/`Turn`/`Persona`/`Artifact`/`InterviewInvite` and their
state machines, every `typing.Protocol` an adapter implements, the provider
registry, settings and logging. It owns zero I/O — no database, no HTTP
client, no queue.

**Public surface** — `interviewer_core.domain` (entities, `SessionPhase`,
`advance()`), `interviewer_core.ports` (`LLMPort`, `SpeechToTextPort`,
`TextToSpeechPort`, `BlobStore`, the nine repository Protocols,
`WorkflowEngine`/`WorkflowStep`/`StepContext`, `Clock`/`SystemClock`/`FrozenClock`,
`IdGenerator`/`Uuid7Ids`/`SeqIds`), `interviewer_core.registry`
(`ProviderSpec`, `register`, `require_spec`, `known_providers`),
`interviewer_core.config.load_settings`, `interviewer_core.logging.get_logger`,
`interviewer_core.errors` (`ConfigError`, `PortError`, `DomainError`),
`interviewer_core.engine` (`TurnPipeline`, `TurnRequest`/`TurnOutcome`/
`HistoryTurn`, `evaluate`).

**The engine** (`interviewer_core.engine`) is one candidate turn, decided
against fakes only — no adapter, no Redis, no database anywhere in this
package. `TurnPipeline.run()` is a Chain of Responsibility with three
stages, always in this order:

1. **route** (`pipeline.py`, `_run_intake`/`_run_questioning`) — reads
   `session.phase` and decides what this turn even is. It can end the chain
   here: an intake turn with no name found re-asks (once) or falls back to
   the trimmed transcript; a questioning turn whose answer completes
   coverage returns the persona's `farewell_text` verbatim, no further call.
   Otherwise it resolves *which* `PersonaQuestion` comes next — a fresh one
   or a follow-up — via `policies.policy_for(persona.policy)`.
2. **compose** (`pipeline.py`, `_compose`; prompts in `prompting.py`) — one
   `LLMPort.complete` call that rewrites the chosen question against the
   persona's tone and history.
3. **guard** (`guardrails.check_question`) — deterministic, in code. A
   failure regenerates once (`_compose` again, with an amendment); a second
   failure falls back to the question's authored `text` and marks the turn
   `degraded`.

Coverage bookkeeping (`coverage.py`) is a fourth, cross-cutting concern read
and written by both `route` and `guard`: `assess_answer` scores a reply
deterministically (vocabulary overlap with `expected_answer` — no model
call), `completion_reason` is the single place the two end conditions
(`min_coverage`, `max_questions`) are checked, and `question_numbers` is
what the page's "3 of 8" comes from — always derived from `coverage`, never
a counter passed in.

The evaluator (`evaluator.py`, `evaluate()`) is a separate, one-shot
function — not part of `TurnPipeline` and not called by it. It takes the
finished `history`, asks the model once for a verdict on every answered
question, validates the response against a closed vocabulary
(`_VERDICTS`), and computes `overall_score` itself, as a weight-weighted
mean over `persona.questions` — never asked of the model.

**Depends on** — nothing outside the standard library and `pydantic`
(including `pydantic-settings`). Not `sqlmodel`, not `httpx`, not `redis`,
not any adapter package.

**Invariants** — this package imports nothing outside the standard library,
`pydantic`, or itself; a unit test walks its AST and fails, naming the
offending import, if that is violated. No provider name appears anywhere in
this package. No `if/elif` dispatches on a provider slug — the registry does.

**Where to change what** — a new external concern → a `Protocol` in `ports`
plus its fake; a new entity or state transition → `domain`; a new provider
kind → a row in `registry`'s vocabulary, not a branch; logging or settings
shape → `config` / `logging`; **a new question policy** → a class
implementing `engine.policies.QuestionPolicy` plus one line in
`engine._POLICIES` — never a branch on `persona.policy`; **a new pipeline
stage** → `engine.pipeline.TurnPipeline`, inserted in the `route -> compose
-> guard` chain at the point its cost belongs (cheapest checks end the turn
first); **change how an answer is scored** — a turn's live coverage
confidence is `engine.coverage.assess_answer`, the finished interview's
per-question verdict is `engine.evaluator._parse_scores`, and the
`overall_score` weighting is `engine.evaluator._weighted_mean`.

**Traps** — `pydantic-settings`'s import name is `pydantic_settings`, not
`pydantic`; it is allowed here deliberately (see
`docs/adr/0002-core-logging-without-structlog.md` for the logging half of
this same boundary). `sqlmodel` looks like a pydantic library and is not
one of the two allowed imports — the purity test names it specifically
because it is the mistake most likely to slip past a quick read. **The
interviewer's own prompt (`engine.prompting.build_question_messages`) must
never carry a question's `expected_answer`** — only
`build_evaluator_messages` may. A model told the answer while it is still
asking the question asks it badly and often leaks it; `test_prompting.py`
and `test_pipeline_questioning.py` both assert this directly.
