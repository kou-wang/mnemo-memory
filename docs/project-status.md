# Project Status

Last updated: 2026-10-08

## Current phase

**Sprint 1 — Repository Bootstrap + Core Domain Engine**

Working branch: `sprint-1-bootstrap`

Open PR: **#6 — Sprint 1: bootstrap temporal memory domain**

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

## In progress

### Issue #4 — CI and quality gates

Implementation complete on the Sprint 1 branch; awaiting review.

CI now provides named quality checks on Python 3.11 and 3.12 for:
- Ruff
- strict mypy
- the complete pytest suite with package coverage
- a failing lifecycle-specific coverage threshold of 90%

The same commands are documented for local use. Sprint 1 code work is complete
pending final PR review. GitHub branch protection is not currently enabled on
`main`; repository settings must require the named CI checks separately.

## Next

1. Review Issue #4 — CI and quality gates
2. Complete final review of PR #6
3. Merge PR #6 after approval and required checks
4. Sprint 2 — extraction/repository interfaces and conservative entity resolution

## Current constraints

Sprint 1 must not add:
- FastAPI
- PostgreSQL / SQLAlchemy
- pgvector
- Redis
- OpenAI SDK
- React Native / Expo
- authentication
- billing
- notifications

## Product direction

The eventual consumer product is a fast everyday-memory app focused on:
- people and dates
- preferences
- parking / object locations
- workout history
- life events / maintenance
- shopping and other wants

The open-source repository is the reusable temporal Personal Memory Engine underlying that product.
