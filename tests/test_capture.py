"""Contract tests for raw Capture provenance."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from mnemo.models.capture import Capture, SourceType

CAPTURED_AT = datetime(2026, 10, 8, 15, tzinfo=UTC)
CREATED_AT = datetime(2026, 10, 8, 15, 0, 1, tzinfo=UTC)


def test_text_capture_is_valid() -> None:
    capture = Capture(
        user_id="user-1",
        source_type=SourceType.TEXT,
        raw_text="Kevin's birthday is March 12.",
        captured_at=CAPTURED_AT,
        created_at=CREATED_AT,
    )

    assert capture.raw_text == "Kevin's birthday is March 12."
    assert capture.source_type == SourceType.TEXT


def test_voice_transcript_capture_is_valid_without_raw_audio() -> None:
    capture = Capture(
        user_id="user-1",
        source_type=SourceType.VOICE,
        raw_text="I parked at P3 B12.",
        captured_at=CAPTURED_AT,
        created_at=CREATED_AT,
    )

    assert capture.source_type == SourceType.VOICE
    assert set(Capture.model_fields) == {
        "id",
        "user_id",
        "source_type",
        "raw_text",
        "captured_at",
        "created_at",
    }


def test_capture_rejects_blank_raw_text() -> None:
    with pytest.raises(ValidationError):
        Capture(
            user_id="user-1",
            source_type=SourceType.TEXT,
            raw_text="   ",
            captured_at=CAPTURED_AT,
            created_at=CREATED_AT,
        )


@pytest.mark.parametrize("field", ["captured_at", "created_at"])
def test_capture_rejects_naive_timestamps(field: str) -> None:
    values = {
        "user_id": "user-1",
        "source_type": SourceType.TEXT,
        "raw_text": "Remember this.",
        "captured_at": CAPTURED_AT,
        "created_at": CREATED_AT,
    }
    values[field] = datetime(2026, 10, 8, 15)

    with pytest.raises(ValidationError, match="timezone-aware"):
        Capture.model_validate(values)
