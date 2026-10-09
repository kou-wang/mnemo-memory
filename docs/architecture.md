# Architecture

This document describes the current system boundaries and invariants. Durable
rationales live in [accepted decisions](decisions/README.md), established
product behavior in [product requirements](product-requirements.md), and future
sequence in the [roadmap](roadmap.md).

## Boundary

Mnemo separates probabilistic interpretation from deterministic memory management.

```text
Text / transcribed voice
   |
   v
Capture
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
   +--> capture repository
   +--> atomic lifecycle writes
   +--> structured lookup
   +--> temporal lookup
   +--> semantic index
```

The extractor must never write directly to storage.

## Core interface boundaries

Provider-independent contracts remain authoritative while concrete
implementations stay behind those boundaries. PostgreSQL is the first
persistence adapter and does not leak SQLAlchemy or database types into the
domain models or repository protocols.

### Capture

`Capture` preserves the user's raw text, source type (`TEXT` or `VOICE`), user
scope, and timezone-aware capture/storage times before extraction. A voice
capture contains its transcript. Raw audio is deleted by default after
transcription and is not part of the core model.

Capture and Memory remain distinct. One Capture may produce zero, one, or many
`CandidateMemory` values.

### Extraction

`Extractor` is a minimal synchronous protocol from `Capture` to a sequence of
`CandidateMemory` values. It interprets language only and has no persistence or
lifecycle authority.

Each candidate carries an unresolved subject mention plus an explicit
`EntityType` classification, and an object mention must carry its own type when
present. These types are probabilistic interpretation hints for ingestion-time
entity creation; candidates do not contain persisted entity identifiers.

`OpenAIExtractor` is the first concrete adapter behind this boundary. All SDK,
Responses API, prompt, and provider response-schema details live under
`mnemo.providers.openai`; the domain models, lifecycle engine, and
provider-independent interfaces do not import OpenAI types. The SDK is an
optional package extra. The adapter uses `responses.parse()` with a strict
provider-local Pydantic envelope, then maps the parsed DTOs into
`CandidateMemory` values. The model name is supplied by the caller.

The provider DTO is interpretation output only. The adapter has no repository,
entity resolver, lifecycle engine, or clock dependency and cannot persist,
resolve, deduplicate, supersede, delete, expire, complete, or cancel memories.
Capture `captured_at` is its only reference time; it does not consult the
machine wall clock. Intent-completion language remains outside this extraction
schema because `CandidateMemory` cannot represent a lifecycle command without
conflating it with a new memory.

### Entity resolution

`EntityResolver` resolves one extracted subject or object mention inside an
explicit user scope. Its result distinguishes a matched entity, an unmatched
mention that may require later creation, and ambiguity with multiple candidates.
The resolver does not persist or auto-merge; ADR-006 remains authoritative.

`DeterministicEntityResolver` is the first concrete strategy. It reads only the
requested user's entities through `EntityRepository` and compares the mention
exactly after Unicode NFKC normalization, outer trimming, whitespace collapsing,
and Unicode case folding. Canonical names and explicit aliases participate in
matching. Punctuation, accents, and partial-name distinctions are preserved; no
fuzzy, embedding, nickname, transliteration, or model-based inference occurs.

Zero, one, or multiple distinct entity-id matches produce `UNMATCHED`, `MATCHED`,
or `AMBIGUOUS`, respectively. Ambiguous results retain every distinct candidate
in stable entity-id order and never select or merge one. Resolution is read-only:
entity creation belongs to ingestion orchestration, while alias changes remain
future-scoped.
Extracted entity types do not participate in this matching decision and must not
silently disambiguate identities with the same normalized name or alias.

### Ingestion orchestration

`IngestionService` is the first provider-independent write path. It composes the
existing extractor, resolver, repositories, clock, and lifecycle engine without
importing OpenAI or SQLAlchemy:

```text
Capture (persist first)
  -> Extractor
  -> resolve subject and object
  -> safely create unmatched typed entities
  -> materialize validated Memory with provenance
  -> LifecycleEngine.reconcile()
  -> append, no write for NOOP, or atomic CURRENT_STATE supersession
```

