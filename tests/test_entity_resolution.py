"""Tests for deterministic, conservative entity resolution."""

from __future__ import annotations

from uuid import UUID

import pytest

from mnemo.entities import DeterministicEntityResolver, normalize_entity_name
from mnemo.interfaces.entities import EntityResolutionOutcome, EntityResolver
from mnemo.interfaces.repositories import EntityRepository, RepositoryInvariantError
from mnemo.models.entity import Entity, EntityType

USER_ID = "user-1"
OTHER_USER_ID = "user-2"


class FakeEntityRepository:
    """Test-only user-scoped repository for exercising the public contract."""

    def __init__(self, entities: tuple[Entity, ...] = ()) -> None:
        self.records = {entity.id: entity for entity in entities}
        self.write_operations: list[str] = []
        self.list_calls: list[str] = []

    def add(self, *, user_id: str, entity: Entity) -> None:
        if entity.user_id != user_id:
            raise RepositoryInvariantError("entity belongs to a different user")
        if entity.id in self.records:
            raise RepositoryInvariantError("entity id already exists")
        self.records[entity.id] = entity
        self.write_operations.append("add")

    def get(self, *, user_id: str, entity_id: UUID) -> Entity | None:
        entity = self.records.get(entity_id)
        if entity is None or entity.user_id != user_id:
            return None
        return entity

    def list_for_user(self, *, user_id: str) -> list[Entity]:
        self.list_calls.append(user_id)
        return [entity for entity in self.records.values() if entity.user_id == user_id]


class LeakyEntityRepository(FakeEntityRepository):
    """Deliberately broken fake used to prove resolver defense in depth."""

    def list_for_user(self, *, user_id: str) -> list[Entity]:
        return list(self.records.values())


def _entity(
    number: int,
    name: str,
    *,
    user_id: str = USER_ID,
    entity_type: EntityType = EntityType.PERSON,
    aliases: tuple[str, ...] = (),
) -> Entity:
    return Entity(
        id=UUID(int=number),
        user_id=user_id,
        type=entity_type,
        canonical_name=name,
        aliases=list(aliases),
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" Kevin ", "kevin"),
        ("Alex   Kim", "alex kim"),
        ("Alex\t\nKim", "alex kim"),
        ("Straße", "strasse"),
        ("Ｋｅｖｉｎ", "kevin"),
    ],
)
def test_entity_name_normalization(raw: str, expected: str) -> None:
    assert normalize_entity_name(raw) == expected


def test_entity_name_normalization_preserves_punctuation_distinctions() -> None:
    assert normalize_entity_name("O'Connor") != normalize_entity_name("OConnor")


def test_entity_name_normalization_preserves_accent_distinctions() -> None:
    assert normalize_entity_name("José") != normalize_entity_name("Jose")


def test_entity_name_normalization_does_not_expand_partial_names() -> None:
    assert normalize_entity_name("Kevin Wang") != normalize_entity_name("Kevin")


def test_entity_name_normalization_rejects_blank_values() -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        normalize_entity_name(" \t\n ")


def test_unique_canonical_name_match_is_matched() -> None:
    kevin = _entity(1, "Kevin")
    resolver: EntityResolver = DeterministicEntityResolver(FakeEntityRepository((kevin,)))

    result = resolver.resolve(user_id=USER_ID, mention="  KEVIN ")

    assert result.outcome == EntityResolutionOutcome.MATCHED
    assert result.matched_entity == kevin
    assert result.candidates == ()


def test_unique_explicit_alias_match_is_matched() -> None:
    kevin = _entity(1, "Kevin Wang", aliases=("K.W.", "Kev"))
    resolver = DeterministicEntityResolver(FakeEntityRepository((kevin,)))

    result = resolver.resolve(user_id=USER_ID, mention="kev")

    assert result.outcome == EntityResolutionOutcome.MATCHED
    assert result.matched_entity == kevin


def test_no_exact_name_or_alias_match_is_unmatched() -> None:
    resolver = DeterministicEntityResolver(
        FakeEntityRepository((_entity(1, "Kevin Wang", aliases=("Kev",)),))
    )

    result = resolver.resolve(user_id=USER_ID, mention="Kevin")

    assert result.outcome == EntityResolutionOutcome.UNMATCHED
    assert result.matched_entity is None
    assert result.candidates == ()


def test_same_entity_matching_canonical_name_and_alias_is_one_match() -> None:
    kevin = _entity(1, "Kevin", aliases=(" KEVIN ",))
    resolver = DeterministicEntityResolver(FakeEntityRepository((kevin,)))

    result = resolver.resolve(user_id=USER_ID, mention="kevin")

    assert result.outcome == EntityResolutionOutcome.MATCHED
    assert result.matched_entity == kevin


def test_duplicate_normalized_canonical_names_are_ambiguous() -> None:
    first = _entity(2, "Alex   Kim")
    second = _entity(1, " alex kim ")
    resolver = DeterministicEntityResolver(FakeEntityRepository((first, second)))

    result = resolver.resolve(user_id=USER_ID, mention="ALEX KIM")

    assert result.outcome == EntityResolutionOutcome.AMBIGUOUS
    assert result.matched_entity is None
    assert result.candidates == (second, first)


