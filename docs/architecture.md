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

1. `memory_key` is a `CURRENT_STATE`-only concept: it is required (and
   must equal the canonical key derived from `subject_entity_id` +
   `predicate`) for `CURRENT_STATE` memories, and must be `None` for every
   other `MemoryKind`.
2. At most one active `CURRENT_STATE` memory may exist for a given user + memory key.
3. A new value for the same current-state slot supersedes the previous active value.
4. `FACT` has **no** single-active-slot invariant in Sprint 1. The engine
   cannot infer from `MemoryKind.FACT` alone whether a predicate is
   single-valued (e.g. `birthday`) or naturally multi-valued (e.g.
   `has_child`, `owns_pet`, `phone_number`). A new fact with the same
   subject + predicate but a different value therefore appends rather
   than supersedes, so uncertain conflicts never silently retire history.
   An exact duplicate fact is a no-op. Explicit correction/update
   semantics (e.g. "Kevin's birthday is actually March 13") are a future
   design that requires the caller to supply an unambiguous,
   deterministic correction signal.
5. `PREFERENCE` memories may coexist freely; a new preference never replaces
   an unrelated one, and an exact duplicate is a no-op. Sprint 1 does not
   implement natural-language preference removal ("Kevin doesn't like
   whisky anymore"); when added, it must retire/end the prior memory via
   explicit supersession or a validity window -- not `DELETED`.
6. `EVENT` memories are append-only except for duplicate handling.
7. `INTENT` memories may become completed, cancelled, expired, or deleted.
8. Terminal statuses (`SUPERSEDED`, `COMPLETED`, `CANCELLED`, `EXPIRED`,
   `DELETED`) are final: once reached, a memory cannot transition to a
   different status.
9. `DELETED` is reserved for explicit user/privacy deletion requests. It
   must never be used to mean "this is no longer true" -- that is a
   semantic invalidation (supersession, expiration, or a closed validity
   window), not a data-deletion event.
10. Terminal history is retained unless the user explicitly deletes data.
11. Every persisted memory should retain provenance to its source capture when available.
12. Retrieval should prefer structured/temporal lookup before semantic search.
13. User isolation is enforced inside `LifecycleEngine.reconcile()`, not
    merely assumed from the caller: any existing memory with a different
    `user_id` than the incoming memory raises a `LifecycleInvariantError`
    rather than being silently filtered out.

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
