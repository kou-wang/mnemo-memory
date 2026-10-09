"""OpenAI implementation of provider-independent grounded answer synthesis."""

from __future__ import annotations

from datetime import datetime

from openai import OpenAI, OpenAIError
from pydantic import ValidationError

from mnemo.answers.models import SynthesizedAnswer
from mnemo.interfaces.answers import AnswerSynthesizer
from mnemo.models._shared import require_non_blank, require_timezone_aware
from mnemo.models.memory import Memory
from mnemo.providers.openai.answer_prompt import (
    ANSWER_SYNTHESIS_INSTRUCTIONS,
    build_answer_input,
)
from mnemo.providers.openai.answer_schemas import OpenAIAnswerOutput


class OpenAIAnswerSynthesisError(RuntimeError):
    """Base error for failed OpenAI answer-synthesis attempts."""


class OpenAIAnswerProviderError(OpenAIAnswerSynthesisError):
    """The OpenAI API or SDK failed before producing a usable answer."""


class OpenAIAnswerResponseError(OpenAIAnswerSynthesisError):
    """The provider returned no valid structured grounded answer."""


class OpenAIAnswerSynthesizer(AnswerSynthesizer):
    """Phrase only supplied Memory evidence through Structured Outputs."""

    def __init__(self, *, model: str, client: OpenAI | None = None) -> None:
        if not model.strip():
            raise ValueError("model must not be blank")
        self._model = model.strip()
        self._client = client if client is not None else OpenAI()

    def synthesize(
        self,
        *,
        question: str,
        evidence: tuple[Memory, ...],
        asked_at: datetime,
    ) -> SynthesizedAnswer:
        question_text = require_non_blank(question, field_name="question")
        reference_time = require_timezone_aware(asked_at, field_name="asked_at")
        if not evidence:
            raise ValueError("evidence must contain at least one Memory")

        try:
            response = self._client.responses.parse(
                model=self._model,
                instructions=ANSWER_SYNTHESIS_INSTRUCTIONS,
                input=build_answer_input(
                    question=question_text,
                    evidence=evidence,
                    asked_at=reference_time,
                ),
                text_format=OpenAIAnswerOutput,
            )
        except OpenAIError:
            raise OpenAIAnswerProviderError("OpenAI answer synthesis request failed") from None
        except ValidationError:
            raise OpenAIAnswerResponseError(
                "OpenAI returned malformed structured answer output"
            ) from None

        parsed = response.output_parsed
        if not isinstance(parsed, OpenAIAnswerOutput):
            raise OpenAIAnswerResponseError(
                "OpenAI refused the request or returned no parsed grounded answer"
            )
        try:
            return parsed.to_answer()
        except ValidationError:
            raise OpenAIAnswerResponseError(
                "OpenAI returned an unusable structured grounded answer"
            ) from None
