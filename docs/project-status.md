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

## In progress

### Issue #3 — Canonical scenario fixtures

Next task.

The fixtures should represent reusable consumer-memory sequences and later seed the evaluation dataset.

## Next

1. Issue #3 — Add canonical scenario fixtures
2. Issue #4 — Tighten CI and quality gates
3. Merge PR #6 when Sprint 1 is complete
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
