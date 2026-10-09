"""Run Mnemo's 100% deterministic contract evaluation gate."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Engine

from mnemo.entities import DeterministicEntityResolver
from mnemo.evaluation import (
    EvaluationDomain,
    EvaluationResult,
    StructuredRecallEvaluationCase,
    build_report,
    evaluate_structured_recall,
    evaluation_exit_code,
    run_core_evaluations,
)
from mnemo.interfaces.queries import MemoryQuery, MemoryQueryOrder
from mnemo.models.capture import Capture, SourceType
from mnemo.models.entity import Entity, EntityType
from mnemo.models.memory import Memory
from mnemo.models.types import MemoryKind, MemoryStatus
from mnemo.persistence.postgres.repositories import (
    PostgresCaptureRepository,
    PostgresEntityRepository,
    PostgresMemoryQueryRepository,
    PostgresMemoryRepository,
)
from mnemo.persistence.postgres.session import create_postgres_engine, create_session_factory
from mnemo.recall import RecallMode, RecallOutcome, StructuredRecallRequest, StructuredRecallService

ROOT = Path(__file__).parents[1]
USER_ID = "evaluation-user"
OTHER_USER_ID = "other-evaluation-user"
NOW = datetime(2026, 10, 9, 20, tzinfo=UTC)


def _id(number: int) -> UUID:
    return UUID(int=120_000 + number)


@dataclass(frozen=True)
class _FixedClock:
    instant: datetime

    def now(self) -> datetime:
        return self.instant


def _entity(number: int, name: str, entity_type: EntityType, *, user_id: str = USER_ID) -> Entity:
    return Entity(
        id=_id(number),
        user_id=user_id,
        type=entity_type,
        canonical_name=name,
    )


def _memory(
    number: int,
    *,
    subject: Entity,
    kind: MemoryKind,
    predicate: str,
    value: object,
    observed_at: datetime,
    occurred_at: datetime | None = None,
    status: MemoryStatus = MemoryStatus.ACTIVE,
    valid_until: datetime | None = None,
    user_id: str = USER_ID,
) -> Memory:
    return Memory(
        id=_id(number),
        user_id=user_id,
        kind=kind,
        subject_entity_id=subject.id,
        predicate=predicate,
        value=value,
        status=status,
        observed_at=observed_at,
        occurred_at=occurred_at,
        valid_until=valid_until,
        memory_key=(
            Memory.build_memory_key(subject.id, predicate)
            if kind == MemoryKind.CURRENT_STATE
            else None
        ),
        source_capture_id=_id(1_000 + number),
        created_at=observed_at,
        updated_at=observed_at,
    )


def _request(
    *,
    subject: str,
    kind: MemoryKind,
    predicate: str,
    mode: RecallMode,
) -> StructuredRecallRequest:
    return StructuredRecallRequest(
        user_id=USER_ID,
        subject=subject,
        kind=kind,
        predicate=predicate,
        mode=mode,
    )


def _persist_capture(captures: PostgresCaptureRepository, memory: Memory) -> None:
    if memory.source_capture_id is None:
        raise ValueError("evaluation memories require source provenance")
    captures.add(
        user_id=memory.user_id,
        capture=Capture(
            id=memory.source_capture_id,
            user_id=memory.user_id,
            source_type=SourceType.TEXT,
            raw_text=f"evaluation capture for {memory.predicate}",
            captured_at=memory.observed_at,
            created_at=memory.observed_at,
        ),
    )


def _clear_evaluation_rows(engine: Engine) -> None:
    with engine.begin() as connection:
        for table in ("memories", "captures", "entities"):
            connection.execute(
                text(f"DELETE FROM {table} WHERE user_id IN (:user_id, :other_user_id)"),
                {"user_id": USER_ID, "other_user_id": OTHER_USER_ID},
            )


def _seed_and_cases(
    *,
    captures: PostgresCaptureRepository,
    entities: PostgresEntityRepository,
    memories: PostgresMemoryRepository,
) -> tuple[StructuredRecallEvaluationCase, ...]:
    car = _entity(1, "my car", EntityType.VEHICLE)
    passport = _entity(2, "my passport", EntityType.OBJECT)
    kevin = _entity(3, "Kevin", EntityType.PERSON)
    me = _entity(4, "me", EntityType.PERSON)
    vehicle = _entity(5, "my vehicle", EntityType.VEHICLE)
    alex_one = _entity(6, "Alex", EntityType.PERSON)
    alex_two = _entity(7, "Alexander", EntityType.PERSON)
    alex_two.aliases = ["Alex"]
    foreign = _entity(8, "shared car", EntityType.VEHICLE, user_id=OTHER_USER_ID)
    maya = _entity(9, "Maya", EntityType.PERSON)
    for entity in (car, passport, kevin, me, vehicle, alex_one, alex_two, maya):
        entities.add(user_id=USER_ID, entity=entity)
    entities.add(user_id=OTHER_USER_ID, entity=foreign)

    old_parking = _memory(
        100,
        subject=car,
        kind=MemoryKind.CURRENT_STATE,
        predicate="parked_at",
        value="A1",
        observed_at=NOW - timedelta(hours=2),
    )
    current_parking = _memory(
        101,
        subject=car,
        kind=MemoryKind.CURRENT_STATE,
        predicate="parked_at",
        value="B7",
        observed_at=NOW - timedelta(hours=1),
    )
    _persist_capture(captures, old_parking)
    _persist_capture(captures, current_parking)
    memories.append(user_id=USER_ID, memory=old_parking)
    memories.supersede_current_state(
        user_id=USER_ID,
        current_memory_id=old_parking.id,
        incoming=current_parking,
    )
    passport_memory = _memory(
        102,
        subject=passport,
        kind=MemoryKind.CURRENT_STATE,
        predicate="located_at",
        value="desk drawer",
        observed_at=NOW - timedelta(minutes=50),
    )
    birthday_one = _memory(
        103,
        subject=kevin,
        kind=MemoryKind.FACT,
        predicate="birthday",
        value="March 12",
        observed_at=NOW - timedelta(days=2),
    )
    birthday_two = _memory(
        104,
        subject=kevin,
        kind=MemoryKind.FACT,
        predicate="birthday",
        value="March 13",
        observed_at=NOW - timedelta(days=1),
    )
    coffee = _memory(
        105,
        subject=kevin,
        kind=MemoryKind.PREFERENCE,
        predicate="likes",
        value="coffee",
        observed_at=NOW - timedelta(days=2),
    )
    jazz = _memory(
        106,
        subject=kevin,
        kind=MemoryKind.PREFERENCE,
        predicate="likes",
        value="jazz",
        observed_at=NOW - timedelta(days=1),
    )
    bench_old = _memory(
        107,
        subject=me,
        kind=MemoryKind.EVENT,
        predicate="bench_press",
        value="185x5",
        observed_at=NOW - timedelta(days=4),
        occurred_at=NOW - timedelta(days=3),
    )
    bench_new = _memory(
        108,
        subject=me,
        kind=MemoryKind.EVENT,
        predicate="bench_press",
        value="190x5",
        observed_at=NOW - timedelta(days=2),
        occurred_at=NOW - timedelta(days=1),
    )
    oil_old = _memory(
        109,
        subject=vehicle,
        kind=MemoryKind.EVENT,
        predicate="oil_changed",
        value={"mileage": 40_000},
        observed_at=NOW - timedelta(days=40),
        occurred_at=NOW - timedelta(days=40),
    )
    oil_new = _memory(
        110,
        subject=vehicle,
        kind=MemoryKind.EVENT,
        predicate="oil_changed",
        value={"mileage": 42_000},
        observed_at=NOW - timedelta(days=2),
        occurred_at=NOW - timedelta(days=2),
    )
    milk = _memory(
        111,
        subject=me,
        kind=MemoryKind.INTENT,
        predicate="buy",
        value="milk",
        observed_at=NOW - timedelta(hours=3),
    )
    eggs = _memory(
        112,
        subject=me,
        kind=MemoryKind.INTENT,
        predicate="buy",
        value="eggs",
        observed_at=NOW - timedelta(hours=2),
    )
    stale = _memory(
        113,
        subject=me,
        kind=MemoryKind.FACT,
        predicate="temporary_note",
        value="stale",
        observed_at=NOW - timedelta(days=3),
        valid_until=NOW - timedelta(days=1),
    )
    foreign_memory = _memory(
        114,
        subject=foreign,
        kind=MemoryKind.CURRENT_STATE,
        predicate="parked_at",
        value="FOREIGN",
        observed_at=NOW,
        user_id=OTHER_USER_ID,
    )
    maya_birthday = _memory(
        115,
        subject=maya,
        kind=MemoryKind.FACT,
        predicate="birthday",
        value="April 4",
        observed_at=NOW - timedelta(days=1),
    )
    for memory in (
        passport_memory,
        birthday_one,
        birthday_two,
        coffee,
        jazz,
        bench_old,
        bench_new,
        oil_old,
        oil_new,
        milk,
        eggs,
        stale,
        maya_birthday,
    ):
        _persist_capture(captures, memory)
        memories.append(user_id=USER_ID, memory=memory)
    _persist_capture(captures, foreign_memory)
    memories.append(user_id=OTHER_USER_ID, memory=foreign_memory)
    memories.transition_status(
        user_id=USER_ID,
        memory_id=eggs.id,
        expected_status=MemoryStatus.ACTIVE,
        target_status=MemoryStatus.COMPLETED,
    )

    def case(
        case_id: str,
        request: StructuredRecallRequest,
        values: tuple[object, ...],
        source_ids: tuple[UUID | None, ...],
        outcome: RecallOutcome = RecallOutcome.FOUND,
    ) -> StructuredRecallEvaluationCase:
        return StructuredRecallEvaluationCase(
            case_id=case_id,
            domain=EvaluationDomain.STRUCTURED_RECALL,
            request=request,
            expected_outcome=outcome,
            expected_values=values,
            expected_source_capture_ids=source_ids,
        )

    return (
        case(
            "current_parking",
            _request(
                subject="my car",
                kind=MemoryKind.CURRENT_STATE,
                predicate="parked_at",
                mode=RecallMode.CURRENT,
            ),
            ("B7",),
            (current_parking.source_capture_id,),
        ),
        case(
            "passport_location",
            _request(
                subject="my passport",
                kind=MemoryKind.CURRENT_STATE,
                predicate="located_at",
                mode=RecallMode.CURRENT,
            ),
            ("desk drawer",),
            (passport_memory.source_capture_id,),
        ),
        case(
            "birthday_fact",
            _request(
                subject="Maya",
                kind=MemoryKind.FACT,
                predicate="birthday",
                mode=RecallMode.CURRENT,
            ),
            ("April 4",),
            (maya_birthday.source_capture_id,),
        ),
        case(
            "multiple_fact_values",
            _request(
                subject="Kevin",
                kind=MemoryKind.FACT,
                predicate="birthday",
                mode=RecallMode.CURRENT,
            ),
            ("March 13", "March 12"),
            (birthday_two.source_capture_id, birthday_one.source_capture_id),
        ),
        case(
            "multiple_preferences",
            _request(
                subject="Kevin",
                kind=MemoryKind.PREFERENCE,
                predicate="likes",
                mode=RecallMode.ACTIVE,
            ),
            ("jazz", "coffee"),
            (jazz.source_capture_id, coffee.source_capture_id),
        ),
        case(
            "event_history_ordering",
            _request(
                subject="me",
                kind=MemoryKind.EVENT,
                predicate="bench_press",
                mode=RecallMode.HISTORY,
            ),
            ("190x5", "185x5"),
            (bench_new.source_capture_id, bench_old.source_capture_id),
        ),
        case(
            "latest_event",
            _request(
                subject="my vehicle",
                kind=MemoryKind.EVENT,
                predicate="oil_changed",
                mode=RecallMode.LATEST,
            ),
            ({"mileage": 42_000},),
            (oil_new.source_capture_id,),
        ),
        case(
            "active_intents_only",
            _request(
                subject="me",
                kind=MemoryKind.INTENT,
                predicate="buy",
                mode=RecallMode.ACTIVE,
            ),
            ("milk",),
            (milk.source_capture_id,),
        ),
        case(
            "stale_temporal_exclusion",
            _request(
                subject="me",
                kind=MemoryKind.FACT,
                predicate="temporary_note",
                mode=RecallMode.CURRENT,
            ),
            (),
            (),
            RecallOutcome.NOT_FOUND,
        ),
        case(
            "missing_subject",
            _request(
                subject="missing",
                kind=MemoryKind.FACT,
                predicate="birthday",
                mode=RecallMode.CURRENT,
            ),
            (),
            (),
            RecallOutcome.NOT_FOUND,
        ),
        case(
            "ambiguous_subject",
            _request(
                subject="Alex",
                kind=MemoryKind.FACT,
                predicate="birthday",
                mode=RecallMode.CURRENT,
            ),
            (),
            (),
            RecallOutcome.AMBIGUOUS_SUBJECT,
        ),
        case(
            "user_isolation",
            _request(
                subject="shared car",
                kind=MemoryKind.CURRENT_STATE,
                predicate="parked_at",
                mode=RecallMode.CURRENT,
            ),
            (),
            (),
            RecallOutcome.NOT_FOUND,
        ),
    )


def _evaluate_superseded_parking_history(
    queries: PostgresMemoryQueryRepository,
) -> EvaluationResult:
    history = tuple(
        queries.query(
            MemoryQuery(
                user_id=USER_ID,
                statuses=None,
                kind=MemoryKind.CURRENT_STATE,
                subject_entity_id=_id(1),
                predicate="parked_at",
                order=MemoryQueryOrder.EVENT_TIME_DESC,
            )
        )
    )
    failures: list[str] = []
    if tuple(memory.value for memory in history) != ("B7", "A1"):
        failures.append("superseded parking history was not returned newest-first")
    if tuple(memory.status for memory in history) != (
        MemoryStatus.ACTIVE,
        MemoryStatus.SUPERSEDED,
    ):
        failures.append("parking history did not preserve active/superseded states")
    if len(history) == 2 and history[1].superseded_by_id != history[0].id:
        failures.append("superseded parking record did not link to its replacement")
    if any(memory.source_capture_id is None for memory in history):
        failures.append("parking history lost source-capture provenance")
    return EvaluationResult(
        case_id="superseded_parking_history",
        domain=EvaluationDomain.STRUCTURED_RECALL,
        passed=not failures,
        diagnostic="; ".join(failures) if failures else None,
    )


def run(database_url: str, *, json_output: Path | None = None) -> int:
    alembic_config = Config(str(ROOT / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(ROOT / "migrations"))
    alembic_config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(alembic_config, "head")
    engine = create_postgres_engine(database_url)
    try:
        _clear_evaluation_rows(engine)
        factory = create_session_factory(engine)
        captures = PostgresCaptureRepository(factory)
        entities = PostgresEntityRepository(factory)
        memories = PostgresMemoryRepository(factory)
        queries = PostgresMemoryQueryRepository(factory)
        cases = _seed_and_cases(captures=captures, entities=entities, memories=memories)
        service = StructuredRecallService(
            entity_resolver=DeterministicEntityResolver(entities),
            memory_query_repository=queries,
            clock=_FixedClock(NOW),
        )
        structured_results = (
            *evaluate_structured_recall(service=service, cases=cases),
            _evaluate_superseded_parking_history(queries),
        )
        core_report = run_core_evaluations()
        report = build_report((*core_report.results, *structured_results))
        print(report.human_summary())
        if json_output is not None:
            json_output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return evaluation_exit_code(report)
    finally:
        try:
            _clear_evaluation_rows(engine)
        finally:
            engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.environ.get("MNEMO_TEST_DATABASE_URL"))
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or MNEMO_TEST_DATABASE_URL is required")
    return run(args.database_url, json_output=args.json_output)


if __name__ == "__main__":
    raise SystemExit(main())
