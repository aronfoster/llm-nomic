"""Deterministic, offline stand-in for a provider API client.

``ScriptedApiClient`` implements ``ApiClientProtocol`` without any SDK,
credential, or network use. It recognises which engine phase a prompt
belongs to from the instruction headers in ``llm/prompts.py`` and returns
a valid JSON reply for that phase, so a whole game can run in-process.
The reply logic lives in ``tests/scripted_replies.py`` so a fake CLI
subprocess can share it.
"""

from __future__ import annotations

from collections import Counter

from src.nomic_engine.data_models import ChatMessage, CompletionResult
from tests.scripted_replies import phase_of, reply_for


class ScriptedApiClient:
    """Answers every engine prompt with a fixed, valid, cheap reply.

    Args:
        owner: Name of the actor this client serves. The judge client is
            created with ``owner="judge"``.
        score_delta: Points the judge awards the proposer of a passed
            proposal.
        calls: Optional shared counter of phases seen, for assertions.
    """

    def __init__(
        self,
        owner: str,
        *,
        score_delta: int = 3,
        calls: Counter[str] | None = None,
    ) -> None:
        self.owner = owner
        self.score_delta = score_delta
        self.calls: Counter[str] = calls if calls is not None else Counter()
        self._proposal_count = 0

    @staticmethod
    def phase_of(text: str) -> str:
        """Return the engine phase a prompt text asks for."""
        return phase_of(text)

    def get_completion(
        self, messages: list[ChatMessage], *, use_cache_control: bool = True
    ) -> CompletionResult:
        last = messages[-1].content
        phase = phase_of(last)
        self.calls[phase] += 1
        if phase == "propose":
            self._proposal_count += 1
        return CompletionResult(
            text=reply_for(
                phase,
                owner=self.owner,
                score_delta=self.score_delta,
                proposal_count=self._proposal_count,
                context="\n".join(m.content for m in messages),
                last_prompt=last,
            ),
            raw_response=None,
            client_latency_ms=0,
        )
