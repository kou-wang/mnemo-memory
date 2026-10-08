# Shared Agent Instructions

This is the canonical engineering entrypoint for every AI agent working in
Mnemo, including Codex and Cursor. Tool-specific files may point here, but must
not maintain a separate copy of project semantics.

## Read before implementation

Use this source-of-truth order:

1. The linked GitHub Issue: task scope and acceptance criteria.
2. This file: shared engineering and workflow rules.
3. [Architecture](docs/architecture.md): current boundaries and invariants.
4. [Accepted decisions](docs/decisions/README.md): durable decisions that must
   not be silently revisited.
5. [Product requirements](docs/product-requirements.md): established product
   requirements and MVP boundaries.
6. [Roadmap](docs/roadmap.md): phase ordering and intended outcomes.
7. [Project status](docs/project-status.md): current implementation and review
   state.
8. Tool-specific entrypoints such as `.cursor/rules/*.mdc`.

Also read the current sprint specification when the Issue or project status
links one. If these sources conflict, stop and surface the contradiction to the
maintainer/architect. Do not guess or silently change architecture.

## Scope and workflow

- Treat the GitHub Issue as the task-specific source of truth, within accepted
  architecture and product decisions.
- Implement only the Issue. Do not add adjacent features, infrastructure, or
  dependencies without explicit authorization.
- Never do feature work directly on `main`; use a focused branch and PR.
- Follow the review and repair lifecycle in
  [Development workflow](docs/development-workflow.md).
- An implementation agent must not mark its own work reviewed or approved.

## Architecture boundaries

Mnemo is a reusable temporal personal-memory engine, not a generic notes app or
a thin RAG wrapper. The consumer product is a separate layer.

The hard boundary is:

> Probabilistic systems interpret language. Deterministic code controls memory
> lifecycle and persistence decisions.

Extractors may propose candidate memories. They must not directly persist,
delete, supersede, complete, cancel, expire, or otherwise bypass deterministic
domain rules. The five top-level memory kinds are `FACT`, `PREFERENCE`,
`CURRENT_STATE`, `EVENT`, and `INTENT`.

Do not change lifecycle semantics, add a memory kind, or cross an accepted
boundary without explicit Issue scope and an update or addition under
`docs/decisions/`. See [Architecture](docs/architecture.md) for the complete
invariants.

## Correctness, security, and privacy

Use this priority order when tradeoffs conflict:

1. user data correctness and safety;
2. deterministic memory semantics;
3. preservation of history and provenance;
4. testability;
5. simple public API;
6. performance;
7. implementation convenience.

User isolation is a domain invariant, not only a higher-layer concern. Any
operation that receives another user's memory must fail closed rather than
silently filter it. Never commit secrets, credentials, local environment files,
or real personal user data.

Prefer no answer to an unsupported personal claim. Preserve capture provenance,
semantic time, and historical records unless explicit deletion requirements say
otherwise.

## Code and test conventions

- Python 3.11 or newer; maintain Python 3.11 and 3.12 CI compatibility.
- Pydantic v2 and full annotations on public interfaces.
- Keep the domain independent of web frameworks, model providers, databases,
  vector stores, and network calls.
- Prefer small pure functions, explicit transitions, and no hidden side effects.
- Use timezone-aware datetimes, preferably UTC internally.
- Do not use mutable default arguments, broad exception swallowing, or
  unexplained type ignores.
- Add behavior tests for behavior changes; favor sequence tests for lifecycle
  behavior.
- Do not weaken lint, typing, or coverage settings to make a change pass.

Before declaring implementation complete, run:

```bash
ruff check .
mypy src
pytest --cov=mnemo --cov-report=term-missing
coverage report --include="*/mnemo/lifecycle/*" --fail-under=90
```

Fix failures rather than bypassing a gate. CI exposes the stable checks
`Quality gates (Python 3.11)` and `Quality gates (Python 3.12)`.

## Documentation responsibilities

Keep durable context in the repository, not only in chat:

- update `docs/architecture.md` when the current architecture changes;
- add or update an ADR when an accepted architecture decision changes;
- update `docs/product-requirements.md` only with maintainer-approved product
  requirement changes;
- update `docs/roadmap.md` when phase sequencing or outcomes change;
- update `docs/project-status.md` when implementation or review state changes;
- update tests and user/developer documentation affected by the change.

Unknown future choices must be marked `TBD` instead of guessed. Preserve useful
history when moving documentation and repair every affected reference.

## Dependency policy

Keep the core lightweight. Before adding a dependency, identify the concrete
problem, confirm the standard library/current dependencies do not solve it, and
avoid coupling domain semantics to infrastructure.