Both mentions are resolved before the service creates any entity for a
candidate. Ambiguity or a matched-entity type conflict blocks that candidate and
produces an explicit result; entity type never selects among ambiguous
identities. Unmatched mentions may create an entity with the extracted type and
no inferred aliases. Equal normalized subject/object mentions with the same type
share one new entity when both were unmatched.

The capture repository write intentionally happens before extraction, so raw
provenance survives provider or later processing failures. Repository methods
remain the atomic boundaries: the service does not introduce a cross-repository
unit of work or destructively undo committed records. A successfully created
entity can remain if a later memory write fails, allowing a retry to resolve and
reuse it. Current-state retirement and replacement are never split; they use
`MemoryRepository.supersede_current_state()`.

Retry guarantees assume equivalent extracted candidates. An identical stored
capture is accepted, created entities are resolved on retry, and lifecycle exact
duplicates become `NOOP`; varying live model output is not claimed to be fully
idempotent.

### Persistence

`CaptureRepository` persists and retrieves captures under explicit user scope.
`EntityRepository` provides user-scoped entity lookup/listing plus explicit add
for ingestion orchestration; cross-user reads do not expose records, and
cross-user writes fail closed.

`MemoryRepository` reads active/user-scoped memory and exposes lifecycle writes
as atomic operations:

- append a new memory while preserving provenance;
- supersede an active `CURRENT_STATE` and insert its replacement in one
  transaction while retaining the historical record;
- validate an expected status and apply a non-supersession status transition in
  one transaction.

A `NOOP` decision performs no repository write. Repository adapters must fail
closed on cross-user mutation and must not expose another user's record through
lookup. Generic status transition operations must reject `SUPERSEDED` because
supersession requires an atomic replacement-aware operation.

The PostgreSQL adapter uses SQLAlchemy 2.x with psycopg 3 and Alembic-managed
schema migrations. It preserves structured memory values in `JSONB` and stores
timezone-aware timestamps. Composite foreign keys enforce that memory subjects,
objects, captures, and supersession links remain in the same user scope. A
partial unique index enforces at most one active `CURRENT_STATE` per
`(user_id, memory_key)` even when a caller bypasses repository code.

Each repository mutation owns one database transaction. Current-state
supersession locks the existing active row and changes it to `SUPERSEDED` while
inserting its replacement in that same transaction; any failure rolls back both
changes. The generic transition method remains non-supersession-only.

### Structured and temporal recall

`StructuredRecallService` is the first deterministic read path. It resolves a
structured subject mention through the existing conservative `EntityResolver`,
then reads validated `Memory` evidence through the provider-independent
`MemoryQueryRepository`. Unmatched, ambiguous, and uniquely matched-but-wrong-
type subjects remain explicit outcomes. An expected `EntityType` is only a
post-match consistency check and never chooses among ambiguous identities.

The read contract supports user, status, kind, subject, predicate, object,
occurrence/observation/effective-event time, validity, stable ordering, and
bounded-limit filters. The PostgreSQL implementation returns domain models,
never ORM rows, and is backed by one focused structured-recall index.

Current and active recall returns only `ACTIVE` evidence that is temporally
valid according to the injected timezone-aware `Clock`. Future `valid_from`,
past `valid_until`, and reached `expires_at` boundaries exclude a row without
mutating its persisted status. Explicit history queries may still return stale
or terminal evidence. Event history is newest-first by `occurred_at`, falling
back to `observed_at`, with UUID ordering as a deterministic final tie-breaker.
Current-state duplicate slots fail closed, while conflicting active facts and
multiple preferences remain separate evidence rather than being guessed away.

Recall creates no entities, performs no lifecycle changes, preserves each
memory's source-capture provenance, and stops at typed evidence. Natural-
language query interpretation and grounded answer synthesis are downstream
layers with no authority to alter this evidence. Semantic or vector retrieval
remains a future fallback or augmentation after structured and temporal lookup,
not the primary path.

### Natural-language recall planning

`RecallPlanner` is the provider-independent probabilistic interpretation
boundary in front of structured recall:

