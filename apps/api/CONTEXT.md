# apps/api

**Responsibility** — the FastAPI entrypoint: HTTP routers, request/response
schemas, the auth dependency (admin JWT and session-scoped candidate
tokens), and the composition root that builds every port's real adapter from
settings. It computes nothing itself — a route validates the request, calls
one port or one engine function, and returns the uniform response envelope.

**Public surface** — the ASGI app at `interviewer_api.main:app`; nothing else
is meant to be imported from outside this app.

**Depends on** — every port in `interviewer_core.ports`, built by this app's
own `deps.py` from `interviewer_core.config` settings and
`interviewer_core.registry.require_spec`.

**Invariants** — `POST /session/turns` stores the upload and enqueues a run;
it never transcribes, composes or scores inside the request. Every route
except `/auth/*`, `/healthz` and `/readyz` requires a valid bearer token,
checked by one dependency, not by convention per-route.

**Where to change what** — a new route → a router module plus a line in the
app's router registration; a new setting the API reads → `deps.py`, appended,
never reordered; auth rules → the one auth dependency, not duplicated per
router.

**Traps** — `/healthz` and `/readyz` exist today and answer `200` with no
dependency check behind them; a real readiness check (Postgres, Redis) is the
auth/worker task's job, not a reason to treat the current stub as done.
