# T08 — Interview engine and evaluator

**Wave 1 · lane E · depends on T02 · runs in parallel with T03, T04, T05, T06 · covers PRD §11 T11**

```bash
git worktree add ../wt-t08-engine -b task/t08-engine master
```

**Owns:** `packages/core/src/interviewer_core/engine/**`, `packages/core/CONTEXT.md`
(engine section), its tests.

This lane touches **`packages/core` only** and runs entirely on fakes — no
adapter, no Redis, no database. It is the one lane that can start the moment
wave 0 lands, and the reason it sits in wave 1 rather than wave 2: it depends on
nothing any sibling lane builds, and T09 blocks on it.

> **The persona is the whole configuration.** There is no interview guide and no
> knowledge base: the pinned persona version carries the authored greeting,
> intake prompt and farewell, the questions
> (`ref`, `topic`, `text`, `expected_answer`, `weight`, `follow_up_depth`), the
> coverage rules and the rubric. This lane builds **two** readers of that one
> object — the question policy, which decides what to ask next, and the
> **evaluator**, which scores the finished transcript against what each question
> expected. Retrieval is expansion `E1`; nothing here retrieves anything.

## Reference in this repo

| Read | For |
|---|---|
| `packages/agentkit-py/src/agentkit/engine/pipeline.py` | a turn as an ordered chain of stages where any stage may end the turn with a **reason**, and the reason is data the caller records |
| `packages/agentkit-py/src/agentkit/engine/composer.py`, `prompting.py` | building a prompt out of configuration + history, with the layers kept separate and each one testable |
| `apps/worker/src/ama_worker/prompts/` and its rubric YAMLs | a rubric that lives as versioned configuration and is never edited in place — the same reason the persona carries `rubric_json` and is published as a version |
| `apps/worker/src/ama_worker/` scoring path + `tests/calibration/` | an LLM asked for a **structured** verdict per criterion with a rationale, and hand-graded fixtures used as a regression gate on the rubric. The evaluator here is the small version of it |
| `packages/agentkit-py/src/agentkit/engine/router.py` | choosing a strategy from configuration rather than from a chain of `if`s about the request |
| `packages/agentkit-py/src/agentkit/engine/guardrails.py` | rules applied to a generated answer before it ships, each with a named verdict |
| `packages/agentkit-py/src/agentkit/engine/repetition.py` | detecting that the model is asking the same thing again — the interviewer version of it is a coverage problem |
| `packages/agentkit-py/src/agentkit/domain/turn.py` | the turn result carrying what happened *and* why, so the caller never has to infer it |

## Deliverables

### `TurnPipeline` (Chain of Responsibility)

`route → compose → guard`. Each stage takes the turn context and returns either
a continuation or a terminal outcome **with a reason**. A
stage that decides "no further question is needed" ends the chain **before** the
expensive one runs — that ordering is the point of the chain, not an accident.

### Phase rules — what a turn means depends on where the session is

