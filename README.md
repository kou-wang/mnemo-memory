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

## Project documentation

Sprint 1 established the domain model and deterministic lifecycle rules before
LLM extraction or storage adapters. The shared project context is organized as:

- [Architecture](docs/architecture.md)
- [Accepted decisions](docs/decisions/README.md)
- [Product requirements](docs/product-requirements.md)
- [Roadmap](docs/roadmap.md)
- [Project status](docs/project-status.md)
- [Development workflow](docs/development-workflow.md)
- [Sprint 1 specification](docs/sprint-1-spec.md)

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
ruff check .
mypy src
pytest --cov=mnemo --cov-report=term-missing
coverage report --include="*/mnemo/lifecycle/*" --fail-under=90
```

These are the same gates run by CI on Python 3.11 and 3.12. The lifecycle
coverage command fails below 90% without imposing that threshold on unrelated
future packages.

### Optional OpenAI extractor

Install the provider adapter only when needed:

```bash
pip install -e ".[openai]"
```

With `OPENAI_API_KEY` configured by the application, inject a Structured
Outputs-capable model name:

```python
from mnemo.providers.openai import OpenAIExtractor

extractor = OpenAIExtractor(model="YOUR_STRUCTURED_OUTPUT_MODEL")
candidates = extractor.extract(capture)
```

The adapter sends capture text to an external AI provider. It only interprets
language into candidate memories; persistence, entity resolution, and lifecycle
mutations remain separate deterministic responsibilities.

The workflow exposes stable `Quality gates (Python 3.11)` and
`Quality gates (Python 3.12)` checks. Repository administrators must configure
those checks as required in GitHub branch protection; the workflow itself
cannot enable branch protection.

## License

Apache-2.0.
