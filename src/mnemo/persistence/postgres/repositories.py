"""Synchronous SQLAlchemy implementations of Mnemo repository contracts."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from mnemo.interfaces.queries import MemoryQuery, MemoryQueryOrder, MemoryQueryRepository
from mnemo.interfaces.repositories import (
    CaptureRepository,
    EntityRepository,
    MemoryRepository,
    RepositoryInvariantError,
)
from mnemo.lifecycle.engine import LifecycleEngine, LifecycleInvariantError
from mnemo.models.capture import Capture
from mnemo.models.entity import Entity
from mnemo.models.memory import Memory
from mnemo.models.types import MemoryKind, MemoryStatus
from mnemo.persistence.postgres.mapping import (
    capture_from_row,
    capture_to_row,
    entity_from_row,
    entity_to_row,
    memory_from_row,
    memory_to_row,
)
from mnemo.persistence.postgres.tables import CaptureRow, EntityRow, MemoryRow


class PostgresRepositoryError(RuntimeError):
    """A sanitized unexpected PostgreSQL operational failure."""


class _PostgresRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    @staticmethod
    def _raise_write_error(
        error: IntegrityError | OperationalError,
        *,
        record_type: str,
    ) -> None:
        if isinstance(error, OperationalError):
            raise PostgresRepositoryError(
                f"PostgreSQL {record_type} operation failed"
            ) from None
        raise RepositoryInvariantError(
            f"{record_type} violates PostgreSQL repository constraints"
        ) from None


class PostgresCaptureRepository(_PostgresRepository, CaptureRepository):
    """PostgreSQL capture persistence with one transaction per mutation."""

    def add(self, *, user_id: str, capture: Capture) -> None:
        if capture.user_id != user_id:
            raise RepositoryInvariantError("capture belongs to a different user")
        try:
            with self._sessions.begin() as session:
                session.add(capture_to_row(capture))
        except (IntegrityError, OperationalError) as error:
            self._raise_write_error(error, record_type="capture")

    def get(self, *, user_id: str, capture_id: UUID) -> Capture | None:
        try:
            with self._sessions() as session:
                row = session.scalar(
                    select(CaptureRow).where(
                        CaptureRow.user_id == user_id,
                        CaptureRow.id == capture_id,
                    )
                )
        except OperationalError:
            raise PostgresRepositoryError("PostgreSQL capture lookup failed") from None
        return None if row is None else capture_from_row(row)


class PostgresEntityRepository(_PostgresRepository, EntityRepository):
    """PostgreSQL entity persistence without matching or alias side effects."""

    def add(self, *, user_id: str, entity: Entity) -> None:
        if entity.user_id != user_id:
            raise RepositoryInvariantError("entity belongs to a different user")
        try:
            with self._sessions.begin() as session:
                session.add(entity_to_row(entity))
        except (IntegrityError, OperationalError) as error:
            self._raise_write_error(error, record_type="entity")

    def get(self, *, user_id: str, entity_id: UUID) -> Entity | None:
        try:
            with self._sessions() as session:
                row = session.scalar(
                    select(EntityRow).where(
                        EntityRow.user_id == user_id,
                        EntityRow.id == entity_id,
                    )
                )
        except OperationalError:
            raise PostgresRepositoryError("PostgreSQL entity lookup failed") from None
        return None if row is None else entity_from_row(row)

    def list_for_user(self, *, user_id: str) -> Sequence[Entity]:
        try:
            with self._sessions() as session:
                rows = session.scalars(
                    select(EntityRow)
                    .where(EntityRow.user_id == user_id)
                    .order_by(EntityRow.id)
                ).all()
        except OperationalError:
            raise PostgresRepositoryError("PostgreSQL entity listing failed") from None
        return tuple(entity_from_row(row) for row in rows)


class PostgresMemoryRepository(_PostgresRepository, MemoryRepository):
    """PostgreSQL memory persistence with atomic lifecycle mutations."""

    def list_active(
        self,
        *,
        user_id: str,
        kind: MemoryKind | None = None,
        subject_entity_id: UUID | None = None,
        predicate: str | None = None,
        memory_key: str | None = None,
    ) -> Sequence[Memory]:
        statement = select(MemoryRow).where(
            MemoryRow.user_id == user_id,
            MemoryRow.status == MemoryStatus.ACTIVE.value,
        )
        if kind is not None:
            statement = statement.where(MemoryRow.kind == kind.value)
        if subject_entity_id is not None:
            statement = statement.where(MemoryRow.subject_entity_id == subject_entity_id)
        if predicate is not None:
            statement = statement.where(MemoryRow.predicate == predicate)
        if memory_key is not None:
            statement = statement.where(MemoryRow.memory_key == memory_key)
        statement = statement.order_by(MemoryRow.observed_at, MemoryRow.id)

        try:
            with self._sessions() as session:
                rows = session.scalars(statement).all()
        except OperationalError:
            raise PostgresRepositoryError("PostgreSQL memory listing failed") from None
        return tuple(memory_from_row(row) for row in rows)

    def get(self, *, user_id: str, memory_id: UUID) -> Memory | None:
        try:
            with self._sessions() as session:
                row = session.scalar(
                    select(MemoryRow).where(
                        MemoryRow.user_id == user_id,
                        MemoryRow.id == memory_id,
                    )
                )
        except OperationalError:
            raise PostgresRepositoryError("PostgreSQL memory lookup failed") from None
        return None if row is None else memory_from_row(row)

    def append(self, *, user_id: str, memory: Memory) -> None:
        self._require_owner(user_id=user_id, memory=memory)
        try:
            with self._sessions.begin() as session:
                session.add(memory_to_row(memory))
        except (IntegrityError, OperationalError) as error:
            self._raise_write_error(error, record_type="memory")

    def supersede_current_state(
        self,
        *,
        user_id: str,
        current_memory_id: UUID,
        incoming: Memory,
    ) -> None:
        self._require_owner(user_id=user_id, memory=incoming)
        try:
            with self._sessions.begin() as session:
                current_row = self._locked_memory(
                    session=session,
                    user_id=user_id,
                    memory_id=current_memory_id,
                )
                if current_row is None:
                    raise RepositoryInvariantError(
                        "active current memory was not found for user"
                    )
                current = memory_from_row(current_row)
                if (
                    current.status != MemoryStatus.ACTIVE
                    or current.kind != MemoryKind.CURRENT_STATE
                    or incoming.kind != MemoryKind.CURRENT_STATE
                    or incoming.status != MemoryStatus.ACTIVE
                    or current.memory_key != incoming.memory_key
                ):
                    raise RepositoryInvariantError("invalid CURRENT_STATE supersession")
                if session.get(MemoryRow, incoming.id) is not None:
                    raise RepositoryInvariantError("incoming memory id already exists")
                LifecycleEngine().validate_status_transition(
                    kind=current.kind,
                    current=current.status,
                    target=MemoryStatus.SUPERSEDED,
                )

                current_row.status = MemoryStatus.SUPERSEDED.value
                current_row.superseded_by_id = incoming.id
                session.flush()
                session.add(memory_to_row(incoming))
        except RepositoryInvariantError:
            raise
        except LifecycleInvariantError as error:
            raise RepositoryInvariantError(str(error)) from None
        except (IntegrityError, OperationalError) as error:
            self._raise_write_error(error, record_type="memory supersession")

    def transition_status(
        self,
        *,
        user_id: str,
        memory_id: UUID,
        expected_status: MemoryStatus,
        target_status: MemoryStatus,
    ) -> None:
        if target_status == MemoryStatus.SUPERSEDED:
            raise RepositoryInvariantError(
                "SUPERSEDED requires a replacement-aware atomic repository operation"
            )
        try:
            with self._sessions.begin() as session:
                row = self._locked_memory(
                    session=session,
                    user_id=user_id,
                    memory_id=memory_id,
                )
                if row is None:
                    raise RepositoryInvariantError("memory was not found for user")
                memory = memory_from_row(row)
                if memory.status != expected_status:
                    raise RepositoryInvariantError(
                        "memory status does not match expected_status"
                    )
                LifecycleEngine().validate_status_transition(
                    kind=memory.kind,
                    current=memory.status,
                    target=target_status,
                )
                row.status = target_status.value
        except RepositoryInvariantError:
            raise
        except LifecycleInvariantError as error:
            raise RepositoryInvariantError(str(error)) from None
        except (IntegrityError, OperationalError) as error:
            self._raise_write_error(error, record_type="memory status transition")

    @staticmethod
    def _locked_memory(
        *,
        session: Session,
        user_id: str,
        memory_id: UUID,
    ) -> MemoryRow | None:
        return session.scalar(
            select(MemoryRow)
            .where(MemoryRow.user_id == user_id, MemoryRow.id == memory_id)
            .with_for_update()
        )

    @staticmethod
    def _require_owner(*, user_id: str, memory: Memory) -> None:
        if memory.user_id != user_id:
            raise RepositoryInvariantError("memory belongs to a different user")


class PostgresMemoryQueryRepository(_PostgresRepository, MemoryQueryRepository):
    """PostgreSQL structured/temporal memory reads with stable ordering."""

    def query(self, query: MemoryQuery) -> Sequence[Memory]:
        statement = select(MemoryRow).where(MemoryRow.user_id == query.user_id)
        if query.statuses is not None:
            statement = statement.where(
                MemoryRow.status.in_(tuple(status.value for status in query.statuses))
            )
        if query.kind is not None:
            statement = statement.where(MemoryRow.kind == query.kind.value)
        if query.subject_entity_id is not None:
            statement = statement.where(MemoryRow.subject_entity_id == query.subject_entity_id)
        if query.predicate is not None:
            statement = statement.where(MemoryRow.predicate == query.predicate)
        if query.object_entity_id is not None:
            statement = statement.where(MemoryRow.object_entity_id == query.object_entity_id)
        if query.occurred_at_from is not None:
            statement = statement.where(MemoryRow.occurred_at >= query.occurred_at_from)
        if query.occurred_at_until is not None:
            statement = statement.where(MemoryRow.occurred_at <= query.occurred_at_until)
        if query.observed_at_from is not None:
            statement = statement.where(MemoryRow.observed_at >= query.observed_at_from)
        if query.observed_at_until is not None:
            statement = statement.where(MemoryRow.observed_at <= query.observed_at_until)

        event_time = func.coalesce(MemoryRow.occurred_at, MemoryRow.observed_at)
        if query.event_time_from is not None:
            statement = statement.where(event_time >= query.event_time_from)
        if query.event_time_until is not None:
            statement = statement.where(event_time <= query.event_time_until)
        if query.valid_at is not None:
            statement = statement.where(
                or_(MemoryRow.valid_from.is_(None), MemoryRow.valid_from <= query.valid_at),
                or_(MemoryRow.valid_until.is_(None), MemoryRow.valid_until >= query.valid_at),
                or_(MemoryRow.expires_at.is_(None), MemoryRow.expires_at > query.valid_at),
            )

        if query.order == MemoryQueryOrder.OBSERVED_AT_ASC:
            statement = statement.order_by(MemoryRow.observed_at, MemoryRow.id)
        elif query.order == MemoryQueryOrder.OBSERVED_AT_DESC:
            statement = statement.order_by(MemoryRow.observed_at.desc(), MemoryRow.id.desc())
        else:
            statement = statement.order_by(
                event_time.desc(), MemoryRow.observed_at.desc(), MemoryRow.id.desc()
            )
        statement = statement.limit(query.limit)

        try:
            with self._sessions() as session:
                rows = session.scalars(statement).all()
        except OperationalError:
            raise PostgresRepositoryError("PostgreSQL memory query failed") from None
        return tuple(memory_from_row(row) for row in rows)
