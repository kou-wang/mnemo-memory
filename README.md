# mnemo-memory

Open-source temporal memory engine for everyday AI applications.

Mnemo turns short, natural-language captures into structured personal memories that can be updated, superseded, expired, aggregated, and recalled over time.

## Product principles

- **Memory, not notes.** Store structured facts, preferences, current state, events, and intents.
- **Deterministic lifecycle.** LLMs interpret language; code controls persistence and state transitions.
- **Temporal by default.** Current state can supersede prior state without deleting history.
- **Source-backed recall.** Every memory keeps provenance to the original capture.
- **Prefer no answer to a false memory.** Recall should abstain when evidence is insufficient.

## Core memory kinds

- `FACT` — durable facts such as birthdays.
- `PREFERENCE` — likes/dislikes that may evolve.
- `CURRENT_STATE` — mutable state such as parking or object location.
- `EVENT` — append-only history such as workouts or maintenance.
- `INTENT` — future wants/actions such as shopping, reading, or visiting.

## Sprint 1

Sprint 1 establishes the domain model and deterministic lifecycle rules before adding LLM extraction or storage adapters.

See [docs/architecture.md](docs/architecture.md) and [docs/sprint-1-spec.md](docs/sprint-1-spec.md).

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## License

Apache-2.0.
