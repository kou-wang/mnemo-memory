# Development Workflow

GitHub is the durable handoff point for planning, implementation, review, and
merge. Chat conversations may support the work, but must not be the only record
of scope, decisions, or review findings.

## Source-of-truth hierarchy

The authoritative order is:

1. GitHub Issue for task-specific scope and acceptance criteria;
2. root [`AGENTS.md`](../AGENTS.md) for shared engineering rules;
3. [architecture](architecture.md) for current boundaries and invariants;
4. [accepted decisions](decisions/README.md) for durable decisions;
5. [product requirements](product-requirements.md) for approved requirements;
6. [roadmap](roadmap.md) for phase sequencing;
7. [project status](project-status.md) for current state;
8. tool-specific entrypoints for tool behavior only.

If sources conflict, stop and ask the maintainer/architect to resolve the
contradiction. Do not silently choose or rewrite an accepted decision.

## Issue-to-merge lifecycle

1. ChatGPT or the maintainer defines/refines a GitHub Issue with scope,
   acceptance criteria, non-goals, and dependencies.
2. Codex reads the full Issue and the repository guidance linked above.
3. Codex starts from updated `main`, creates or uses a focused feature branch,
   and implements only that Issue.
4. Codex runs every required local quality gate and records the results.
5. Codex pushes and opens or updates a PR linked to the Issue.
6. ChatGPT or the maintainer reviews the GitHub diff directly against scope,
   correctness, architecture, tests, security/privacy, and maintainability.
7. Failed criteria become concrete PR review comments and a focused repair
   request; they are not left only in chat.
8. Codex implements the requested repairs, reruns gates, and pushes again.
9. The reviewer checks the revised code and CI again.
10. Merge only after review passes and CI is green.
11. Update `docs/project-status.md` and close the Issue when appropriate.

Implementation agents do not approve their own work. They may report that an
implementation is complete and awaiting review, but only the maintainer/reviewer
marks it reviewed or authorizes merge.

## Working agreements

- No direct feature work on `main`.
- Prefer one primary Issue per implementation PR.
- Do not silently expand scope; create or refine an Issue for additional work.
- Architecture changes require an added or updated ADR and explicit review.
- Product requirement changes require maintainer approval and an update to
  `docs/product-requirements.md`.
- Preserve accepted decisions and history when reorganizing documentation.
- Never commit secrets, credentials, or real personal data.

## Quality and merge gates

Run locally:

```bash
ruff check .
mypy src
pytest --cov=mnemo --cov-report=term-missing
coverage report --include="*/mnemo/lifecycle/*" --fail-under=90
python scripts/run_deterministic_evaluation.py
```

The deterministic evaluation command also requires the disposable PostgreSQL
test database described in [Evaluation](evaluation.md).

CI runs stable checks named `Quality gates (Python 3.11)` and
`Quality gates (Python 3.12)`. Repository administrators may make those checks
required through GitHub rules or branch protection. The workflow does not imply
that protection is enabled, and implementation agents must not claim it is
without verification.

Use the repository [pull request template](../.github/pull_request_template.md)
to record scope, evidence, impacts, and follow-ups.
