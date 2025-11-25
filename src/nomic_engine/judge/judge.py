"""Judge selection object for configuring game resolution."""

from __future__ import annotations

from ..data_models import JudgeType, ModelDefinition


class Judge:
    """Container for judge configuration.

    Attributes:
        judge_type: Whether the judge is a human or an LLM.
        model: The LLM model definition, required when judge_type is LLM.
    """

    def __init__(
        self, judge_type: JudgeType, model: ModelDefinition | None = None
    ) -> None:
        self.judge_type = judge_type
        self.model = model

        if judge_type == JudgeType.LLM and model is None:
            raise ValueError("LLM judge requires a model definition")
