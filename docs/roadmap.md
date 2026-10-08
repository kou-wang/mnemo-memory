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
ambiguous merges. Detailed algorithms are `TBD`.

## 6. Persistence

Persist structured and temporal memory behind the approved storage boundary.
Database and indexing choices are `TBD`.

## 7. Retrieval and temporal recall

Support structured lookup, temporal lookup, aggregation, and semantic/hybrid
retrieval where necessary, with grounded synthesized answers and abstention.

## 8. Evaluation

Turn canonical scenarios into repeatable extraction, lifecycle, retrieval,
temporal-query, and end-to-end evaluation datasets and gates. Metrics and
thresholds beyond established lifecycle coverage are `TBD`.

## 9. Consumer and mobile application work

Build the low-friction consumer experience on top of the reusable engine after
the engine boundaries are stable. Product platform, framework, and rollout
details are `TBD`.

Current implementation and review state lives in
[Project status](project-status.md), not in this roadmap.
