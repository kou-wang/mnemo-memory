# Architecture

## Boundary

Mnemo separates probabilistic interpretation from deterministic memory management.

```text
User capture
   |
   v
Extractor (LLM or rule based)
   |
   v
CandidateMemory[]
   |
   v
Entity Resolver
   |
   v
Lifecycle Engine
   |
   +--> deduplication
   +--> supersession
   +--> expiration
   +--> intent transitions
   |
   v
Persistence Adapter
   |
   +--> structured lookup
   +--> temporal lookup
   +--> semantic index
```

The extractor must never write directly to storage.

## Domain invariants

1. A `CURRENT_STATE` memory must have a `memory_key`.
2. At most one active `CURRENT_STATE` memory may exist for a given user + memory key.
3. A new value for the same current-state slot supersedes the previous active value.
4. At most one active `FACT` memory may exist for a given subject + predicate. A
   new value is treated as a correction: it supersedes (never deletes) the
   previous active fact, preserving history and provenance.
5. `PREFERENCE` memories may coexist freely; a new preference never replaces
   an unrelated one. Removing a preference is a status transition (e.g. to
   `DELETED`), not an automatic side effect of adding another preference.
6. `EVENT` memories are append-only except for duplicate/correction handling.
7. `INTENT` memories may become completed, cancelled, expired, or deleted.
8. Terminal statuses (`SUPERSEDED`, `COMPLETED`, `CANCELLED`, `EXPIRED`,
   `DELETED`) are final: once reached, a memory cannot transition to a
   different status.
9. Terminal history is retained unless the user explicitly deletes data.
10. Every persisted memory should retain provenance to its source capture when available.
11. Retrieval should prefer structured/temporal lookup before semantic search.

## Memory key

A memory key identifies a mutable state slot, not a whole memory. The initial format is:

```text
<subject_entity_id>:<normalized_predicate>
```

Examples:

- `my_car:parked_at`
- `passport:located_at`

The persistence layer will scope keys by user.

## Next layers

Sprint 1 intentionally excludes:

- LLM provider implementation
- PostgreSQL adapter
- pgvector
- entity merge heuristics
- FastAPI
- mobile app

Those are added after the domain behavior is covered by deterministic tests.
