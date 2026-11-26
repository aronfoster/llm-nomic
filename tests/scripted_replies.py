"""Pure reply logic shared by the in-process and subprocess fakes.

No project imports, so a fake CLI process can load it quickly. Given the
prompt text, ``phase_of`` names the engine phase and ``reply_for``
returns a valid, cheap answer for it.
"""

from __future__ import annotations

import json
from typing import Any

# Instruction header (or opening phrase) -> phase name.
PHASE_MARKERS: tuple[tuple[str, str], ...] = (
    ("=== YOUR PROPOSAL ===", "propose"),
    ("=== YOUR DISCUSSION ===", "discuss"),
    ("=== REVISION DECISION ===", "revise"),
    ("=== YOUR VOTE ===", "vote"),
    ("Review the proposal outcome.", "judge_veto"),
    ("Assign score changes for this move.", "judge_score"),
    ("Review the rule change and determine", "judge_maintain_state"),
    ("Update your private memory.", "memory"),
)


def phase_of(text: str) -> str:
    """Return the phase whose marker appears LAST in ``text``.

    The newest prompt is last, so earlier turns in a long history, or a
    flattened multi-message prompt, cannot confuse the match.
    """
    best: tuple[int, str] | None = None
    for marker, phase in PHASE_MARKERS:
        index = text.rfind(marker)
        if index >= 0 and (best is None or index > best[0]):
            best = (index, phase)
    if best is None:
        raise AssertionError(
            f"scripted reply does not recognise this prompt: {text[:200]!r}"
        )
    return best[1]


def proposer_name(context: str) -> str | None:
    """Find the proposer named in the judge's turn context."""
    for line in context.splitlines():
        stripped = line.strip()
        if stripped.startswith("**Proposer:**"):
            return stripped.split("**Proposer:**", 1)[1].strip().split()[0]
    return None


def reply_for(
    phase: str,
    *,
    owner: str,
    score_delta: int,
    proposal_count: int,
    context: str,
    last_prompt: str,
) -> str:
    """Return the scripted answer text for one phase."""
    if phase == "memory":
        return f"{owner}: scripted memory note."
    body: dict[str, Any]
    if phase == "propose":
        body = {
            "private_thoughts": "Scripted proposal.",
            "type": "ADD",
            "target_rule_id": None,
            "new_text": (
                f"Scripted rule from {owner} "
                f"#{proposal_count}: players should be polite."
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
        adjustments: list[dict[str, Any]] = []
        proposer = proposer_name(context)
        if "**FAILED**" not in last_prompt and proposer is not None:
            adjustments = [
                {
                    "player": proposer,
                    "delta": score_delta,
                    "reason": "Passed proposal",
                }
            ]
        body = {
            "private_thoughts": "Award the proposer.",
            "score_adjustments": adjustments,
        }
    else:  # judge_maintain_state
        body = {
            "private_thoughts": "No engine change.",
            "flags": {},
            "target_score": None,
        }
    return json.dumps(body)
