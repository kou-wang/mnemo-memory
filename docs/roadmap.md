# Roadmap

This roadmap records sequence and intended outcomes. Detailed implementation
belongs in GitHub Issues and accepted architecture choices belong under
[decisions](decisions/README.md).

## 1. Sprint 1 — complete

Repository bootstrap, typed domain models, deterministic lifecycle behavior,
canonical scenario fixtures, and Python 3.11/3.12 quality gates are complete.
See the historical [Sprint 1 specification](sprint-1-spec.md).

## 2. Shared developer workflow — Issue #7

Establish one durable Issue → implementation → PR → review → repair → merge
workflow shared by ChatGPT/maintainers, Codex, and Cursor.

## 3. Sprint 2 interfaces — Issue #5

Define provider-independent extraction and storage interfaces after Issue #7 is
reviewed and merged. Do not add concrete providers or persistence technology as
part of the interface task unless Issue #5 explicitly requires it.

## 4. Extraction

Implement natural-language interpretation behind the approved extraction
boundary. Provider and model choices are `TBD`.

## 5. Entity resolution

Add conservative, explainable, reversible entity resolution without silent
ambiguous merges. Issue #16 adds explicit probabilistic entity-type hints to
unresolved extraction mentions as the bridge to future ingestion orchestration;
it does not change deterministic name/alias matching or create entities.
Detailed future algorithms and orchestration remain `TBD`.

## 6. Persistence

Persist structured and temporal memory behind the approved storage boundary.
Issue #14 establishes PostgreSQL through SQLAlchemy 2.x and psycopg 3, with
Alembic migrations and database-enforced current-state/user-scope invariants.
Vector and semantic indexing choices remain `TBD`.

## 7. Ingestion orchestration

Issue #18 connects capture-first provenance, typed entity resolution/creation,
validated memory materialization, deterministic lifecycle reconciliation, and
repository writes. It is the internal write-path bridge before recall and does
not add lifecycle-command interpretation or a cross-repository unit of work.

## 8. Retrieval and temporal recall

Issue #20 adds the first deterministic structured and temporal recall layer:
explicit subject resolution outcomes, current/active/history/latest modes,
temporal validity, stable PostgreSQL queries, and provenance-preserving evidence.
Issue #22 adds probabilistic natural-language planning into one or more existing
structured recall requests, with explicit unsupported/ambiguous abstention and
relative time anchored only to the supplied question timestamp. Aggregation,
grounded synthesis, and semantic/hybrid retrieval remain later work.
Semantic/vector lookup is a fallback or augmentation after structured retrieval,
not the primary path.

## 9. Evaluation

Turn canonical scenarios into repeatable extraction, lifecycle, retrieval,
temporal-query, and end-to-end evaluation datasets and gates. Metrics and
thresholds beyond established lifecycle coverage are `TBD`.

## 10. Consumer and mobile application work

Build the low-friction consumer experience on top of the reusable engine after
the engine boundaries are stable. The established direction is iOS-first using
React Native + Expo while preserving an Android path. Detailed application
implementation, release planning, and rollout remain future-scoped.

Current implementation and review state lives in
[Project status](project-status.md), not in this roadmap.
