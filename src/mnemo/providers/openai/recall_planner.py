"""OpenAI implementation of provider-independent recall planning."""

from __future__ import annotations

from datetime import datetime

from openai import OpenAI, OpenAIError
from pydantic import ValidationError

from mnemo.interfaces.recall import RecallPlanner
from mnemo.models._shared import require_non_blank, require_timezone_aware
from mnemo.providers.openai.recall_prompt import (
    RECALL_PLANNING_INSTRUCTIONS,
    build_recall_planning_input,
)
from mnemo.providers.openai.recall_schemas import OpenAIRecallPlanOutput
from mnemo.recall.models import RecallPlan


class OpenAIRecallPlanningError(RuntimeError):
    """Base error for failed OpenAI recall-planning attempts."""


class OpenAIRecallProviderError(OpenAIRecallPlanningError):
    """The OpenAI API or SDK failed before producing a usable plan."""


class OpenAIRecallResponseError(OpenAIRecallPlanningError):
    """The provider returned no valid structured recall plan."""


class OpenAIRecallPlanner(RecallPlanner):
    """Interpret questions without retrieval, persistence, or lifecycle authority."""

    def __init__(self, *, model: str, client: OpenAI | None = None) -> None:
        if not model.strip():
            raise ValueError("model must not be blank")
        self._model = model.strip()
        self._client = client if client is not None else OpenAI()

    def plan(
        self,
        *,
        user_id: str,
        question: str,
        asked_at: datetime,
    ) -> RecallPlan:
        scoped_user_id = require_non_blank(user_id, field_name="user_id")
        question_text = require_non_blank(question, field_name="question")
        reference_time = require_timezone_aware(asked_at, field_name="asked_at")
        try:
            response = self._client.responses.parse(
                model=self._model,
                instructions=RECALL_PLANNING_INSTRUCTIONS,
                input=build_recall_planning_input(
                    question=question_text,
                    asked_at=reference_time,
                ),
                text_format=OpenAIRecallPlanOutput,
            )
        except OpenAIError:
            raise OpenAIRecallProviderError("OpenAI recall planning request failed") from None
        except ValidationError:
            raise OpenAIRecallResponseError(
                "OpenAI returned malformed structured recall planning output"
            ) from None

        parsed = response.output_parsed
        if not isinstance(parsed, OpenAIRecallPlanOutput):
            raise OpenAIRecallResponseError(
                "OpenAI refused the request or returned no parsed recall plan"
            )
        try:
            return parsed.to_plan(user_id=scoped_user_id)
        except ValidationError:
            raise OpenAIRecallResponseError(
                "OpenAI returned an unusable structured recall plan"
            ) from None
