"""Contract tests for extraction, entity resolution, and time boundaries."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from mnemo.interfaces.clock import Clock
from mnemo.interfaces.entities import (
    EntityResolution,
    EntityResolutionOutcome,
    EntityResolver,
)
from mnemo.interfaces.extraction import Extractor
from mnemo.models.candidate import CandidateMemory
from mnemo.models.capture import Capture, SourceType
from mnemo.models.entity import Entity, EntityType
from mnemo.models.types import MemoryKind

NOW = datetime(2026, 10, 8, 15, tzinfo=UTC)


class FakeExtractor:
    def extract(self, capture: Capture) -> Sequence[CandidateMemory]:
        if capture.raw_text == "nothing memorable":
            return ()
        return (
            CandidateMemory(
                kind=MemoryKind.INTENT,
                subject="user",
                predicate="buy",
                value="eggs",
            ),
            CandidateMemory(
                kind=MemoryKind.INTENT,
                subject="user",
                predicate="buy",
                value="milk",
            ),
        )


class FakeEntityResolver:
    def __init__(self, entity: Entity) -> None:
        self.entity = entity

    def resolve(self, *, user_id: str, mention: str) -> EntityResolution:
        return EntityResolution(
            user_id=user_id,
            mention=mention,
            outcome=EntityResolutionOutcome.MATCHED,
            matched_entity=self.entity,
        )


@dataclass(frozen=True)
class FixedClock:
    instant: datetime

    def now(self) -> datetime:
        return self.instant


def _capture(raw_text: str) -> Capture:
    return Capture(
        user_id="user-1",
        source_type=SourceType.TEXT,
        raw_text=raw_text,
        captured_at=NOW,
        created_at=NOW,
    )


def _entity(name: str, *, user_id: str = "user-1") -> Entity:
    return Entity(user_id=user_id, type=EntityType.PERSON, canonical_name=name)


def test_extractor_can_return_multiple_candidates_without_persistence() -> None:
    extractor: Extractor = FakeExtractor()

    candidates = extractor.extract(_capture("Buy eggs and milk"))

    assert [candidate.value for candidate in candidates] == ["eggs", "milk"]
    assert all(isinstance(candidate, CandidateMemory) for candidate in candidates)
    assert not hasattr(extractor, "repository")


def test_extractor_can_return_zero_candidates() -> None:
    extractor: Extractor = FakeExtractor()

    assert extractor.extract(_capture("nothing memorable")) == ()


def test_matched_resolution_identifies_entity() -> None:
    kevin = _entity("Kevin")
    resolver: EntityResolver = FakeEntityResolver(kevin)

    result = resolver.resolve(user_id="user-1", mention="Kevin")

    assert result.outcome == EntityResolutionOutcome.MATCHED
    assert result.matched_entity == kevin
    assert result.candidates == ()


def test_unmatched_resolution_is_distinguishable() -> None:
    result = EntityResolution(
        user_id="user-1",
        mention="someone new",
        outcome=EntityResolutionOutcome.UNMATCHED,
    )

    assert result.outcome == EntityResolutionOutcome.UNMATCHED
    assert result.matched_entity is None
    assert result.candidates == ()


def test_ambiguous_resolution_preserves_multiple_candidates() -> None:
    candidates = (_entity("Alex Kim"), _entity("Alex Rivera"))

    result = EntityResolution(
        user_id="user-1",
        mention="Alex",
        outcome=EntityResolutionOutcome.AMBIGUOUS,
        candidates=candidates,
    )

    assert result.outcome == EntityResolutionOutcome.AMBIGUOUS
    assert result.candidates == candidates
    assert result.matched_entity is None


@pytest.mark.parametrize(
    ("outcome", "matched_entity", "candidates"),
    [
        (EntityResolutionOutcome.MATCHED, None, ()),
        (EntityResolutionOutcome.UNMATCHED, _entity("Kevin"), ()),
        (EntityResolutionOutcome.AMBIGUOUS, None, (_entity("Only one"),)),
        (
            EntityResolutionOutcome.AMBIGUOUS,
            _entity("Matched"),
            (_entity("Alex Kim"), _entity("Alex Rivera")),
        ),
    ],
)
def test_entity_resolution_rejects_contradictory_states(
    outcome: EntityResolutionOutcome,
    matched_entity: Entity | None,
    candidates: tuple[Entity, ...],
) -> None:
    with pytest.raises(ValidationError):
        EntityResolution(
            user_id="user-1",
            mention="Kevin",
            outcome=outcome,
            matched_entity=matched_entity,
            candidates=candidates,
        )


def test_entity_resolution_rejects_cross_user_candidates() -> None:
    with pytest.raises(ValidationError, match="requested user_id"):
        EntityResolution(
            user_id="user-1",
            mention="Alex",
            outcome=EntityResolutionOutcome.AMBIGUOUS,
            candidates=(_entity("Alex One"), _entity("Alex Two", user_id="user-2")),
        )


def test_ambiguous_resolution_rejects_duplicate_candidates() -> None:
    candidate = _entity("Alex")

    with pytest.raises(ValidationError, match="distinct entities"):
        EntityResolution(
            user_id="user-1",
            mention="Alex",
            outcome=EntityResolutionOutcome.AMBIGUOUS,
            candidates=(candidate, candidate),
        )


def test_fixed_clock_is_deterministic_and_timezone_aware() -> None:
    clock: Clock = FixedClock(NOW)

    first = clock.now()
    second = clock.now()

    assert first == second == NOW
    assert first.tzinfo is not None
    assert first.utcoffset() is not None
