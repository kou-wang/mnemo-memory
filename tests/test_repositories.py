"""Test-double contract tests for provider-independent repositories."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from mnemo.interfaces.repositories import (
    CaptureRepository,
    MemoryRepository,
    RepositoryInvariantError,
)
from mnemo.lifecycle.engine import LifecycleAction, LifecycleEngine
from mnemo.models.capture import Capture, SourceType
from mnemo.models.memory import Memory
from mnemo.models.types import MemoryKind, MemoryStatus

NOW = datetime(2026, 10, 8, 15, tzinfo=UTC)


class FakeCaptureRepository:
    """Minimal user-scoped fake used only to exercise the protocol contract."""

    def __init__(self) -> None:
        self.records: dict[UUID, Capture] = {}

    def add(self, *, user_id: str, capture: Capture) -> None:
        if capture.user_id != user_id:
            raise RepositoryInvariantError("capture belongs to a different user")
        self.records[capture.id] = capture

    def get(self, *, user_id: str, capture_id: UUID) -> Capture | None:
        capture = self.records.get(capture_id)
        if capture is None or capture.user_id != user_id:
            return None
        return capture


class FakeMemoryRepository:
    """Small fake proving atomic method semantics without being production storage."""

    def __init__(self) -> None:
        self.records: dict[UUID, Memory] = {}
        self.write_operations: list[str] = []

    def list_active(
        self,
        *,
        user_id: str,
        kind: MemoryKind | None = None,
        subject_entity_id: UUID | None = None,
        predicate: str | None = None,
        memory_key: str | None = None,
    ) -> list[Memory]:
        return [
            memory
            for memory in self.records.values()
            if memory.user_id == user_id
            and memory.status == MemoryStatus.ACTIVE
            and (kind is None or memory.kind == kind)
            and (subject_entity_id is None or memory.subject_entity_id == subject_entity_id)
            and (predicate is None or memory.predicate == predicate)
            and (memory_key is None or memory.memory_key == memory_key)
        ]

    def get(self, *, user_id: str, memory_id: UUID) -> Memory | None:
        memory = self.records.get(memory_id)
        if memory is None or memory.user_id != user_id:
            return None
        return memory

    def append(self, *, user_id: str, memory: Memory) -> None:
        self._require_owner(user_id=user_id, memory=memory)
        if memory.id in self.records:
            raise RepositoryInvariantError("memory id already exists")
        self.records[memory.id] = memory
        self.write_operations.append("append")

    def supersede_current_state(
        self,
        *,
        user_id: str,
        current_memory_id: UUID,
        incoming: Memory,
    ) -> None:
        self._require_owner(user_id=user_id, memory=incoming)
        current = self.get(user_id=user_id, memory_id=current_memory_id)
        if current is None:
            raise RepositoryInvariantError("active current memory was not found for user")
        if (
            current.status != MemoryStatus.ACTIVE
            or current.kind != MemoryKind.CURRENT_STATE
            or incoming.kind != MemoryKind.CURRENT_STATE
            or incoming.status != MemoryStatus.ACTIVE
            or current.memory_key != incoming.memory_key
            or incoming.id in self.records
        ):
            raise RepositoryInvariantError("invalid CURRENT_STATE supersession")
        LifecycleEngine().validate_status_transition(
            kind=current.kind,
            current=current.status,
            target=MemoryStatus.SUPERSEDED,
        )

        # A real adapter performs these two durable changes in one transaction.
        self.records[current.id] = current.model_copy(
            update={
                "status": MemoryStatus.SUPERSEDED,
                "superseded_by_id": incoming.id,
            }
        )
        self.records[incoming.id] = incoming
        self.write_operations.append("supersede_current_state")

    def transition_status(
        self,
        *,
        user_id: str,
        memory_id: UUID,
        expected_status: MemoryStatus,
        target_status: MemoryStatus,
    ) -> None:
        memory = self.get(user_id=user_id, memory_id=memory_id)
        if memory is None:
            raise RepositoryInvariantError("memory was not found for user")
        if memory.status != expected_status:
            raise RepositoryInvariantError("memory status does not match expected_status")
        LifecycleEngine().validate_status_transition(
            kind=memory.kind,
            current=memory.status,
            target=target_status,
        )
        self.records[memory.id] = memory.model_copy(update={"status": target_status})
        self.write_operations.append("transition_status")

    @staticmethod
    def _require_owner(*, user_id: str, memory: Memory) -> None:
        if memory.user_id != user_id:
            raise RepositoryInvariantError("memory belongs to a different user")


def _capture(*, user_id: str = "user-1") -> Capture:
    return Capture(
        user_id=user_id,
        source_type=SourceType.TEXT,
        raw_text="I parked at A1.",
        captured_at=NOW,
        created_at=NOW,
    )


def _memory(
    *,
    kind: MemoryKind,
    value: object,
    user_id: str = "user-1",
    entity_id: UUID | None = None,
    predicate: str = "buy",
    source_capture_id: UUID | None = None,
) -> Memory:
    entity_id = entity_id or uuid4()
    return Memory(
        user_id=user_id,
        kind=kind,
        subject_entity_id=entity_id,
        predicate=predicate,
        value=value,
        observed_at=NOW,
        valid_from=NOW if kind in {MemoryKind.CURRENT_STATE, MemoryKind.INTENT} else None,
        memory_key=(
            Memory.build_memory_key(entity_id, predicate)
            if kind == MemoryKind.CURRENT_STATE
            else None
        ),
        source_capture_id=source_capture_id,
        created_at=NOW,
        updated_at=NOW,
    )


def test_capture_repository_lookup_is_user_scoped() -> None:
    repository: CaptureRepository = FakeCaptureRepository()
    capture = _capture()
    repository.add(user_id="user-1", capture=capture)

    assert repository.get(user_id="user-1", capture_id=capture.id) == capture
    assert repository.get(user_id="user-2", capture_id=capture.id) is None


def test_capture_repository_rejects_cross_user_add() -> None:
    repository: CaptureRepository = FakeCaptureRepository()

    with pytest.raises(RepositoryInvariantError):
        repository.add(user_id="user-1", capture=_capture(user_id="user-2"))


def test_memory_repository_lookup_and_active_filters_are_user_scoped() -> None:
    repository: MemoryRepository = FakeMemoryRepository()
    own = _memory(kind=MemoryKind.INTENT, value="AirPods")
    foreign = _memory(kind=MemoryKind.INTENT, value="headphones", user_id="user-2")
    repository.append(user_id="user-1", memory=own)
    repository.append(user_id="user-2", memory=foreign)

    assert repository.get(user_id="user-1", memory_id=own.id) == own
    assert repository.get(user_id="user-2", memory_id=own.id) is None
    assert list(repository.list_active(user_id="user-1", kind=MemoryKind.INTENT)) == [own]


def test_memory_repository_rejects_cross_user_append() -> None:
    repository: MemoryRepository = FakeMemoryRepository()
    foreign = _memory(kind=MemoryKind.EVENT, value="oil change", user_id="user-2")

    with pytest.raises(RepositoryInvariantError):
        repository.append(user_id="user-1", memory=foreign)


def test_append_preserves_memory_and_source_provenance() -> None:
    repository: MemoryRepository = FakeMemoryRepository()
    source_capture_id = uuid4()
    incoming = _memory(
        kind=MemoryKind.EVENT,
        value={"mileage": 42_800},
        source_capture_id=source_capture_id,
    )

    repository.append(user_id="user-1", memory=incoming)

    stored = repository.get(user_id="user-1", memory_id=incoming.id)
    assert stored == incoming
    assert stored is not None
    assert stored.source_capture_id == source_capture_id


def test_current_state_supersession_is_one_atomic_operation_and_retains_history() -> None:
    repository = FakeMemoryRepository()
    entity_id = uuid4()
    original_source = uuid4()
    incoming_source = uuid4()
    current = _memory(
        kind=MemoryKind.CURRENT_STATE,
        value="A1",
        entity_id=entity_id,
        predicate="parked_at",
        source_capture_id=original_source,
    )
    incoming = _memory(
        kind=MemoryKind.CURRENT_STATE,
        value="B7",
        entity_id=entity_id,
        predicate="parked_at",
        source_capture_id=incoming_source,
    )
    repository.append(user_id="user-1", memory=current)
    repository.write_operations.clear()

    repository.supersede_current_state(
        user_id="user-1",
        current_memory_id=current.id,
        incoming=incoming,
    )

    historical = repository.get(user_id="user-1", memory_id=current.id)
    latest = repository.get(user_id="user-1", memory_id=incoming.id)
    assert repository.write_operations == ["supersede_current_state"]
    assert historical is not None
    assert historical.status == MemoryStatus.SUPERSEDED
    assert historical.superseded_by_id == incoming.id
    assert historical.source_capture_id == original_source
    assert latest == incoming
    assert latest.source_capture_id == incoming_source


def test_invalid_supersession_fails_without_mutation() -> None:
    repository = FakeMemoryRepository()
    current = _memory(
        kind=MemoryKind.CURRENT_STATE,
        value="A1",
        predicate="parked_at",
    )
    wrong_slot = _memory(
        kind=MemoryKind.CURRENT_STATE,
        value="safe",
        predicate="located_at",
    )
    repository.append(user_id="user-1", memory=current)
    repository.write_operations.clear()

    with pytest.raises(RepositoryInvariantError):
        repository.supersede_current_state(
            user_id="user-1",
            current_memory_id=current.id,
            incoming=wrong_slot,
        )

    assert repository.get(user_id="user-1", memory_id=current.id) == current
    assert repository.get(user_id="user-1", memory_id=wrong_slot.id) is None
    assert repository.write_operations == []


def test_explicit_status_transition_validates_expected_and_current_state() -> None:
    repository = FakeMemoryRepository()
    source_capture_id = uuid4()
    intent = _memory(
        kind=MemoryKind.INTENT,
        value="AirPods",
        source_capture_id=source_capture_id,
    )
    repository.append(user_id="user-1", memory=intent)
    repository.write_operations.clear()

    repository.transition_status(
        user_id="user-1",
        memory_id=intent.id,
        expected_status=MemoryStatus.ACTIVE,
        target_status=MemoryStatus.COMPLETED,
    )

    completed = repository.get(user_id="user-1", memory_id=intent.id)
    assert completed is not None
    assert completed.status == MemoryStatus.COMPLETED
    assert completed.source_capture_id == source_capture_id
    assert repository.write_operations == ["transition_status"]

    with pytest.raises(RepositoryInvariantError, match="expected_status"):
        repository.transition_status(
            user_id="user-1",
            memory_id=intent.id,
            expected_status=MemoryStatus.ACTIVE,
            target_status=MemoryStatus.CANCELLED,
        )
    assert completed == repository.get(user_id="user-1", memory_id=intent.id)


def test_atomic_mutations_reject_cross_user_scope_without_changes() -> None:
    repository = FakeMemoryRepository()
    current = _memory(
        kind=MemoryKind.CURRENT_STATE,
        value="A1",
        predicate="parked_at",
    )
    incoming = _memory(
        kind=MemoryKind.CURRENT_STATE,
        value="B7",
        user_id="user-2",
        entity_id=current.subject_entity_id,
        predicate="parked_at",
    )
    repository.append(user_id="user-1", memory=current)
    repository.write_operations.clear()

    with pytest.raises(RepositoryInvariantError):
        repository.supersede_current_state(
            user_id="user-1",
            current_memory_id=current.id,
            incoming=incoming,
        )
    with pytest.raises(RepositoryInvariantError):
        repository.transition_status(
            user_id="user-2",
            memory_id=current.id,
            expected_status=MemoryStatus.ACTIVE,
            target_status=MemoryStatus.SUPERSEDED,
        )

    assert repository.get(user_id="user-1", memory_id=current.id) == current
    assert repository.get(user_id="user-2", memory_id=incoming.id) is None
    assert repository.write_operations == []


def test_noop_decision_requires_no_repository_write() -> None:
    repository = FakeMemoryRepository()
    existing = _memory(kind=MemoryKind.PREFERENCE, value="tennis", predicate="likes")
    duplicate = existing.model_copy(update={"id": uuid4()})
    repository.append(user_id="user-1", memory=existing)
    repository.write_operations.clear()

    decision = LifecycleEngine().reconcile(existing_active=[existing], incoming=duplicate)

    assert decision.action == LifecycleAction.NOOP
    assert repository.write_operations == []
    assert repository.get(user_id="user-1", memory_id=duplicate.id) is None
