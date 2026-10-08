# Sprint 1 — Repository Bootstrap + Core Domain Engine

## Goal

Establish a testable, provider-independent domain layer before adding LLM extraction or persistence.

## Deliverables

### 1. Domain models

Implement and test:

- `MemoryKind`: FACT, PREFERENCE, CURRENT_STATE, EVENT, INTENT
- `MemoryStatus`: ACTIVE, SUPERSEDED, COMPLETED, CANCELLED, EXPIRED, DELETED
- `Entity`
- `CandidateMemory`
- `Memory`

### 2. Lifecycle engine

The lifecycle engine must remain deterministic and side-effect free.

Required behavior:

- current-state append when no prior active slot exists
- current-state no-op when value is unchanged
- current-state supersession when value changes
- invariant violation when multiple active states exist for one slot
- intent ACTIVE -> COMPLETED
- intent ACTIVE -> CANCELLED
- invalid terminal-state transitions rejected
- exact duplicate detection for non-current-state memories

### 3. Test fixtures

Create fixture sequences for the initial product scenarios:

1. birthday fact
2. friend preference
3. parking state
4. object location
5. workout events
6. vehicle maintenance event
7. shopping intent

Sequence tests must include:

- "I parked at A1" -> "I moved to B7"
- "I want AirPods" -> "I bought them"
- repeated identical capture
- correction without deleting provenance

### 4. Quality gates

CI must run:

```bash
ruff check .
mypy src
pytest --cov=mnemo
```

Initial target: >= 90% coverage for lifecycle code.

## Non-goals

Do not add FastAPI, PostgreSQL, pgvector, Redis, OpenAI SDK, or React Native in Sprint 1.

## Definition of done

Sprint 1 is complete when the domain model is stable enough that storage and extraction can be implemented behind interfaces without changing lifecycle semantics.
