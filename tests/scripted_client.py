"""Deterministic, offline stand-in for a provider API client.

``ScriptedApiClient`` implements ``ApiClientProtocol`` without any SDK,
credential, or network use. It recognises which engine phase a prompt
belongs to from the instruction headers in ``llm/prompts.py`` and returns
a valid JSON reply for that phase, so a whole game can run in-process.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from src.nomic_engine.data_models import ChatMessage, CompletionResult

# Instruction header (or opening phrase) -> phase name. First match wins
# against the LAST message in the conversation, which is the new prompt.
_PHASE_MARKERS: tuple[tuple[str, str], ...] = (
    ("=== YOUR PROPOSAL ===", "propose"),
    ("=== YOUR DISCUSSION ===", "discuss"),
    ("=== REVISION DECISION ===", "revise"),
    ("=== YOUR VOTE ===", "vote"),
    ("Review the proposal outcome.", "judge_veto"),
    ("Assign score changes for this move.", "judge_score"),
    ("Review the rule change and determine", "judge_maintain_state"),
    ("Update your private memory.", "memory"),
)


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
        for marker, phase in _PHASE_MARKERS:
            if marker in text:
                return phase
        raise AssertionError(
            "ScriptedApiClient does not recognise this prompt: "
            f"{text[:200]!r}"
        )

    def get_completion(
        self, messages: list[ChatMessage], *, use_cache_control: bool = True
    ) -> CompletionResult:
        phase = self.phase_of(messages[-1].content)
        self.calls[phase] += 1
        return CompletionResult(
            text=self._reply(phase, messages),
            raw_response=None,
            client_latency_ms=0,
        )

    def _reply(self, phase: str, messages: list[ChatMessage]) -> str:
        if phase == "memory":
            return f"{self.owner}: scripted memory note."
        body: dict[str, Any]
        if phase == "propose":
            self._proposal_count += 1
            body = {
                "private_thoughts": "Scripted proposal.",
                "type": "ADD",
                "target_rule_id": None,
                "new_text": (
                    f"Scripted rule from {self.owner} "
                    f"#{self._proposal_count}: players should be polite."
                ),
                "rationale": "Politeness is harmless.",
            }
        elif phase == "discuss":
            body = {
                "private_thoughts": "Scripted discussion.",
                "discussion_text": "No objection.",
            }
        elif phase == "revise":
            body = {
                "private_thoughts": "Scripted revision.",
                "action": "KEEP",
                "new_text": None,
                "rationale": None,
            }
        elif phase == "vote":
            body = {
                "private_thoughts": "Scripted vote.",
                "public_reason": "Fine by me.",
                "vote": "YES",
            }
        elif phase == "judge_veto":
            body = {
                "private_thoughts": "Nothing to veto.",
                "veto": False,
                "reason": "Legal.",
            }
        elif phase == "judge_score":
            body = {
                "private_thoughts": "Award the proposer.",
                "score_adjustments": self._score_adjustments(messages),
            }
        else:  # judge_maintain_state
            body = {
                "private_thoughts": "No engine change.",
                "flags": {},
                "target_score": None,
            }
        return json.dumps(body)

    def _score_adjustments(
        self, messages: list[ChatMessage]
    ) -> list[dict[str, Any]]:
        """Award the proposer if the proposal passed, else nobody."""
        prompt = messages[-1].content
        if "**FAILED**" in prompt:
            return []
        context = "\n".join(m.content for m in messages)
        proposer = _proposer_name(context)
        if proposer is None:
            return []
        return [
            {
                "player": proposer,
                "delta": self.score_delta,
                "reason": "Passed proposal",
            }
        ]


def _proposer_name(context: str) -> str | None:
    """Find the proposer named in the judge's turn context."""
    for line in context.splitlines():
        stripped = line.strip()
        if stripped.startswith("**Proposer:**"):
            return stripped.split("**Proposer:**", 1)[1].strip().split()[0]
    return None
