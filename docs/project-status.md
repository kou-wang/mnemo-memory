# Project Status

Last updated: 2026-10-08

## Current phase

**Developer Workflow Hardening — Issue #7**

Working branch: `chore/issue-7-agent-workflow`

Sprint 1 PR: **#6 — merged**

Open PR: **#8 — Developer workflow: shared agent instructions and PR review process**

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

## In progress

### Issue #7 — Shared agent workflow

Implementation reviewed and approved on PR #8; ready to merge after CI remains green.

Scope:
- canonical cross-agent guidance in root `AGENTS.md`
- lightweight Cursor entrypoint
- product requirements, roadmap, and development workflow documentation
- accepted ADR migration to `docs/decisions/`
- concise pull request template

## Next

1. Merge PR #8 / Issue #7
2. Issue #5 — Sprint 2 extraction and storage interfaces
3. Later extraction, entity resolution, persistence, retrieval, and evaluation work
4. Consumer/mobile application work

## Current constraints

Issue #7 is documentation/process-only and must not add runtime implementation
or infrastructure for:
- FastAPI
- PostgreSQL / SQLAlchemy
- pgvector
- Redis
- OpenAI SDK
- React Native / Expo
- authentication
- billing
- notifications
- memory models or lifecycle semantics
- extraction or storage interfaces

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
