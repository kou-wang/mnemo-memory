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
4. `EVENT` memories are append-only except for duplicate/correction handling.
5. `INTENT` memories may become completed, cancelled, expired, or deleted.
6. Terminal history is retained unless the user explicitly deletes data.
7. Every persisted memory should retain provenance to its source capture when available.
8. Retrieval should prefer structured/temporal lookup before semantic search.

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
