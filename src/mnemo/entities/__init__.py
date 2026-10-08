"""Deterministic, conservative entity-resolution behavior."""

from mnemo.entities.normalization import normalize_entity_name
from mnemo.entities.resolver import DeterministicEntityResolver

__all__ = ["DeterministicEntityResolver", "normalize_entity_name"]