`route` reads `phase` (from the workflow's `ctx.input`, T07) and picks the
behaviour. Three, and only three:

- **`intake`** — the answer is a name, not an answer. Extract it, return
  `{candidate_name, name_confidence}` and the **first question**. If the model
  finds no name, re-ask once with the persona's `intake_prompt_text`; if the
  second try also fails, take the trimmed transcript, mark
  `name_confidence="low"` and **move on**. Nobody's interview stops because a
  name was mumbled.
- **`questioning`** — the loop below.
- **completion fires** — return the persona's `farewell_text` verbatim and the
  request to move the phase to `closing`. No model call: it is authored text
  (T02), and the last thing a candidate hears should not be a generation that
  might go strange.

The greeting is not here at all — it is served straight from the persona at claim
time (T09), before any run exists. The first screen of the product costs nothing
and cannot fail.

### `QuestionPolicy` (Strategy)

`guided`, `adaptive`, `stress`, selected by the persona's `policy` field:

- `guided` — walk the persona's questions in order, one each;
- `adaptive` — pick the question with the weakest coverage, follow up while the
  answer is thin, up to that question's `follow_up_depth`;
- `stress` — push on the question the candidate answered most confidently.

Selection is a registry lookup, not an `if`. Adding a fourth policy is a new
class plus a registration.

### Coverage tracking

`Coverage` maps each persona question `ref` to `{asked, answered, confidence}`.
The policy reads it to choose the next question; the completion rule reads it to
end the session. A session ends when **either** every question reaches
`min_coverage` **or** `max_questions` is hit — whichever comes first, and the end
records **which** one fired.

Coverage also produces what the page shows: `question_number` and
`question_total`, so the candidate always knows they are on **3 of 8**. The
numbers come from the persona and the coverage map, never from a client counter —
a reloaded page must not restart the count.

### Prompt composition

Persona (tone, seniority, language) + the persona's questions and coverage rules
+ turn history → messages for `LLMPort`. Rules:

- the **pinned** persona version from the session, never the current one;
- the model rewrites and follows up on the persona's question; it does not invent
  a topic the persona never listed. The `question_ref` on the turn says which one
  it was serving, and that is what coverage is keyed by;
- **the `expected_answer` never enters the interview prompt.** It is the
  evaluator's input, not the interviewer's — a model that has been told the
  answer asks the question badly and often leaks it. Two readers of one persona,
  two different prompts;
- **no provider name, no model name, no `httpx`** anywhere in this package — the
  architecture test from T02 enforces it.

The pipeline's product is **question text**. It knows nothing about speech: no
audio, no voice, no `reply_mode`. Whether that text is spoken is decided one
layer out, by the workflow's `synthesize` step (T07), which is why the PoC's
text-out costs the engine exactly nothing — and why voice-out will too.

### Guardrails

Before a question ships: it is a question; it is not a near-duplicate of an
earlier one; it stays in the session language; it respects the persona's length
limit; it does not quote the `expected_answer`. A failed guardrail regenerates
once, then falls back to the persona's scripted `text` for that question rather
than shipping nothing — and the turn is marked `degraded`, which is the only
thing that flag means now that nothing is retrieved.

### The evaluator (PRD §5.5)

Pure, in this package, driven by `LLMPort` like everything else here. Input: the
session's turns and the **pinned** persona version. Output, as a domain object:

```
InterviewReport(per_question=[{ref, score, verdict, rationale, answered}],
                overall_score, summary)
```

- **Every question in the persona appears in the report.** One never reached is
  `answered=False`, scored zero with that as its stated reason, and stays in the
  denominator. Dropping it flatters the candidate and hides that the interview
  ended early.
- Scoring is **against `expected_answer` and `rubric_json`**, not against the
  model's own taste. The prompt gives the question, the expectation, the
  candidate's words, and asks for a score with a rationale — the rationale is a
  required field, because a number nobody can argue with is a number nobody can
  audit.
- `overall_score` is the `weight`-weighted mean over all questions. It is
  computed **in code, from the per-question scores**, never asked of the model:
  an LLM that both scores and averages will quietly disagree with itself.
- The verdict vocabulary is a `Literal`, and a response missing a `ref` or
  carrying an unknown one is a `DomainError`, not a shrug.

## Tests

All with a **scripted `FakeLLM`** — deterministic, no network:

- **intake**: a transcript of "hi, I'm Ana Ribeiro" yields `candidate_name="Ana
  Ribeiro"` and the first question; a transcript with no name re-asks once, then
  falls back with `name_confidence="low"` and still returns a question;
- **closing**: when the completion rule fires the outcome is the persona's
  `farewell_text` **verbatim**, with no model call — assert the fake was not
  asked;
- coverage advances: an answer covering question `q2` marks it, and the next
  question targets a different `ref`, and `question_number` advances with it;
- `max_questions` ends the session, and the end reason says so;
- `min_coverage` reached on every question ends the session, and the end reason
  says that instead;
- each policy, given identical state, picks a different and specified next
  question;
- guardrail: a duplicate question triggers one regeneration, then the scripted
  fallback, and the turn records `degraded=True`;
- **the interview prompt never contains an `expected_answer`** — assert it on the
  messages the fake received, because this one is invisible in the output;
- the pinned persona version is used even when a newer version exists.

Evaluator, same fake:

- the intake turn and the closing turn are **not** in the evaluator's input: a
  candidate who says something impressive while giving their name gains nothing,
  and a farewell is not an answer;
- an answer matching the expectation scores above one that misses it;
- a question never asked is reported `answered=False` with a reason, and still
  counts in `overall_score`;
- `overall_score` respects `weight`: doubling one question's weight moves the
  overall in the direction that question was scored;
- a model reply with an unknown `ref`, a missing rationale or a verdict outside
  the vocabulary raises `DomainError` rather than being coerced;
- the report records the persona version it scored under, and re-running the
  evaluation against a newer version does not change a stored report.

## Done when

- The whole engine suite runs on fakes, in milliseconds, with no I/O.
- The architecture test still passes — the engine added nothing impure.
- A full interview and its report run end to end on `FakeLLM`, before any
  provider exists.
- `packages/core/CONTEXT.md` documents the pipeline stages and answers "add a
  question policy → here", "add a pipeline stage → here" and "change how an
  answer is scored → here", and states under **Traps** that the interviewer
  prompt must never carry an `expected_answer`.

## Land it — worktree → `master`

`make check` inside the worktree first. No network, no containers, so there is
no excuse to skip it.

```bash
cd ../wt-t08-engine
make check                    # ruff, mypy --strict, tests, coverage, docs-check
git add -A && git commit -m "feat(engine): turn pipeline, question policies, coverage and evaluator (T08)"

cd <repo>                     # the main checkout, always on master
git switch master
git merge --no-ff task/t08-engine -m "feat(engine): turn pipeline, question policies, coverage and evaluator (T08)"
make check                    # green on the trunk, not only on the branch

git worktree remove ../wt-t08-engine
git branch -d task/t08-engine
```

Merged straight onto `master` — no pull request, no integration branch. If
`make check` fails on the trunk after the merge, fix it on `master` at once:
every later lane branches off it.
