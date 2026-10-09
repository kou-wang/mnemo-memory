# Project Status

Last updated: 2026-10-09

## Current phase

**Natural-language recall planning (Issue #22)**

Working branch: `feat/natural-language-recall-planner`

Sprint 1 PR: **#6 — merged**

Developer workflow PR: **#8 — merged**

Core interfaces PR: **#9 — merged**

OpenAI extractor PR: **#11 — merged**

Deterministic entity resolution PR: **#13 — merged**

PostgreSQL persistence PR: **#15 — merged**

Typed entity mentions PR: **#17 — merged**

Ingestion orchestration PR: **#19 — merged**

Structured and temporal recall PR: **#21 — merged**

Issue #22 implementation: **complete; awaiting maintainer review**

## Completed

### Issue #1 — Core domain models

Completed and reviewed.

Implemented:
- MemoryKind / MemoryStatus
- Entity
- CandidateMemory
- Memory
- canonical CURRENT_STATE memory_key validation
- timezone-aware datetime validation
- domain model tests

### Issue #2 — Deterministic lifecycle state machine

Completed and reviewed.

Final semantics:
- CURRENT_STATE: append / no-op / supersede
- FACT: exact duplicate no-op; conflicting values append conservatively
- PREFERENCE: exact duplicate no-op; other values append
- EVENT: exact duplicate no-op; otherwise append
- INTENT: lifecycle transition validation
- duplicate identity includes object_entity_id
- reconcile fails closed on cross-user input
- memory_key is CURRENT_STATE-only
- CURRENT_STATE reconciliation only considers CURRENT_STATE memories in the same slot
- DELETED remains reserved for explicit user/privacy deletion

### Issue #3 — Canonical scenario fixtures

Completed and reviewed.

Implemented reusable deterministic scenario sequences for:
- birthday facts and conservative conflicts
- coexisting friend preferences and exact repeats
- parking and passport current-state history
- workout and vehicle-maintenance events
- shopping intent completion and multi-memory Costco captures
- duplicate-event no-op behavior
- cross-user reconciliation failure

All fixture timestamps, identifiers, expected lifecycle actions, final states,
historical records, and source provenance are explicit and reproducible.

### Issue #4 — CI and quality gates

Completed and reviewed.

CI now provides named quality checks on Python 3.11 and 3.12 for:
- Ruff
- strict mypy
- the complete pytest suite with package coverage
- a failing lifecycle-specific coverage threshold of 90%

The same commands are documented for local use. Sprint 1 is complete. The
workflow does not claim that GitHub branch protection is enabled; repository
administrators configure required checks separately.

### Issue #7 — Shared agent workflow

Completed and reviewed.

Scope:
- canonical cross-agent guidance in root `AGENTS.md`
- lightweight Cursor entrypoint
- product requirements, roadmap, and development workflow documentation
- accepted ADR migration to `docs/decisions/`
- concise pull request template

### Issue #5 — Core interfaces

Completed and reviewed.

Implemented provider-independent contracts for:
- raw text/voice-transcript Capture provenance
- extraction to zero, one, or many CandidateMemory values
- conservative matched/unmatched/ambiguous entity resolution
- user-scoped capture and memory repositories
- atomic current-state supersession and explicit status transitions
- injectable timezone-aware clocks

### Issue #10 — OpenAI Structured Outputs extractor

Completed and reviewed.

Implemented:
- an optional OpenAI SDK extra isolated under `mnemo.providers.openai`
- configurable-model Responses API structured parsing
- strict provider-local DTOs mapped into CandidateMemory values
- explicit provider, refusal/unparsed-response, and malformed-output failures
- capture timestamp reference context without wall-clock access
- network-free extraction tests for the established MVP use cases
- a deterministic canonical extraction-evaluation seed

The extractor has no persistence, entity-resolution, or lifecycle authority.
No storage backend or lifecycle semantic change is included.

### Issue #12 — Deterministic entity resolution

Completed and reviewed.

Implemented:
- a provider-independent, user-scoped `EntityRepository` contract
- pure NFKC, whitespace, and casefold name normalization
- exact canonical-name and explicit-alias matching
- deterministic MATCHED / UNMATCHED / AMBIGUOUS outcomes
- entity-id deduplication and stable ambiguous candidate ordering
- fail-closed repository scope validation
- read-only resolution with no entity creation, alias learning, or merge behavior

### Issue #14 — PostgreSQL persistence

Completed and reviewed.

Implemented:
- SQLAlchemy 2.x + psycopg 3 adapters for capture, entity, and memory repositories
- an Alembic initial PostgreSQL schema migration
- exact capture provenance, timezone-aware timestamps, arrays, and JSONB values
- same-user composite foreign keys and fail-closed repository access
- a partial unique index for active current-state slots
- transactional, row-locked current-state supersession with rollback guarantees
- real PostgreSQL integration coverage in the Python 3.11/3.12 CI matrix

### Issue #16 — Typed entity mentions

Completed and reviewed.

Implemented:
- required `subject_type` and object/object-type consistency on `CandidateMemory`
- provider-local typed subject/object fields in OpenAI Structured Outputs
- prompt guidance for independent type classification and first-person subjects
- typed canonical extraction tests and evaluation seed
- preserved recursive `anyOf` schema compatibility with no `oneOf`
- unchanged deterministic name/alias entity resolution behavior

### Issue #18 — Ingestion orchestration

Completed and reviewed.

Implemented:
- provider-independent capture-to-memory write-path orchestration
- capture-first durable provenance and conflict-safe retry handling
- candidate-safe entity resolution and typed unmatched-entity creation
- explicit ambiguity/type-conflict/no-op/persisted candidate outcomes
- deterministic CandidateMemory-to-Memory mapping with injected time
- LifecycleEngine-owned append/no-op/supersession decisions
- atomic repository current-state replacement without a global unit of work
- equivalent-retry deduplication and real PostgreSQL end-to-end coverage

### Issue #20 — Structured and temporal recall

Completed and reviewed.

Implemented:
- provider-independent structured recall requests, results, and memory queries
- explicit matched, missing, ambiguous, and subject-type-conflict outcomes
- deterministic current-state, fact, preference, event, and intent recall
- clock-based temporal validity without status mutation
- PostgreSQL structured/temporal queries with stable ordering and limits
- source-capture provenance preservation and fail-closed scope validation
- real PostgreSQL recall coverage for the initial product scenarios

## In progress

### Issue #22 — Natural-language recall planning

Implementation complete; awaiting maintainer review.

Implemented:
- provider-independent `RecallPlanner` and typed plan outcomes
- OpenAI Responses API Structured Outputs planning adapter
- canonical MVP question-to-structured-request interpretation guidance
- explicit unsupported and ambiguous abstention without speculative requests
- fixed-offset relative calendar time anchored only to supplied `asked_at`
- strict no-`oneOf` schema regression coverage and sanitized provider failures
- deterministic offline recall-planning evaluation seed

## Next

1. Review Issue #22 and its dedicated PR
2. Later semantic retrieval, answer synthesis, and evaluation work
3. Consumer/mobile application work

## Current constraints

Issue #22 adds only probabilistic natural-language recall planning and must not add:
- FastAPI
- pgvector
- Redis
- React Native / Expo code
- authentication
- billing
- notifications
- lifecycle semantic changes
- recall execution orchestration or LLM answer synthesis
- embeddings, pgvector, or semantic/hybrid ranking
- entity creation, merging, or type-based identity disambiguation
- automatic expiration mutation
- repository access, identity resolution, persistence, or lifecycle mutation

## Product direction

The eventual consumer product is a fast everyday-memory app focused on:
- people and dates
- preferences
- parking / object locations
- workout history
- life events / maintenance
- shopping and other wants

The open-source repository is the reusable temporal Personal Memory Engine underlying that product.

See [Product requirements](product-requirements.md), the [roadmap](roadmap.md),
and the [development workflow](development-workflow.md) for durable context.
