# 0002 — Core logging without structlog

## Context

`packages/core`'s purity test allows exactly the standard library, `pydantic`
(including `pydantic-settings`, used by `core/config`), and itself. A common
reference shape for this kind of settings/logging pairing uses `structlog`
for structured, redacted logging. `structlog` is not part of the pydantic
family and is not the standard library.

## Decision

`packages/core/src/interviewer_core/logging` implements structured, redacted
logging on the standard library's `logging` module: a JSON `Formatter` for
`LOG_JSON=true`, a key-value one for local dev, and a `Filter` that redacts
`authorization`, `api_key`, `passkey`, and any `*_key` / `*_token` field
before a record is emitted. It exposes the same shape a caller would expect
from a structured logger — `bind(**kwargs)` returning a logger that carries
that context on every subsequent call — without importing a framework into
the pure core.

## Consequences

- `packages/core` keeps its one-line dependency story: `pydantic` and the
  standard library. The AST purity test does not need a growing allowlist.
- Nobody who wants richer sinks (log shipping, sampling, OpenTelemetry
  correlation) is blocked — that wiring is an adapter's or an app's concern,
  layered on top of the same standard-library `Logger` instances, in
  `packages/adapters` or in an app's own bootstrap, never inside
  `packages/core`.
- The cost is reimplementing a handful of `structlog`'s ergonomics (bound
  context, JSON rendering) by hand, once, in `core/logging`, instead of
  taking them from a dependency.

## What would make us reverse it

If the purity rule itself changes — for instance, if the allowlist is
deliberately widened to a named set of pure, dependency-light libraries —
`structlog` could be reconsidered on the same terms. Until then, the
dependency-split rule in `packages/core`'s `CONTEXT.md` is the one this ADR
defers to.
