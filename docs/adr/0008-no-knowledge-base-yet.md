# ADR 0008: no knowledge base, no retrieval, no embedder — yet

## Status

Accepted. Scoped as expansion E1, not built.

## Context

The original PRD sketch (§1, §3.1) described three separable pieces per
area: a knowledge base, a persona, and an interview guide, with retrieval
grounding follow-up questions between `transcribe` and `compose`. What got
built is two pieces: `Area` and a versioned `Persona` that carries its own
`questions` (each with `topic`, `text`, `expected_answer`) directly. There is
no `KnowledgeDocument`, no `KnowledgeChunk`, no `KnowledgeRetriever` port, no
`retrieve` step in `turn_steps.py`.

## Decision

Ship the loop first on a persona that is *self-contained*: the question list
and its expected answers are the only grounding a turn needs. A fixed,
author-written interview guide does not need a corpus to search — it needs
someone to have written good questions, which is exactly what
`scripts/demo.py`'s seeded persona is meant to demonstrate.

Building the knowledge base now would mean a fifth port, a chunking
pipeline, and an area-scoping test (a document in area A must never surface
for area B) before any interview could run at all — real scope, for a
capability the fixed-question loop does not yet need.

## Consequences

- `compose` (`turn_steps.py`) reads the transcript, the persona, and
  coverage — never a retrieved passage. A follow-up question is only ever
  as deep as `follow_up_depth` allows on the same fixed question, never an
  adaptive probe grounded in outside material.
- **What would make us build it**: a persona whose questions need to
  reference material too large to fit in `expected_answer` text — a
  candidate asked to reason about a shared document, a codebase, or a
  policy corpus the interviewer must ground follow-ups in. That is the
  trigger for E1, in this order (README §10): a `KnowledgeRetriever` port
  with lexical (BM25-style) search first, a `retrieve` step inserted
  between `transcribe` and `compose` that degrades to empty and records
  that it did (matching the PRD §5.4 degrade-honestly rule every other
  step follows), then a vector adapter behind the same port
  (`RETRIEVAL_PROVIDER=vector`) with no engine change once the port
  exists.
- Until then, "no knowledge base" is a stated absence (README §9), not a
  half-built port nobody finished — there is no `retrieval/` adapter
  package, no stub to keep green.