```text
Natural-language question
  -> RecallPlanner
  -> StructuredRecallRequest[]
  -> StructuredRecallService
  -> grounded Memory evidence
```

A plan explicitly distinguishes `PLANNED`, `UNSUPPORTED`, and `AMBIGUOUS`.
Abstention contains no speculative structured requests. The first concrete
adapter, `OpenAIRecallPlanner`, uses the Responses API with a strict
provider-local Structured Outputs envelope and maps it into provider-independent
`RecallPlan` and `StructuredRecallRequest` values. OpenAI SDK types remain inside
the provider package.

Planning receives an explicit timezone-aware `asked_at` and uses it as its only
time reference. Simple calendar phrases use the supplied fixed timezone offset:
"yesterday" is the previous local calendar day, "this week" begins Monday at
midnight and ends at `asked_at`, and "last month" is the previous local calendar
month. Other ambiguous temporal language must abstain rather than consult a wall
clock or guess.

The planner has no repository, entity-resolution, retrieval, persistence,
lifecycle, truth-evaluation, or answer-synthesis authority. Structured recall
execution remains deterministic. Grounded answer synthesis is a separate
downstream boundary; semantic fallback remains later work.

### Recall execution orchestration

`RecallOrchestrationService` is the provider-independent bridge from a natural-
language plan to deterministic structured recall. It preserves planner
`UNSUPPORTED` and `AMBIGUOUS` outcomes without executing retrieval. For a
`PLANNED` result, it validates every request's user scope before the first read,
then executes the requests exactly once and in plan order without broadening,
repairing, or otherwise reinterpreting them.

The result retains each request beside its complete `StructuredRecallResult` and
also exposes evidence flattened in stable request/result order. Aggregate
outcomes distinguish all-found, all-missing, mixed partial, ambiguous-subject,
and subject-type-conflict cases; they do not merge memories or synthesize a
natural-language answer. Planner/provider failures and structured-recall
invariant failures propagate to the caller. Memory provenance remains unchanged
through this read-only layer.

### Grounded answer synthesis

`RecallAnswerService` composes completed recall execution with a provider-
independent `AnswerSynthesizer`:

```text
Natural-language question
  -> RecallPlanner
  -> deterministic structured recall
  -> grounded Memory evidence
  -> AnswerSynthesizer
  -> user-facing text + cited memory ids
```

Deterministic recall remains the sole owner of the evidence set. The synthesizer
receives exactly the ordered `Memory` evidence already returned by recall and has
no repository, resolver, lifecycle, persistence, or fallback-retrieval authority.
The OpenAI adapter serializes only the minimal evidence fields needed for
phrasing and does not send the user id. Its strict provider-local result maps to
provider-independent answer models.

`NOT_FOUND`, `UNSUPPORTED`, ambiguous-plan, ambiguous-subject, and subject-type-
conflict outcomes bypass synthesis. Missing evidence returns the stable message
`I don't have that saved.` without an LLM call. `PARTIAL` recall may phrase its
available evidence but remains explicitly partial and retains every per-request
recall result.

Before returning an answer, deterministic code validates every citation against
the supplied memory ids and fails closed on unknown, missing, or duplicate
citations. When one structured FACT request returns multiple memories, every one
must be cited. Deterministic answer code does not infer cardinality or label
different FACT values as conflicting: they may legitimately coexist or represent
uncertain saved information. Synthesis preserves and reports the supplied values
without silently selecting one. Provenance remains attached to the unchanged
evidence models. Semantic/vector fallback remains later work.

### Time

`Clock` is an injectable protocol whose `now()` result must be timezone-aware.
It enables deterministic future temporal orchestration without adding a
scheduler or forcing existing models to depend on a clock.

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

## Deferred implementations

The current interface layer intentionally excludes:

- additional LLM provider implementations
- pgvector
- fuzzy or semantic entity candidate generation and entity merge operations
- FastAPI
- mobile app
- semantic/vector retrieval and ranking

These may be added only through later scoped Issues after the contracts and
domain behavior are reviewed.

Specific future technologies and implementation details remain `TBD` until an
approved Issue and, when architectural, an accepted decision establish them.
