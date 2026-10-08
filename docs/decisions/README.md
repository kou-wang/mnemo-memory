# Architecture Decisions

This file records durable decisions that future agents should not silently revisit.

See [Architecture](../architecture.md) for the current system shape and
[Development workflow](../development-workflow.md) for the approval process for
changing an accepted decision.

## ADR-001 — Five top-level memory kinds

**Status:** Accepted

Mnemo uses:
- FACT
- PREFERENCE
- CURRENT_STATE
- EVENT
- INTENT

A new top-level kind requires evidence that these five cannot model the use case.

## ADR-002 — Probabilistic interpretation, deterministic lifecycle

**Status:** Accepted

LLMs/extractors interpret natural language and emit candidate memories.

Deterministic domain code owns persistence decisions, lifecycle transitions, deduplication, supersession, expiration, and invariants.

The extractor never writes directly to storage.

## ADR-003 — CURRENT_STATE is the only slotted memory kind

**Status:** Accepted

`memory_key` exists only for CURRENT_STATE.

It is canonical for `subject_entity_id + predicate`.

For a user + memory key, at most one ACTIVE current state may exist.

A changed current state supersedes the prior ACTIVE memory while preserving history.

## ADR-004 — FACT conflicts are conservative

**Status:** Accepted

A differing FACT with the same subject and predicate does not automatically supersede an older FACT.

Reason: predicates may be single-valued or multi-valued, and the engine cannot infer cardinality from MemoryKind alone.

Sprint 1 behavior:
- exact duplicate -> NOOP
- different value -> APPEND

Explicit correction semantics will require an unambiguous deterministic signal in a later design.

## ADR-005 — DELETED means actual deletion

**Status:** Accepted

`DELETED` is reserved for explicit user/privacy deletion.

It must not be used as shorthand for "this is no longer true."

Semantic invalidation should use supersession, expiration, completion/cancellation, or validity windows as appropriate.

## ADR-006 — Conservative entity resolution

**Status:** Accepted

Prefer creating duplicate entities over incorrectly merging different real-world entities.

Ambiguous entity merges must not happen solely because strings/embeddings are similar.

Future merge operations should be explainable and reversible.

## ADR-007 — Structured retrieval before semantic retrieval

**Status:** Accepted

Recall should prefer:
1. structured lookup
2. temporal lookup
3. aggregation
4. semantic/hybrid retrieval

Mnemo is not an everything-through-vector-search system.

## ADR-008 — Preserve provenance

**Status:** Accepted

Capture and Memory are different objects.

One capture may produce multiple memories, and persisted memories should retain a link to their source capture whenever possible.

## ADR-009 — Fail closed on cross-user reconciliation

**Status:** Accepted

The domain layer validates user isolation when reconciling multiple memories.

Supplying a memory for a different user is an invariant violation; it must not be silently filtered.

## ADR-010 — Timezone-aware temporal data

**Status:** Accepted

All datetime values used by core memory models are timezone-aware.

Prefer UTC internally and preserve semantic distinctions among observation, occurrence, validity, expiration, and storage timestamps.

## ADR-011 — PostgreSQL persistence adapter

**Status:** Accepted

PostgreSQL is the first durable persistence backend. Its adapter uses
SQLAlchemy 2.x with the synchronous psycopg 3 driver, and Alembic owns schema
migrations. The domain models and repository protocols remain independent of
all three libraries.

PostgreSQL stores structured memory values in `JSONB`, preserves timezone-aware
timestamps, and enforces same-user references with composite foreign keys. A
partial unique index enforces at most one active `CURRENT_STATE` for each
`(user_id, memory_key)` slot. Current-state supersession must lock and retire the
old row while inserting its replacement in one transaction; generic status
transitions cannot set `SUPERSEDED`.

This decision does not select a vector index, retrieval strategy, service API,
or asynchronous database stack.
