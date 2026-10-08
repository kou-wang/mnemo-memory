"""Small validation helpers shared across domain models.

These helpers exist only to avoid duplicating the same string-normalization
logic across ``Entity``, ``CandidateMemory``, and ``Memory``. They must stay
pure and framework-independent: no I/O, no provider calls, no persistence.
"""

from __future__ import annotations

import re
from datetime import datetime

_WHITESPACE_RUN = re.compile(r"\s+")
_MEMORY_KEY_FORMAT = re.compile(r"^[^\s:]+:[^\s:]+$")


def require_timezone_aware(value: datetime, *, field_name: str) -> datetime:
    """Reject naive datetimes.

    Comparing a naive and a timezone-aware datetime raises an incidental
    ``TypeError`` from the standard library rather than a clear domain
    error. Since the engine is temporal-first and treats time as
    first-class data, every datetime must carry explicit timezone info
    (prefer UTC) so that temporal comparisons never fail ambiguously.
    """
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")
    return value


def require_non_blank(value: str, *, field_name: str) -> str:
    """Strip ``value`` and reject strings that are empty or whitespace-only.

    Pydantic's ``min_length`` constraint only checks raw length, so a
    whitespace-only string (e.g. ``"   "``) would otherwise pass validation.
    """
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must not be blank")
    return stripped


def normalize_memory_key(value: str) -> str:
    """Normalize a ``memory_key`` to its canonical, comparable form.

    Normalization rules:
    - leading/trailing whitespace is stripped
    - the key is lowercased
    - internal whitespace runs are collapsed to a single underscore
    - the result must match ``<subject>:<predicate>`` with non-blank,
      colon-free, whitespace-free segments on both sides

    These rules keep ``memory_key`` comparisons (used for
    ``CURRENT_STATE`` slot identification) stable regardless of how the
    caller capitalized or spaced the original input.
    """
    normalized = _WHITESPACE_RUN.sub("_", value.strip().lower())
    if not _MEMORY_KEY_FORMAT.match(normalized):
        raise ValueError(
            "memory_key must use the '<subject>:<predicate>' format "
            "with non-blank segments and no embedded whitespace"
        )
    return normalized
