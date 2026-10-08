# Project Status

Last updated: 2026-10-08

## Current phase

**Sprint 2 — Deterministic Entity Resolution (Issue #12)**

Working branch: `feat/deterministic-entity-resolution`

Sprint 1 PR: **#6 — merged**

Developer workflow PR: **#8 — merged**

Core interfaces PR: **#9 — merged**

OpenAI extractor PR: **#11 — merged**

Issue #12 implementation: **complete; awaiting maintainer review**

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

## In progress

### Issue #12 — Deterministic entity resolution

Implementation complete; awaiting maintainer review.

Implemented:
- a provider-independent, user-scoped `EntityRepository` contract
- pure NFKC, whitespace, and casefold name normalization
- exact canonical-name and explicit-alias matching
- deterministic MATCHED / UNMATCHED / AMBIGUOUS outcomes
- entity-id deduplication and stable ambiguous candidate ordering
- fail-closed repository scope validation
- read-only resolution with no entity creation, alias learning, or merge behavior
- test-only repository fakes and behavior/contract coverage

## Next

1. Review Issue #12 and its dedicated PR
2. Later persistence, retrieval, and evaluation work
3. Consumer/mobile application work

## Current constraints

Issue #12 adds only the deterministic entity-resolution baseline and must not add:
- FastAPI
- PostgreSQL / SQLAlchemy
- pgvector
- Redis
- fuzzy matching, edit distance, embeddings, or LLM resolution
- automatic alias learning, entity creation, or entity merging
- React Native / Expo code
- authentication
- billing
- notifications
- lifecycle semantic changes
- concrete storage backends
- capture-to-persistence or lifecycle orchestration

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