def test_duplicate_normalized_aliases_are_ambiguous() -> None:
    first = _entity(1, "Alex Kim", aliases=("Alex",))
    second = _entity(2, "Alex Rivera", aliases=(" ALEX ",))
    resolver = DeterministicEntityResolver(FakeEntityRepository((first, second)))

    result = resolver.resolve(user_id=USER_ID, mention="alex")

    assert result.outcome == EntityResolutionOutcome.AMBIGUOUS
    assert result.candidates == (first, second)


def test_canonical_name_and_other_entity_alias_are_ambiguous() -> None:
    canonical = _entity(1, "Alex")
    aliased = _entity(2, "Alexander", aliases=("Alex",))
    resolver = DeterministicEntityResolver(FakeEntityRepository((canonical, aliased)))

    result = resolver.resolve(user_id=USER_ID, mention="Alex")

    assert result.outcome == EntityResolutionOutcome.AMBIGUOUS
    assert result.candidates == (canonical, aliased)
    assert len({candidate.id for candidate in result.candidates}) == 2


def test_entity_type_does_not_disambiguate_equal_names() -> None:
    person = _entity(1, "Jordan", entity_type=EntityType.PERSON)
    place = _entity(2, "Jordan", entity_type=EntityType.PLACE)
    resolver = DeterministicEntityResolver(FakeEntityRepository((person, place)))

    result = resolver.resolve(user_id=USER_ID, mention="Jordan")

    assert result.outcome == EntityResolutionOutcome.AMBIGUOUS
    assert result.candidates == (person, place)


def test_foreign_entity_is_invisible_and_does_not_make_local_match_ambiguous() -> None:
    own = _entity(1, "Alex")
    foreign = _entity(2, "Alex", user_id=OTHER_USER_ID)
    repository = FakeEntityRepository((foreign, own))
    resolver = DeterministicEntityResolver(repository)

    result = resolver.resolve(user_id=USER_ID, mention="Alex")

    assert result.outcome == EntityResolutionOutcome.MATCHED
    assert result.matched_entity == own
    assert foreign not in result.candidates
    assert repository.list_calls == [USER_ID]


def test_resolver_fails_closed_if_repository_leaks_foreign_entity() -> None:
    foreign = _entity(1, "Alex", user_id=OTHER_USER_ID)
    resolver = DeterministicEntityResolver(LeakyEntityRepository((foreign,)))

    with pytest.raises(RepositoryInvariantError, match="different user scope"):
        resolver.resolve(user_id=USER_ID, mention="Alex")


def test_resolver_performs_no_writes_or_alias_mutation() -> None:
    kevin = _entity(1, "Kevin Wang", aliases=("Kev",))
    repository = FakeEntityRepository((kevin,))
    resolver = DeterministicEntityResolver(repository)
    original_aliases = list(kevin.aliases)

    result = resolver.resolve(user_id=USER_ID, mention="someone new")

    assert result.outcome == EntityResolutionOutcome.UNMATCHED
    assert repository.write_operations == []
    assert kevin.aliases == original_aliases


def test_resolution_is_deterministic_across_repeated_calls() -> None:
    entities = (
        _entity(3, "Alexander", aliases=("Alex",)),
        _entity(1, "Alex"),
        _entity(2, "Alexandra", aliases=("Alex",)),
    )
    resolver = DeterministicEntityResolver(FakeEntityRepository(entities))

    first = resolver.resolve(user_id=USER_ID, mention="Alex")
    second = resolver.resolve(user_id=USER_ID, mention="Alex")

    assert first == second
    assert [candidate.id for candidate in first.candidates] == [UUID(int=n) for n in (1, 2, 3)]


def test_entity_repository_get_and_list_are_user_scoped() -> None:
    own = _entity(1, "Kevin")
    foreign = _entity(2, "Alex", user_id=OTHER_USER_ID)
    repository: EntityRepository = FakeEntityRepository((own, foreign))

    assert repository.get(user_id=USER_ID, entity_id=own.id) == own
    assert repository.get(user_id=OTHER_USER_ID, entity_id=own.id) is None
    assert list(repository.list_for_user(user_id=USER_ID)) == [own]
    assert list(repository.list_for_user(user_id=OTHER_USER_ID)) == [foreign]


def test_entity_repository_add_preserves_entity_exactly() -> None:
    entity = _entity(1, "Kevin", aliases=("Kev",))
    repository: EntityRepository = FakeEntityRepository()

    repository.add(user_id=USER_ID, entity=entity)

    assert repository.get(user_id=USER_ID, entity_id=entity.id) == entity


def test_entity_repository_rejects_cross_user_add_without_mutation() -> None:
    entity = _entity(1, "Kevin", user_id=OTHER_USER_ID)
    repository = FakeEntityRepository()

    with pytest.raises(RepositoryInvariantError, match="different user"):
        repository.add(user_id=USER_ID, entity=entity)

    assert repository.records == {}
    assert repository.write_operations == []


def test_entity_repository_rejects_duplicate_id_without_mutation() -> None:
    existing = _entity(1, "Kevin")
    duplicate = _entity(1, "Another Kevin")
    repository = FakeEntityRepository((existing,))

    with pytest.raises(RepositoryInvariantError, match="already exists"):
        repository.add(user_id=USER_ID, entity=duplicate)

    assert repository.get(user_id=USER_ID, entity_id=existing.id) == existing
    assert repository.write_operations == []
