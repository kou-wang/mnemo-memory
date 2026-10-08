# AGENTS.md

This file is the shared operating context for any coding agent working in this repository, including Cursor and Codex.

Before making non-trivial changes, read:
- `README.md`
- `docs/architecture.md`
- `docs/decisions.md`
- `docs/project-status.md`
- the current sprint spec under `docs/`

Treat those files as the source of truth unless the user explicitly changes the product or architecture.

## Product goal

Mnemo is an open-source temporal personal-memory engine for everyday AI applications.

It is **not** a generic notes app and **not** a thin RAG wrapper.

It converts short natural-language captures into structured memories that can be updated, superseded, expired, completed/cancelled, queried over time, and aggregated into useful answers.

Initial consumer use cases:
- people and birthdays
- preferences
- parking and object locations
- workouts
- life events / maintenance
- shopping and other future intents

The engine must remain independently useful outside the future consumer app.

## Core memory kinds

The five top-level kinds are:
- `FACT`
- `PREFERENCE`
- `CURRENT_STATE`
- `EVENT`
- `INTENT`

Do not add a new top-level kind without first showing why these five cannot represent the use case.

### FACT
Durable information. Exact duplicates are a no-op. Conflicting values append conservatively in Sprint 1; do not auto-supersede uncertain facts.

### PREFERENCE
Likes/dislikes/preferences. Multiple values may coexist. Exact duplicates are a no-op. Do not use `DELETED` to mean "no longer true."

### CURRENT_STATE
Mutable state such as parking or object location. It is the only memory kind allowed to have a `memory_key`. For the same user + canonical memory key, at most one ACTIVE state may exist. A new value supersedes the previous ACTIVE state while preserving history.

### EVENT
Historical occurrence such as a workout or oil change. Append-oriented. Exact duplicate capture may no-op.

### INTENT
Future wants/actions such as buy/read/watch/visit. Typical semantic lifecycle:
`ACTIVE -> COMPLETED | CANCELLED | EXPIRED`.

`DELETED` is reserved for explicit user/privacy deletion, not ordinary semantic invalidation.

## Hard architecture boundary

> Probabilistic systems interpret language. Deterministic code controls memory lifecycle and persistence decisions.

LLMs/extractors may produce `CandidateMemory` objects.

They must NOT directly:
- write to persistence
- delete memories
- supersede memories
- complete/cancel intents
- choose lifecycle transitions
- bypass deterministic engine interfaces

The deterministic domain layer owns:
- deduplication policy
- lifecycle transitions
- state supersession
- expiration
- conflict handling
- temporal validity
- invariants
- user-isolation checks

## Capture and provenance

Capture and Memory are different concepts.

One capture may yield zero, one, or many candidate memories. Persisted memories should retain provenance to the original capture whenever possible.

Never discard the source merely because structured extraction succeeded.

## Recall philosophy

Prefer, in order:
1. structured lookup
2. temporal lookup
3. aggregation
4. semantic retrieval when needed

Do not route every query through vector search.

A memory system must prefer **no answer** over a fabricated personal fact.

## Entity resolution

Be conservative.

Prefer a duplicate entity over incorrectly merging two different people, places, or objects.

Do not silently merge ambiguous entities based only on approximate string or embedding similarity.

Entity merging must eventually be explainable and reversible.

## Time

Treat time as first-class data.

Keep distinct when applicable:
- `observed_at`
- `occurred_at`
- `valid_from`
- `valid_until`
- `expires_at`
- `created_at`
- `updated_at`

All datetimes are timezone-aware. Prefer UTC internally.

Do not substitute storage timestamps for event/validity time.

## User isolation

Never trust higher layers alone for user isolation.

Domain operations that reconcile multiple memories must fail closed when given cross-user data.

Never silently filter a foreign user's memory and continue.

## Domain-code rules

The core domain layer must:
- remain independent from FastAPI
- remain independent from OpenAI or any specific model provider
- remain independent from PostgreSQL / pgvector
- avoid network calls
- avoid hidden side effects
- use typed models
- keep lifecycle logic deterministic
- raise explicit domain errors for invariant violations

Prefer small pure functions and explicit state transitions over generic abstractions.

## Sprint discipline

Follow `docs/project-status.md` and the current sprint spec.

Do not implement future-sprint infrastructure merely because it seems useful.

During Sprint 1, do NOT add:
- FastAPI
- PostgreSQL / SQLAlchemy
- pgvector
- Redis
- OpenAI SDK
- React Native / Expo
- auth
- billing
- notifications

## Testing

Behavior changes require tests.

Prioritize sequence tests because memory correctness depends on history.

Important scenarios include:
- parking state A1 -> B7
- shopping intent wanted -> completed
- repeated duplicate events
- conflicting facts without silent history loss
- user-isolation failure
- abstention when no memory supports an answer

For lifecycle code, target >= 90% test coverage.

Before considering a coding task complete, run:

```bash
ruff check .
mypy src
pytest --cov=mnemo --cov-report=term-missing
```

Fix failures rather than bypassing checks.

## Python conventions

- Python >= 3.11
- Pydantic v2
- full type annotations for public interfaces
- mypy strict compatibility
- Ruff-compliant imports/style
- timezone-aware datetimes
- no mutable default arguments
- no broad exception swallowing
- no type ignores without a specific documented reason

## Dependency policy

Keep the core lightweight.

Before adding a dependency:
1. explain the concrete problem it solves
2. check whether stdlib/current dependencies suffice
3. avoid coupling domain semantics to infrastructure libraries

## Change policy

Before changing core lifecycle semantics:
1. identify the invariant being changed
2. add/update tests that express the intended behavior
3. make the smallest implementation change
4. run quality gates
5. update `docs/architecture.md` and `docs/decisions.md` if the contract changed
6. update `docs/project-status.md` when a task/sprint state changes

Do not silently alter established memory semantics.

## Git / PR behavior

Prefer small logical commits and focused changes.

Do not commit:
- secrets
- API keys
- local environment files
- generated caches
- real personal user data

Keep public code understandable to an external contributor with no private conversation context.

## Decision priority

When requirements conflict, use this order:
1. user data correctness and safety
2. deterministic memory semantics
3. preservation of history and provenance
4. testability
5. simple public API
6. performance
7. implementation convenience

When unsure, choose the simpler conservative behavior and make uncertainty explicit instead of inventing semantics.
