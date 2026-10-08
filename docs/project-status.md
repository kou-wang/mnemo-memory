# Project Status

Last updated: 2026-10-08

## Current phase

**Sprint 2 — Core Interfaces (Issue #5)**

Working branch: `feat/issue-5-core-interfaces`

Sprint 1 PR: **#6 — merged**

Developer workflow PR: **#8 — merged**

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

## In progress

### Issue #5 — Core interfaces

Implementation complete on `feat/issue-5-core-interfaces`; awaiting review.

Implemented provider-independent contracts for:
- raw text/voice-transcript Capture provenance
- extraction to zero, one, or many CandidateMemory values
- conservative matched/unmatched/ambiguous entity resolution
- user-scoped capture and memory repositories
- atomic current-state supersession and explicit status transitions
- injectable timezone-aware clocks

No concrete provider, storage backend, network integration, or lifecycle
semantic change is included.

## Next

1. Review and merge Issue #5
2. Later extraction, entity resolution, persistence, retrieval, and evaluation work
3. Consumer/mobile application work

## Current constraints

Issue #5 defines interfaces only and must not add concrete implementation or
infrastructure for:
- FastAPI
- PostgreSQL / SQLAlchemy
- pgvector
- Redis
- OpenAI SDK
- React Native / Expo code
- authentication
- billing
- notifications
- lifecycle semantic changes
- extraction providers or storage backends

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
