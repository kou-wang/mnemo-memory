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

## Capture experience

The MVP supports both text and voice capture. Capture must remain extremely
low-friction: the target interaction time is approximately 3 seconds and should
remain under 5 seconds.

The established voice flow is:

```shell
audio
-> transcription
-> persist transcript/raw capture
-> delete raw audio by default
```

The exact transcription provider and implementation are future-scoped. The
persisted transcript/raw capture retains provenance; raw audio is not retained
by default after transcription.

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

## Privacy and user control

- A user's data must remain isolated from every other user's data, including in
  deterministic domain operations.
- Personal data must be encrypted in transit and encrypted at rest. The exact
  encryption architecture and key-management design are `TBD`.
- Users must be able to export their data and delete their account/data. Export
  formats and deletion mechanics are `TBD`.
- Users must be able to inspect and edit or correct a memory that AI
  interpretation got wrong. The editing interface is future-scoped.
- Raw audio must be deleted by default after transcription.
- Use of external AI providers must be disclosed when applicable. Mnemo must
  not claim that processing or data remains entirely on-device when a cloud
  provider is used.
- User data is not intended to be used for model training.
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

## Explicit MVP non-goals

The MVP does not include:

- Gmail integration;
- Calendar integration;
- Contacts integration;
- photo understanding;
- web bookmark/import;
- social features;
- payments/billing;
- a universal AI assistant;
- a meeting recorder;
- a journaling product;
- a full todo app;
- a password manager;
- 24/7 ambient recording.

These boundaries prevent adjacent product ideas from silently expanding MVP
scope. A future change requires explicit maintainer approval and Issue scope.

## Architecture guardrails

- Do not turn Mnemo into a general-purpose notes application.
- Do not route every query through vector search.
- Do not allow probabilistic extraction to control persistence or lifecycle.
- Do not silently merge ambiguous entities.
- Do not return unsupported personal claims.

## Consumer application direction

The initial consumer application is iOS-first. React Native + Expo is the
intended mobile implementation direction, and the shared codebase must preserve
a path to Android. Detailed implementation, release planning, store operations,
and rollout remain future-scoped.

## Engine and product boundary

The public, reusable open-source Memory Engine includes, as they are developed:

- domain memory models;
- extraction interfaces and structured extraction;
- entity resolution;
- the lifecycle engine;
- temporal logic;
- deduplication and conflict rules;
- retrieval and ranking;
- evaluation tooling;
- adapters, an SDK, and examples.

The product/private layer includes:

- consumer mobile UI;
- brand;
- product-specific auth glue;
- analytics;
- push notifications;
- billing;
- production infrastructure;
- growth and product experiments;
- other product-specific integration code.

The open-source engine must remain independently useful, and the product layer
must use it without weakening its invariants.

Detailed packaging, hosting, deployment, and integration mechanics remain
future-scoped.

## License

This repository and its reusable engine are licensed under Apache-2.0. The
repository license is established, not `TBD`.

See [Architecture](architecture.md), [accepted decisions](decisions/README.md),
and the [roadmap](roadmap.md) for current constraints and sequencing.
