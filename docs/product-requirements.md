# Product Requirements

This document records established product requirements and boundaries. It does
not select future implementation details; unresolved choices are marked `TBD`.

## Product position

Mnemo is an everyday personal-memory system that helps people capture small but
useful details and recall them later. It is not a generic notes application and
not a thin retrieval-augmented-generation wrapper.

The product loop is:

1. **Capture** — accept a low-friction natural-language memory input.
2. **Understand** — interpret it into structured personal memory.
3. **Maintain** — apply deterministic lifecycle, temporal, provenance, and
   user-isolation rules.
4. **Recall** — synthesize a useful supported answer rather than returning an
   unexplained list of raw search results.

When available evidence does not support an answer, Mnemo must abstain instead
of fabricating a personal fact.

## Memory requirements

Mnemo represents memories with five top-level kinds:

- `FACT`: durable information such as a birthday;
- `PREFERENCE`: likes, dislikes, and preferences that may coexist;
- `CURRENT_STATE`: mutable state such as parking or object location;
- `EVENT`: append-oriented historical occurrences;
- `INTENT`: future wants or actions that may complete, cancel, or expire.

Memory is temporal and lifecycle-aware. Current state can change without losing
history; events retain occurrence time; intents can leave the active set while
remaining historical. Captures and memories are distinct, and persisted
memories retain source provenance whenever available. One capture may yield
zero, one, or multiple memories.

Recall should prefer structured lookup, temporal lookup, and aggregation before
semantic retrieval. Personal answers must remain grounded in retained memory
evidence.

## User data expectations

- A user's data must remain isolated from every other user's data, including in
  deterministic domain operations.
- Users are expected to be able to inspect, edit or correct, delete, and export
  their memory data. The interfaces, authorization model, export format, and
  deletion workflow are `TBD` and require later approved design.
- Explicit privacy deletion is distinct from ordinary semantic lifecycle
  changes such as supersession, completion, cancellation, or expiration.
- History and provenance are preserved unless the user explicitly deletes data.

## MVP use cases

The established initial use cases are:

- people and birthdays;
- preferences;
- parking and object locations;
- workout history and progression;
- life events and vehicle maintenance;
- shopping and other future intents.

## MVP boundaries and non-goals

- Do not turn Mnemo into a general-purpose notes application.
- Do not route every query through vector search.
- Do not allow probabilistic extraction to control persistence or lifecycle.
- Do not silently merge ambiguous entities.
- Do not return unsupported personal claims.
- Authentication, billing, notifications, mobile product details, model/vendor
  selection, storage technology, and deployment architecture are future
  decisions unless approved by a later Issue/ADR.

## Engine and product boundary

The open-source Mnemo engine owns reusable memory domain behavior and must
remain independently useful. Consumer application experiences, private product
services, and platform-specific UI belong in a separate product layer that uses
the engine without weakening its invariants.

The exact packaging, licensing, hosting, and boundary of future private product
components are `TBD`.

See [Architecture](architecture.md), [accepted decisions](decisions/README.md),
and the [roadmap](roadmap.md) for current constraints and sequencing.
