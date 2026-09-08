# T03 — Provider registry + LLM adapters

**Wave 1 · lane A · depends on T02 · runs in parallel with T04, T05, T06 · covers PRD §11 T5**

```bash
git worktree add ../wt-t03-llm -b task/t03-llm-adapters master
```

**Owns:** `packages/adapters/src/interviewer_adapters/llm/**`, its `CONTEXT.md`,
its tests. **Appends only** to `interviewer_adapters/__init__.py`, `.env.example`,
and the README configuration table.

## Reference in this repo

| Read | For |
|---|---|
| `packages/shared-py/src/ama_shared/llm/registry.py` | registration as data: a dict keyed by `(kind, name)`, a `register` that refuses an existing owner, a `require_spec` that raises with the slug it did not find |
| `packages/shared-py/src/ama_shared/llm/factory.py` | a factory that builds from a spec and never branches on a provider name; the whole point is that adding a provider does not touch this file |
| `packages/shared-py/src/ama_shared/llm/builtins.py` | the module whose import registers the built-in providers, imported once from the package `__init__` so nobody has to remember to call anything |
| `packages/shared-py/src/ama_shared/llm/openrouter.py` | a real OpenRouter client: headers, base URL, error mapping, usage parsing |
| `packages/shared-py/src/ama_shared/llm/openai_compat.py` | the same contract against any OpenAI-shaped endpoint — this is the adapter that makes a take-home endpoint interchangeable with a hosted one |
| `packages/shared-py/src/ama_shared/llm/client.py`, `chat.py`, `models.py` | the Protocol the app code depends on, and the request/answer dataclasses that keep provider vocabulary out of callers |
| `packages/shared-py/src/ama_shared/llm/credentials.py` | uniform creds with an `extra` mapping; the adapter reads its own keys out of `extra`, nobody else does |
| `packages/shared-py/src/ama_shared/retry.py` | retry with exponential backoff and jitter as a **decorator**, so the adapter stays a thin transport |
| `packages/shared-py/src/ama_shared/llm/catalog.py` | how a model catalogue with per-model limits and prices hangs off a spec without leaking into the engine |

## Deliverables

### Registry implementation

Fill in the `core/registry` contract T02 froze:

```python
register(ProviderSpec(kind="llm", name="openrouter", build=..., rate_per_minute=60))
require_spec("llm", slug)   # ConfigError naming the slug and the known ones
known_providers("llm")      # what the README table and any picker read
```

Adapters self-declare inside their own module. `interviewer_adapters/__init__.py`
imports them, so any import of the package leaves them registered. **Adding a
provider is one new file plus one import line — never an edit to a dispatch.**

### `openrouter` and `openai_compat`

Both implement `LLMPort.complete(messages, tools?) -> LLMAnswer` over
`httpx.AsyncClient`. Differences (auth header, referer/title headers, model
naming) live inside the adapter and nowhere else. Both:

- read credentials from `ProviderCreds`; a missing key raises `ConfigError`
  naming the exact env var (`LLM__OPENROUTER__API_KEY`, …);
- parse usage (prompt/completion tokens) into the answer, so T09's run logs and
  the cost accounting of expansion `E4` has something to read;
- map transport and status failures onto `PortError(transient=…, status=…)`.
  429 and 5xx are transient; 400 and 401 are not. **Nothing above the adapter
  ever sees an `httpx` exception.**

Both providers must accept the same `LLM_MODEL` value shape, so
`LLM_PROVIDER=openrouter` ⇄ `LLM_PROVIDER=openai_compat` is an env flip.

### `fake.py` — scripted, registered, and not a test-only import

`FakeLLM` answers from a script the caller sets, records the messages it was
given (T08 asserts on them), and registers itself as `kind="llm"`, `name="fake"`.
Registering it is deliberate: `LLM_PROVIDER=fake` is what makes a clean clone
conduct a whole interview before anyone has a key (PRD §6), and it is refused
when `APP_ENV=prod` — a fake that can run in production is worse than a missing
credential. It costs nothing, it is never rate-limited, and every other lane's
unit suite runs on it.

### Decorators

`RetryingLLM`, `RateLimitedLLM`, `InstrumentedLLM`, each wrapping `LLMPort` and
implementing it. They compose in the composition root, in that order, outside
the adapter. Retry classifies on `PortError.transient`, never on a status it had
to guess. The instrumented wrapper logs provider, model, latency, token usage —
and never the key.

## Tests

All against `respx`, no network:

- success; 401; 429; malformed body; a 200 whose body carries an error field;
  usage parsing.
- missing credential → `ConfigError` naming the variable.
- `PortError.transient` is `True` for 429/5xx/timeout, `False` for 400/401.
- retry decorator: transient retried up to the ceiling with backoff, permanent
  raised on the first attempt, budget honoured.
- rate limiter: N calls per minute, the N+1th waits rather than failing.
- `LLM_PROVIDER=fake` builds `FakeLLM` through the same factory as a real slug,
  and the same slug under `APP_ENV=prod` raises `ConfigError` naming both.
- **The registry proof**: a fake provider registered inside a test is built by
  the factory with **no change to the factory**. If this test needs an edit
  elsewhere, dispatch is not data yet.

## Done when

- Both adapters green on the mock transport; the registry suite green.
- `.env.example` carries the LLM block of PRD §6 and the README configuration
  table lists both slugs — `docs-check` enforces it.
- `interviewer_adapters/llm/CONTEXT.md` answers "add a provider → here" in one
  line under **Where to change what**.

## Land it — worktree → `master`

`make check` inside the worktree first. No network, no containers, so there is
no excuse to skip it.

```bash
cd ../wt-t03-llm
make check                    # ruff, mypy --strict, tests, coverage, docs-check
git add -A && git commit -m "feat(llm): provider registry, openrouter and openai_compat adapters (T03)"

cd <repo>                     # the main checkout, always on master
git switch master
git merge --no-ff task/t03-llm-adapters -m "feat(llm): provider registry, openrouter and openai_compat adapters (T03)"
make check                    # green on the trunk, not only on the branch

git worktree remove ../wt-t03-llm
git branch -d task/t03-llm-adapters
```

Merged straight onto `master` — no pull request, no integration branch. If
`make check` fails on the trunk after the merge, fix it on `master` at once:
every later lane branches off it.
