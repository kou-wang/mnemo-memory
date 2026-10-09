# Evaluation

Mnemo separates deterministic contract evaluation from provider/model quality
evaluation. They answer different questions and must not be reported as the
same result.

## Deterministic contract gate

The deterministic harness verifies invariants of the implemented memory
pipeline with fixed identifiers, timestamps, inputs, and expected outputs. It
covers:

- lifecycle append, no-op, supersession, transition, provenance, and user-scope
  behavior;
- exact canonical-name and alias entity resolution, ambiguity, normalization,
  and user isolation;
- the typed recall-planning fixture contract, including explicit abstentions
  and relative-time request labels;
- structured and temporal recall against real PostgreSQL, including ordering,
  temporal validity, ambiguity, user isolation, and source-capture provenance;
- grounded-answer abstention, evidence handoff, partial results, citation
  requirements, multi-valued facts, and fail-closed invariants using a fake
  synthesizer.

These cases encode deterministic contracts, so the required pass rate is 100%.
The command exits nonzero if any case fails and emits a concise per-domain
summary:

```bash
export MNEMO_TEST_DATABASE_URL="postgresql+psycopg://USER:PASSWORD@HOST/TEST_DATABASE"
python scripts/run_deterministic_evaluation.py
```

The database must be disposable and have the PostgreSQL extensions/permissions
needed by the normal migrations. The runner migrates it, uses only the reserved
`evaluation-user` and `other-evaluation-user` scopes, and removes those rows
when it finishes. CI runs this command in both supported Python jobs against
the isolated PostgreSQL service.

Pass `--json-output PATH` to write the versioned, JSON-serializable report. Each
result has a stable case id, domain, pass/fail value, and failure diagnostic;
each domain summary includes counts and pass rate. The public evaluation module
also exposes precision, recall, and F1 helpers for classification datasets where
those metrics are meaningful. Empty denominators produce `0.0` explicitly.

## Recall-planning fixture

The canonical recall-planning labels live in
`mnemo.evaluation.data/recall_planning.json` and are loaded as typed evaluation
cases. This promotes the earlier test seed into the reusable harness and keeps
one canonical copy.

The deterministic gate validates the fixture and provider-independent plan
contract. It does **not** call OpenAI and does **not** claim that a model produced
the expected plans. Fake or mocked provider outputs demonstrate parsing and
contract behavior, not real model accuracy.

## Provider/model quality evaluation

Live extraction and planning quality must be evaluated separately with an
explicit provider, model version, prompt version, dataset version, and run
timestamp. Such a run may use typed extraction/planning cases and classification
metrics from `mnemo.evaluation`, but it is not part of CI, must never contain
real personal data, and must not be described as deterministic.

The report records `provider_quality_evaluated=false`; its human summary prints
`provider_model_quality: not_run`. Thresholds for future live-provider quality
benchmarks remain TBD and require explicit maintainer approval.

## Dataset ownership and versioning

The repository owns the canonical contract datasets. Changes are reviewed with
the implementation that changes the contract, use stable case ids, and remain
in version control; reports carry a schema version so stored results can be
interpreted later. A failing case must not be relabeled merely to restore a
green gate. Synthetic fixture changes that alter established semantics require
the same architecture or decision review as the underlying behavior.

Future semantic or hybrid retrieval evaluation should run alongside this
baseline on separately labeled datasets and report its own precision/recall/F1
or ranking metrics as appropriate. It must continue running the deterministic
structured baseline unchanged, compare results by dataset and report version,
and must not hide regressions behind an aggregate model-quality score.

## Adding cases

Add a stable typed case when a deterministic contract changes or a regression
is discovered. Keep fixtures synthetic, timezone-aware, user-scoped, and
provenance-bearing. PostgreSQL recall cases belong in the command's seeded
dataset; network-free lifecycle, entity, planning-fixture, and grounding cases
belong in their respective `mnemo.evaluation` modules. A contract change still
requires the normal architecture/decision review; changing an expected value is
not a way to bypass a failing invariant.
