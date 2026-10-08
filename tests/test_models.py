"""Validation tests for the core domain models.

These tests cover invalid model states per Sprint 1's acceptance criteria:
Entity / CandidateMemory / Memory validation, temporal field validation,
and memory_key normalization rules.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from mnemo.models.candidate import CandidateMemory
from mnemo.models.entity import Entity, EntityType
from mnemo.models.memory import Memory
from mnemo.models.types import MemoryKind

NOW = datetime.now(UTC)


# ---------------------------------------------------------------------------
# Entity
# ---------------------------------------------------------------------------


def test_entity_rejects_blank_canonical_name() -> None:
    with pytest.raises(ValidationError):
        Entity(user_id="user-1", type=EntityType.PERSON, canonical_name="   ")


def test_entity_canonical_name_is_stripped() -> None:
    entity = Entity(user_id="user-1", type=EntityType.PERSON, canonical_name="  Kevin  ")
    assert entity.canonical_name == "Kevin"


def test_entity_deduplicates_and_strips_aliases() -> None:
    entity = Entity(
        user_id="user-1",
        type=EntityType.PERSON,
        canonical_name="Kevin",
        aliases=[" Kev ", "Kev", "K."],
    )
    assert entity.aliases == ["Kev", "K."]


def test_entity_rejects_blank_alias() -> None:
    with pytest.raises(ValidationError):
        Entity(
            user_id="user-1",
            type=EntityType.PERSON,
            canonical_name="Kevin",
            aliases=["  "],
        )


# ---------------------------------------------------------------------------
# CandidateMemory
# ---------------------------------------------------------------------------


def test_candidate_memory_rejects_blank_subject() -> None:
    with pytest.raises(ValidationError):
        CandidateMemory(kind=MemoryKind.FACT, subject="   ", predicate="birthday", value="3-12")


def test_candidate_memory_rejects_blank_predicate() -> None:
    with pytest.raises(ValidationError):
        CandidateMemory(kind=MemoryKind.FACT, subject="Kevin", predicate=" ", value="3-12")


def test_candidate_memory_strips_subject_and_predicate() -> None:
    candidate = CandidateMemory(
        kind=MemoryKind.FACT, subject=" Kevin ", predicate=" birthday ", value="3-12"
    )
    assert candidate.subject == "Kevin"
    assert candidate.predicate == "birthday"


def test_candidate_memory_rejects_valid_until_before_valid_from() -> None:
    with pytest.raises(ValidationError):
        CandidateMemory(
            kind=MemoryKind.PREFERENCE,
            subject="Kevin",
            predicate="likes",
            value="whisky",
            valid_from=NOW,
            valid_until=NOW - timedelta(days=1),
        )


def test_candidate_memory_rejects_expires_at_before_valid_from() -> None:
    with pytest.raises(ValidationError):
        CandidateMemory(
            kind=MemoryKind.INTENT,
            subject="user",
            predicate="buy",
            value="racket",
            valid_from=NOW,
            expires_at=NOW - timedelta(days=1),
        )


def test_candidate_memory_accepts_consistent_temporal_bounds() -> None:
    candidate = CandidateMemory(
        kind=MemoryKind.INTENT,
        subject="user",
        predicate="buy",
        value="racket",
        valid_from=NOW,
        valid_until=NOW + timedelta(days=30),
        expires_at=NOW + timedelta(days=30),
    )
    assert candidate.valid_until is not None
    assert candidate.valid_until > candidate.valid_from  # type: ignore[operator]


def test_candidate_memory_rejects_out_of_range_confidence() -> None:
    with pytest.raises(ValidationError):
        CandidateMemory(
            kind=MemoryKind.FACT,
            subject="Kevin",
            predicate="birthday",
            value="3-12",
            confidence=1.5,
        )


# ---------------------------------------------------------------------------
# Memory: temporal validation
# ---------------------------------------------------------------------------


def _base_memory_kwargs() -> dict[str, object]:
    return {
        "user_id": "user-1",
        "kind": MemoryKind.FACT,
        "subject_entity_id": uuid4(),
        "predicate": "birthday",
        "value": "3-12",
    }


def test_memory_rejects_valid_until_before_valid_from() -> None:
    with pytest.raises(ValidationError):
        Memory(**_base_memory_kwargs(), valid_from=NOW, valid_until=NOW - timedelta(days=1))


def test_memory_rejects_expires_at_before_valid_from() -> None:
    with pytest.raises(ValidationError):
        Memory(**_base_memory_kwargs(), valid_from=NOW, expires_at=NOW - timedelta(days=1))


def test_memory_rejects_blank_predicate() -> None:
    kwargs = _base_memory_kwargs()
    kwargs["predicate"] = "   "
    with pytest.raises(ValidationError):
        Memory(**kwargs)


# ---------------------------------------------------------------------------
# Memory: CURRENT_STATE requires memory_key
# ---------------------------------------------------------------------------


def test_current_state_without_memory_key_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Memory(
            user_id="user-1",
            kind=MemoryKind.CURRENT_STATE,
            subject_entity_id=uuid4(),
            predicate="parked_at",
            value="A1",
        )


def test_current_state_with_memory_key_is_accepted() -> None:
    entity_id = uuid4()
    memory = Memory(
        user_id="user-1",
        kind=MemoryKind.CURRENT_STATE,
        subject_entity_id=entity_id,
        predicate="parked_at",
        value="A1",
        memory_key=Memory.build_memory_key(entity_id, "parked_at"),
    )
    assert memory.memory_key == f"{entity_id}:parked_at"


def test_non_current_state_memory_does_not_require_memory_key() -> None:
    memory = Memory(**_base_memory_kwargs())
    assert memory.memory_key is None


# ---------------------------------------------------------------------------
# Memory: memory_key normalization
# ---------------------------------------------------------------------------


def test_build_memory_key_normalizes_predicate_case_and_whitespace() -> None:
    entity_id = uuid4()
    key = Memory.build_memory_key(entity_id, "  Parked AT  ")
    assert key == f"{entity_id}:parked_at"


def test_memory_key_field_is_normalized_on_assignment() -> None:
    entity_id = uuid4()
    memory = Memory(
        user_id="user-1",
        kind=MemoryKind.CURRENT_STATE,
        subject_entity_id=entity_id,
        predicate="parked_at",
        value="A1",
        memory_key=f"  {entity_id}:Parked At  ",
    )
    assert memory.memory_key == f"{entity_id}:parked_at"


def test_memory_key_rejects_missing_colon_segment() -> None:
    with pytest.raises(ValidationError):
        Memory(
            user_id="user-1",
            kind=MemoryKind.CURRENT_STATE,
            subject_entity_id=uuid4(),
            predicate="parked_at",
            value="A1",
            memory_key="no_colon_here",
        )


def test_memory_key_rejects_blank_segment() -> None:
    with pytest.raises(ValidationError):
        Memory(
            user_id="user-1",
            kind=MemoryKind.CURRENT_STATE,
            subject_entity_id=uuid4(),
            predicate="parked_at",
            value="A1",
            memory_key=":parked_at",
        )


def test_two_equivalent_memory_keys_normalize_to_the_same_value() -> None:
    entity_id = uuid4()
    key_a = Memory.build_memory_key(entity_id, "parked_at")
    key_b = Memory.build_memory_key(entity_id, "  PARKED   AT  ")
    assert key_a == key_b


# ---------------------------------------------------------------------------
# Memory: memory_key must be the canonical key for subject_entity_id/predicate
# ---------------------------------------------------------------------------


def test_current_state_memory_key_mismatched_predicate_is_rejected() -> None:
    """memory_key must describe the same subject/predicate as the memory.

    Otherwise a CURRENT_STATE memory could be reconciled against the
    wrong state slot.
    """
    entity_id = uuid4()
    with pytest.raises(ValidationError):
        Memory(
            user_id="user-1",
            kind=MemoryKind.CURRENT_STATE,
            subject_entity_id=entity_id,
            predicate="parked_at",
            value="A1",
            # Built for a different predicate than this memory's own.
            memory_key=Memory.build_memory_key(entity_id, "located_at"),
        )


def test_current_state_memory_key_mismatched_subject_is_rejected() -> None:
    entity_id = uuid4()
    other_entity_id = uuid4()
    with pytest.raises(ValidationError):
        Memory(
            user_id="user-1",
            kind=MemoryKind.CURRENT_STATE,
            subject_entity_id=entity_id,
            predicate="parked_at",
            value="A1",
            # Built for a different subject entity than this memory's own.
            memory_key=Memory.build_memory_key(other_entity_id, "parked_at"),
        )


def test_current_state_memory_key_arbitrary_string_is_rejected() -> None:
    entity_id = uuid4()
    with pytest.raises(ValidationError):
        Memory(
            user_id="user-1",
            kind=MemoryKind.CURRENT_STATE,
            subject_entity_id=entity_id,
            predicate="parked_at",
            value="A1",
            memory_key="some_other_slot:value",
        )


# ---------------------------------------------------------------------------
# Timezone-aware datetime enforcement
# ---------------------------------------------------------------------------


def test_memory_rejects_naive_valid_from() -> None:
    kwargs = _base_memory_kwargs()
    with pytest.raises(ValidationError):
        Memory(**kwargs, valid_from=datetime(2024, 1, 1))  # naive, no tzinfo


def test_memory_rejects_naive_occurred_at() -> None:
    kwargs = _base_memory_kwargs()
    with pytest.raises(ValidationError):
        Memory(**kwargs, occurred_at=datetime(2024, 1, 1))  # naive, no tzinfo


def test_memory_rejects_mixed_naive_and_aware_temporal_fields() -> None:
    """A naive datetime must be rejected explicitly, rather than letting a
    naive/aware comparison raise an incidental TypeError later.
    """
    kwargs = _base_memory_kwargs()
    with pytest.raises(ValidationError) as exc_info:
        Memory(
            **kwargs,
            valid_from=NOW,
            valid_until=datetime(2024, 1, 1),  # naive, no tzinfo
        )
    assert "timezone-aware" in str(exc_info.value)


def test_candidate_memory_rejects_naive_valid_from() -> None:
    with pytest.raises(ValidationError):
        CandidateMemory(
            kind=MemoryKind.PREFERENCE,
            subject="Kevin",
            predicate="likes",
            value="whisky",
            valid_from=datetime(2024, 1, 1),  # naive, no tzinfo
        )


def test_candidate_memory_rejects_mixed_naive_and_aware_temporal_fields() -> None:
    with pytest.raises(ValidationError) as exc_info:
        CandidateMemory(
            kind=MemoryKind.INTENT,
            subject="user",
            predicate="buy",
            value="racket",
            valid_from=NOW,
            valid_until=datetime(2024, 1, 1),  # naive, no tzinfo
        )
    assert "timezone-aware" in str(exc_info.value)
