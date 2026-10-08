"""OpenAI implementation of the provider-independent extraction boundary."""

from __future__ import annotations

from collections.abc import Sequence

from openai import OpenAI, OpenAIError
from pydantic import ValidationError

from mnemo.interfaces.extraction import Extractor
from mnemo.models.candidate import CandidateMemory
from mnemo.models.capture import Capture
from mnemo.providers.openai.prompt import EXTRACTION_INSTRUCTIONS, build_capture_input
from mnemo.providers.openai.schemas import OpenAIExtractionBatch


class OpenAIExtractionError(RuntimeError):
    """Base error for failed OpenAI extraction attempts."""


class OpenAIProviderError(OpenAIExtractionError):
    """The OpenAI API or SDK failed before producing a usable response."""


class OpenAIResponseError(OpenAIExtractionError):
    """The provider returned no valid structured extraction result."""


class OpenAIExtractor(Extractor):
    """Interpret captures through OpenAI Responses Structured Outputs.

    This adapter has no repository, entity resolver, lifecycle engine, or clock.
    It can only convert a Capture into provider-independent CandidateMemory values.
    """

    def __init__(self, *, model: str, client: OpenAI | None = None) -> None:
        if not model.strip():
            raise ValueError("model must not be blank")
        self._model = model.strip()
        self._client = client if client is not None else OpenAI()

    def extract(self, capture: Capture) -> Sequence[CandidateMemory]:
        try:
            response = self._client.responses.parse(
                model=self._model,
                instructions=EXTRACTION_INSTRUCTIONS,
                input=build_capture_input(capture),
                text_format=OpenAIExtractionBatch,
            )
        except OpenAIError:
            raise OpenAIProviderError("OpenAI extraction request failed") from None
        except ValidationError:
            raise OpenAIResponseError("OpenAI returned malformed structured output") from None

        parsed = response.output_parsed
        if not isinstance(parsed, OpenAIExtractionBatch):
            raise OpenAIResponseError(
                "OpenAI refused the request or returned no parsed structured output"
            )

        try:
            return tuple(candidate.to_candidate() for candidate in parsed.candidates)
        except ValidationError:
            raise OpenAIResponseError("OpenAI returned an unusable extraction result") from None
