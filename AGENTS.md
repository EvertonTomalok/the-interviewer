# AGENTS.md

Conventions an assistant (or a person) must follow in this repository. These
are not style preferences — each one is here because breaking it either
breaks a test or breaks the architectural claim the project makes.

## Language

Everything is in English — identifiers, comments, commit messages, every
document in this repository, and every string a user reads on screen. There
is no exception carved out for UI copy here: this project's interface is
English throughout.

## Ports before adapters

A new external concern gets a `typing.Protocol` in `packages/core`'s ports
before it gets an implementation, and a fake before a real adapter. See
`.claude/skills/build/SKILL.md` step 3 and
`.claude/skills/build/references/adding-a-provider.md`.

## No provider name in the engine

`packages/core` never imports a provider's SDK, never branches on a provider
slug, and never knows whether the LLM behind `LLMPort` is OpenRouter or a
scripted fake. If a change to the engine requires knowing which provider is
configured, the change belongs in an adapter or in the registry, not in the
engine.

## No `if/elif` on a provider slug

Anywhere. Provider dispatch is `require_spec(kind, name).build(...)` — data,
not a branch. A dispatch `if/elif` is the bug the registry exists to make
impossible; adding a case to one instead of registering a new
`ProviderSpec` is treated as a defect, not a shortcut.

## Tests before implementation

Red, then green, on in-memory adapters. A test that cannot pass without a
real Postgres or Redis is not a unit test — it belongs in
`packages/adapters/tests/contract/`, marked `@pytest.mark.integration`, run
only by `make itest`.

## No `os.environ` outside settings

Every setting is read once, in `packages/core/src/interviewer_core/config`,
through `pydantic-settings`. A module that needs a value takes it as a
constructor argument or reads it off the settings object it was handed —
never `os.environ` directly. A missing credential fails at process start,
naming the exact variable.

## Worktree discipline

Every non-trivial change runs through `.claude/skills/build/SKILL.md`: its
own worktree, its own branch (`task/t<NN>-<slug>` for a plan task,
otherwise a descriptive name), landing on `master` with `--no-ff` once
`make check` is green — in the worktree, then again on the trunk.

## Documentation moves with the code

A module's `CONTEXT.md` is part of the change that touches that module, in
the same commit or the same branch — not a follow-up. `make docs-check` is
part of `make check` for exactly this reason.
