"""Conservative deterministic entity resolution."""

from __future__ import annotations

from uuid import UUID

from mnemo.entities.normalization import normalize_entity_name
from mnemo.interfaces.entities import EntityResolution, EntityResolutionOutcome, EntityResolver
from mnemo.interfaces.repositories import EntityRepository, RepositoryInvariantError
from mnemo.models._shared import require_non_blank
from mnemo.models.entity import Entity


class DeterministicEntityResolver(EntityResolver):
    """Match only normalized canonical names and explicit aliases.

    Resolution is read-only. Unmatched entity creation and all merge decisions
    belong to later orchestration, not this resolver.
    """

    def __init__(self, repository: EntityRepository) -> None:
        self._repository = repository

    def resolve(self, *, user_id: str, mention: str) -> EntityResolution:
        scoped_user_id = require_non_blank(user_id, field_name="user_id")
        normalized_mention = normalize_entity_name(mention)
        matches: dict[UUID, Entity] = {}

        for entity in self._repository.list_for_user(user_id=scoped_user_id):
            if entity.user_id != scoped_user_id:
                raise RepositoryInvariantError(
                    "entity repository returned a record from a different user scope"
                )
            names = (entity.canonical_name, *entity.aliases)
            if any(normalize_entity_name(name) == normalized_mention for name in names):
                matches[entity.id] = entity

        candidates = tuple(matches[entity_id] for entity_id in sorted(matches))
        if not candidates:
            return EntityResolution(
                user_id=scoped_user_id,
                mention=mention,
                outcome=EntityResolutionOutcome.UNMATCHED,
            )
        if len(candidates) == 1:
            return EntityResolution(
                user_id=scoped_user_id,
                mention=mention,
                outcome=EntityResolutionOutcome.MATCHED,
                matched_entity=candidates[0],
            )
        return EntityResolution(
            user_id=scoped_user_id,
            mention=mention,
            outcome=EntityResolutionOutcome.AMBIGUOUS,
            candidates=candidates,
        )
