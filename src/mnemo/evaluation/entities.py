"""Deterministic conservative entity-resolution evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from mnemo.entities import DeterministicEntityResolver
from mnemo.evaluation.models import EntityResolutionEvaluationCase, EvaluationResult
from mnemo.interfaces.entities import EntityResolutionOutcome
from mnemo.models.entity import Entity, EntityType

_USER_ID = "evaluation-user"


def _id(number: int) -> UUID:
    return UUID(int=90_000 + number)


def _entity(
    number: int,
    name: str,
    *,
    aliases: tuple[str, ...] = (),
    user_id: str = _USER_ID,
) -> Entity:
    return Entity(
        id=_id(number),
        user_id=user_id,
        type=EntityType.PERSON,
        canonical_name=name,
        aliases=list(aliases),
    )


class _EntityRepository:
    def __init__(self, entities: tuple[Entity, ...]) -> None:
        self._entities = entities

    def add(self, *, user_id: str, entity: Entity) -> None:
        raise NotImplementedError

    def get(self, *, user_id: str, entity_id: UUID) -> Entity | None:
        return next(
            (
                entity
                for entity in self._entities
                if entity.user_id == user_id and entity.id == entity_id
            ),
            None,
        )

    def list_for_user(self, *, user_id: str) -> Sequence[Entity]:
        return tuple(entity for entity in self._entities if entity.user_id == user_id)


def entity_resolution_cases() -> tuple[EntityResolutionEvaluationCase, ...]:
    kevin = _entity(1, "Kevin O'Neil", aliases=("Kev",))
    fullwidth = _entity(2, "Ｋｅｖｉｎ")
    whitespace = _entity(3, "Mary   Jane")
    strasse = _entity(4, "Straße")
    punctuated = _entity(5, "A.B")
    accented = _entity(6, "José")
    shared_one = _entity(7, "Alex")
    shared_two = _entity(8, "Alexander", aliases=("Alex",))
    foreign = _entity(9, "Foreign Name", user_id="foreign-user")
    return (
        EntityResolutionEvaluationCase(
            case_id="canonical_name_match",
            user_id=_USER_ID,
            mention="Kevin O'Neil",
            entities=(kevin,),
            expected_outcome=EntityResolutionOutcome.MATCHED,
            expected_entity_ids=(kevin.id,),
        ),
        EntityResolutionEvaluationCase(
            case_id="explicit_alias_match",
            user_id=_USER_ID,
            mention="Kev",
            entities=(kevin,),
            expected_outcome=EntityResolutionOutcome.MATCHED,
            expected_entity_ids=(kevin.id,),
        ),
        EntityResolutionEvaluationCase(
            case_id="unmatched_name",
            user_id=_USER_ID,
            mention="Nobody",
            entities=(kevin,),
            expected_outcome=EntityResolutionOutcome.UNMATCHED,
        ),
        EntityResolutionEvaluationCase(
            case_id="ambiguous_alias",
            user_id=_USER_ID,
            mention="Alex",
            entities=(shared_one, shared_two),
            expected_outcome=EntityResolutionOutcome.AMBIGUOUS,
            expected_entity_ids=(shared_one.id, shared_two.id),
        ),
        EntityResolutionEvaluationCase(
            case_id="unicode_nfkc",
            user_id=_USER_ID,
            mention="Kevin",
            entities=(fullwidth,),
            expected_outcome=EntityResolutionOutcome.MATCHED,
            expected_entity_ids=(fullwidth.id,),
        ),
        EntityResolutionEvaluationCase(
            case_id="whitespace_collapse",
            user_id=_USER_ID,
            mention=" Mary Jane ",
            entities=(whitespace,),
            expected_outcome=EntityResolutionOutcome.MATCHED,
            expected_entity_ids=(whitespace.id,),
        ),
        EntityResolutionEvaluationCase(
            case_id="unicode_casefold",
            user_id=_USER_ID,
            mention="STRASSE",
            entities=(strasse,),
            expected_outcome=EntityResolutionOutcome.MATCHED,
            expected_entity_ids=(strasse.id,),
        ),
        EntityResolutionEvaluationCase(
            case_id="punctuation_not_stripped",
            user_id=_USER_ID,
            mention="AB",
            entities=(punctuated,),
            expected_outcome=EntityResolutionOutcome.UNMATCHED,
        ),
        EntityResolutionEvaluationCase(
            case_id="accent_not_stripped",
            user_id=_USER_ID,
            mention="Jose",
            entities=(accented,),
            expected_outcome=EntityResolutionOutcome.UNMATCHED,
        ),
        EntityResolutionEvaluationCase(
            case_id="user_isolation",
            user_id=_USER_ID,
            mention="Foreign Name",
            entities=(foreign,),
            expected_outcome=EntityResolutionOutcome.UNMATCHED,
        ),
    )


def evaluate_entity_resolution() -> tuple[EvaluationResult, ...]:
    results: list[EvaluationResult] = []
    for case in entity_resolution_cases():
        resolution = DeterministicEntityResolver(_EntityRepository(case.entities)).resolve(
            user_id=case.user_id,
            mention=case.mention,
        )
        actual_ids = (
            (resolution.matched_entity.id,)
            if resolution.matched_entity is not None
            else tuple(entity.id for entity in resolution.candidates)
        )
        failures: list[str] = []
        if resolution.outcome != case.expected_outcome:
            failures.append(
                f"expected outcome {case.expected_outcome}, got {resolution.outcome}"
            )
        if actual_ids != case.expected_entity_ids:
            failures.append(f"expected entity ids {case.expected_entity_ids}, got {actual_ids}")
        results.append(
            EvaluationResult(
                case_id=case.case_id,
                domain=case.domain,
                passed=not failures,
                diagnostic="; ".join(failures) if failures else None,
            )
        )
    return tuple(results)
