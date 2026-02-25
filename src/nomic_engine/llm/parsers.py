"""
Parsers for LLM response formats.

This module handles parsing and validating LLM responses,
particularly for the vote action which requires strict JSON format.
"""

import json
import logging
from typing import Any, Literal, TypedDict

from ..judge_contracts import ScoreAdjustment

logger = logging.getLogger(__name__)


class VoteResponse(TypedDict):
    """Return type for parse_vote_response."""

    private_thoughts: str
    public_reason: str
    vote: Literal["YES", "NO", "ABSTAIN"]


class DiscussionResponse(TypedDict):
    """Return type for parse_discussion_response."""

    private_thoughts: str
    discussion_text: str


class ProposalResponse(TypedDict):
    """Return type for parse_proposal_response."""

    private_thoughts: str
    type: Literal["Add", "Amend", "Repeal", "Transmute"]
    rationale: str
    target_rule_id: str | None
    new_text: str | None


class RevisionResponse(TypedDict):
    """Return type for parse_revision_response."""

    private_thoughts: str
    action: Literal["KEEP", "MODIFY", "WITHDRAW"]
    new_text: str | None
    rationale: str | None


class ParseJudgeVetoResponse(TypedDict):
    """Return type for parse_judge_veto_response."""

    private_thoughts: str
    veto: bool
    reason: str


class ParseJudgeScoreResponse(TypedDict):
    """Return type for parse_judge_score_response."""

    private_thoughts: str
    score_adjustments: list[ScoreAdjustment]


class MaintainStateResponse(TypedDict):
    """Return type for parse_judge_maintain_state_response."""

    private_thoughts: str
    flags: dict[str, Any]
    target_score: int | None


def _extract_json_string(text: str) -> str:
    """
    Extract JSON object from text that may contain surrounding content.

    Many LLMs wrap JSON output in markdown code blocks or include
    conversational text. This function extracts the JSON substring
    by finding the first '{' and last '}' characters.

    Args:
        text: The raw text that may contain a JSON object.

    Returns:
        The extracted JSON substring if braces are found in valid positions,
        otherwise returns the original text unchanged.
    """
    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and start < end:
        return text[start : end + 1]

    return text


def parse_vote_response(response_text: str) -> VoteResponse:
    """
    Parse and validate a vote response from an LLM.

    Expected JSON format:
    {
        "private_thoughts": "Strategic analysis...",
        "public_reason": "Explanation for other players...",
        "vote": "YES" | "NO" | "ABSTAIN"
    }

    Args:
        response_text: The raw text response from the LLM.

    Returns:
        A validated VoteResponse with keys: vote, public_reason,
        private_thoughts

    Raises:
        ValueError: If the response is not valid JSON, missing required keys,
                   or contains invalid values. Error messages are descriptive
                   to aid debugging and can be sent back to the LLM.
    """
    # Step 1: Extract JSON from potential markdown/conversational wrapping
    cleaned_text = _extract_json_string(response_text)

    # Step 2: Parse JSON
    try:
        data = json.loads(cleaned_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Response is not valid JSON. Error: {e}. "
            f"Expected a JSON object with keys: private_thoughts, "
            f"public_reason, vote."
        )

    # Step 3: Validate that it's a dictionary
    if not isinstance(data, dict):
        raise ValueError(
            f"Response must be a JSON object (dict), "
            f"got {type(data).__name__}."
        )

    # Step 4: Validate required keys
    required_keys = ["vote", "public_reason", "private_thoughts"]
    missing_keys = [key for key in required_keys if key not in data]
    if missing_keys:
        raise ValueError(
            f"Missing required key(s): {', '.join(missing_keys)}. "
            f"Required keys are: {', '.join(required_keys)}."
        )

    # Step 5: Validate vote value (case-insensitive)
    vote_value = data["vote"]
    if not isinstance(vote_value, str):
        raise ValueError(
            f"Vote must be a string, got {type(vote_value).__name__}."
        )

    # Normalize to uppercase for validation
    vote_normalized = vote_value.upper()
    vote_lit_map: dict[str, Literal["YES", "NO", "ABSTAIN"]] = {
        "YES": "YES",
        "NO": "NO",
        "ABSTAIN": "ABSTAIN",
    }
    if vote_normalized not in vote_lit_map:
        raise ValueError(
            f"Invalid vote value: '{vote_value}'. "
            f"Must be one of: {', '.join(vote_lit_map)} (case-insensitive)."
        )

    vote_lit = vote_lit_map[vote_normalized]

    # Step 6: Validate that public_reason and private_thoughts are strings
    if not isinstance(data["public_reason"], str):
        raise ValueError(
            f"public_reason must be a string, "
            f"got {type(data['public_reason']).__name__}."
        )

    if not isinstance(data["private_thoughts"], str):
        raise ValueError(
            f"private_thoughts must be a string, "
            f"got {type(data['private_thoughts']).__name__}."
        )

    private_thoughts: str = data["private_thoughts"]
    public_reason: str = data["public_reason"]
    return VoteResponse(
        private_thoughts=private_thoughts,
        public_reason=public_reason,
        vote=vote_lit,
    )


def parse_discussion_response(response_text: str) -> DiscussionResponse:
    """
    Parse and validate a discussion response from an LLM.

    Expected JSON format:
    {
        "private_thoughts": "Strategic analysis...",
        "discussion_text": "Public comment for other players..."
    }

    Args:
        response_text: The raw text response from the LLM.

    Returns:
        A validated DiscussionResponse with keys: private_thoughts,
        discussion_text

    Raises:
        ValueError: If the response is not valid JSON, missing required keys,
                   or contains invalid values. Error messages are descriptive
                   to aid debugging and can be sent back to the LLM.
    """
    # Step 1: Extract JSON from potential markdown/conversational wrapping
    cleaned_text = _extract_json_string(response_text)

    # Step 2: Parse JSON
    try:
        data = json.loads(cleaned_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Response is not valid JSON. Error: {e}. "
            f"Expected a JSON object with keys: private_thoughts, "
            f"discussion_text."
        )

    # Step 3: Validate that it's a dictionary
    if not isinstance(data, dict):
        raise ValueError(
            f"Response must be a JSON object (dict), "
            f"got {type(data).__name__}."
        )

    # Step 4: Validate required keys
    required_keys = ["private_thoughts", "discussion_text"]
    missing_keys = [key for key in required_keys if key not in data]
    if missing_keys:
        raise ValueError(
            f"Missing required key(s): {', '.join(missing_keys)}. "
            f"Required keys are: {', '.join(required_keys)}."
        )

    # Step 5: Validate that both fields are strings
    if not isinstance(data["private_thoughts"], str):
        raise ValueError(
            f"private_thoughts must be a string, "
            f"got {type(data['private_thoughts']).__name__}."
        )

    if not isinstance(data["discussion_text"], str):
        raise ValueError(
            f"discussion_text must be a string, "
            f"got {type(data['discussion_text']).__name__}."
        )

    private_thoughts: str = data["private_thoughts"]
    discussion_text: str = data["discussion_text"]
    return DiscussionResponse(
        private_thoughts=private_thoughts,
        discussion_text=discussion_text,
    )


def parse_proposal_response(response_text: str) -> ProposalResponse:
    """
    Parse and validate a proposal response from an LLM.

    Expected JSON format:
    {
        "private_thoughts": "Strategic analysis...",
        "type": "ADD" | "AMEND" | "REPEAL" | "TRANSMUTE",
        "target_rule_id": "201" | null,
        "new_text": "Rule text..." | null,
        "rationale": "Public explanation..."
    }

    Args:
        response_text: The raw text response from the LLM.

    Returns:
        A validated ProposalResponse with keys: private_thoughts, type,
        target_rule_id, new_text, rationale

    Raises:
        ValueError: If the response is not valid JSON, missing required keys,
                   contains invalid values, or violates game logic constraints.
                   Error messages are descriptive to aid debugging and can be
                   sent back to the LLM.
    """
    # Step 1: Extract JSON from potential markdown/conversational wrapping
    cleaned_text = _extract_json_string(response_text)

    # Step 2: Parse JSON
    try:
        data = json.loads(cleaned_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Response is not valid JSON. Error: {e}. "
            f"Expected a JSON object with keys: private_thoughts, type, "
            f"target_rule_id, new_text, rationale."
        )

    # Step 3: Validate that it's a dictionary
    if not isinstance(data, dict):
        raise ValueError(
            f"Response must be a JSON object (dict), "
            f"got {type(data).__name__}."
        )

    # Step 4: Validate required keys (always required)
    required_keys = ["private_thoughts", "type", "rationale"]
    missing_keys = [key for key in required_keys if key not in data]
    if missing_keys:
        raise ValueError(
            f"Missing required key(s): {', '.join(missing_keys)}. "
            f"Required keys are: private_thoughts, type, target_rule_id, "
            f"new_text, rationale."
        )

    # Step 5: Validate type value (case-insensitive)
    proposal_type = data["type"]
    if not isinstance(proposal_type, str):
        raise ValueError(
            f"type must be a string, got {type(proposal_type).__name__}."
        )

    # Normalize to capitalized format matching ProposalType enum values
    proposal_type_upper = proposal_type.upper()
    # Map from uppercase to ProposalType enum values
    type_map: dict[str, Literal["Add", "Amend", "Repeal", "Transmute"]] = {
        "ADD": "Add",
        "AMEND": "Amend",
        "REPEAL": "Repeal",
        "TRANSMUTE": "Transmute",
    }
    if proposal_type_upper not in type_map:
        valid = "ADD, AMEND, REPEAL, TRANSMUTE"
        raise ValueError(
            f"Invalid type value: '{proposal_type}'. "
            f"Must be one of: {valid} (case-insensitive)."
        )

    type_lit = type_map[proposal_type_upper]

    # Step 6: Validate that private_thoughts and rationale are strings
    if not isinstance(data["private_thoughts"], str):
        raise ValueError(
            f"private_thoughts must be a string, "
            f"got {type(data['private_thoughts']).__name__}."
        )

    if not isinstance(data["rationale"], str):
        raise ValueError(
            f"rationale must be a string, "
            f"got {type(data['rationale']).__name__}."
        )

    # Step 7: Validate target_rule_id type (string or null)
    target_rule_id = data.get("target_rule_id")
    if target_rule_id is not None and not isinstance(target_rule_id, str):
        raise ValueError(
            f"target_rule_id must be a string or null, "
            f"got {type(target_rule_id).__name__}."
        )

    # Step 8: Validate new_text type (string or null)
    new_text = data.get("new_text")
    if new_text is not None and not isinstance(new_text, str):
        raise ValueError(
            f"new_text must be a string or null, "
            f"got {type(new_text).__name__}."
        )

    # Step 9: CRITICAL Game Logic Validation
    # Use the uppercase version for comparisons
    proposal_type_upper = proposal_type_upper  # Already defined above

    if proposal_type_upper == "ADD":
        # ADD: new_text is required, target_rule_id must be None
        if not new_text:
            raise ValueError(
                "Missing 'new_text' for ADD proposal. "
                "ADD proposals must include the text of the new rule."
            )
        if target_rule_id is not None:
            # Clear it rather than error - the LLM might have included it
            # But log this is a deviation from spec - actually, let's be strict
            raise ValueError(
                "ADD proposals must not have a 'target_rule_id'. "
                "Set target_rule_id to null for ADD proposals."
            )

    elif proposal_type_upper == "AMEND":
        # AMEND: target_rule_id AND new_text are required
        if not target_rule_id:
            raise ValueError(
                "Missing 'target_rule_id' for AMEND proposal. "
                "AMEND proposals must specify which rule to modify."
            )
        if not new_text:
            raise ValueError(
                "Missing 'new_text' for AMEND proposal. "
                "AMEND proposals must include the new rule text."
            )

    elif proposal_type_upper == "REPEAL":
        # REPEAL: target_rule_id is required, new_text should be null
        if not target_rule_id:
            raise ValueError(
                "Missing 'target_rule_id' for REPEAL proposal. "
                "REPEAL proposals must specify which rule to delete."
            )
        if new_text is not None:
            raise ValueError(
                "REPEAL proposals must not have 'new_text'. "
                "Set new_text to null for REPEAL proposals."
            )

    elif proposal_type_upper == "TRANSMUTE":
        # TRANSMUTE: target_rule_id is required, new_text should be null
        if not target_rule_id:
            raise ValueError(
                "Missing 'target_rule_id' for TRANSMUTE proposal. "
                "TRANSMUTE proposals must specify which rule to transmute."
            )
        if new_text is not None:
            raise ValueError(
                "TRANSMUTE proposals must not have 'new_text'. "
                "Set new_text to null for TRANSMUTE proposals."
            )

    private_thoughts_p: str = data["private_thoughts"]
    rationale: str = data["rationale"]
    target_rule_id_val: str | None = target_rule_id
    new_text_val: str | None = new_text
    return ProposalResponse(
        private_thoughts=private_thoughts_p,
        type=type_lit,
        rationale=rationale,
        target_rule_id=target_rule_id_val,
        new_text=new_text_val,
    )


def parse_judge_veto_response(
    response_text: str,
) -> ParseJudgeVetoResponse:
    """Parse and validate a veto decision from the Judge LLM."""

    cleaned_text = _extract_json_string(response_text)

    try:
        data = json.loads(cleaned_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            "Response is not valid JSON for judge veto. "
            f"Error: {e}. Expected keys: private_thoughts, veto, reason."
        )

    if not isinstance(data, dict):
        raise ValueError(
            "Judge veto response must be a JSON object with keys: "
            "private_thoughts, veto, reason."
        )

    required_keys = ["private_thoughts", "veto", "reason"]
    missing = [key for key in required_keys if key not in data]
    if missing:
        raise ValueError(
            "Missing required key(s) in judge veto response: "
            f"{', '.join(missing)}."
        )

    if not isinstance(data["private_thoughts"], str):
        raise ValueError("private_thoughts must be a string.")

    if not isinstance(data["reason"], str):
        raise ValueError("reason must be a string.")

    veto_value = data["veto"]
    if not isinstance(veto_value, bool):
        raise ValueError("veto must be a boolean (true or false).")

    private_thoughts: str = data["private_thoughts"]
    reason: str = data["reason"]
    veto: bool = veto_value
    return ParseJudgeVetoResponse(
        private_thoughts=private_thoughts,
        veto=veto,
        reason=reason,
    )


def parse_judge_score_response(
    response_text: str,
    valid_players: list[str],
) -> ParseJudgeScoreResponse:
    """Parse and validate score adjustments from the Judge LLM."""

    cleaned_text = _extract_json_string(response_text)

    try:
        data = json.loads(cleaned_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            "Response is not valid JSON for judge scoring. "
            f"Error: {e}. Expected keys: private_thoughts, score_adjustments."
        )

    if not isinstance(data, dict):
        raise ValueError(
            "Judge score response must be a JSON object with keys: "
            "private_thoughts, score_adjustments."
        )

    required_keys = ["private_thoughts", "score_adjustments"]
    missing = [key for key in required_keys if key not in data]
    if missing:
        raise ValueError(
            "Missing required key(s) in judge score response: "
            f"{', '.join(missing)}."
        )

    if not isinstance(data["private_thoughts"], str):
        raise ValueError("private_thoughts must be a string.")

    adjustments = data["score_adjustments"]
    if not isinstance(adjustments, list):
        raise ValueError("score_adjustments must be a list.")

    typed_adjustments: list[ScoreAdjustment] = []
    for idx, adj in enumerate(adjustments):
        if not isinstance(adj, dict):
            raise ValueError(
                f"Adjustment #{idx + 1} must be an object with player, "
                "delta, reason."
            )

        for key in ["player", "delta", "reason"]:
            if key not in adj:
                raise ValueError(
                    f"Adjustment #{idx + 1} is missing required key: {key}."
                )

        if not isinstance(adj["player"], str):
            raise ValueError(f"Adjustment #{idx + 1} player must be a string.")

        if adj["player"] not in valid_players:
            raise ValueError(
                f"Adjustment #{idx + 1} references unknown player "
                f"'{adj['player']}'. Valid players: "
                f"{', '.join(valid_players)}."
            )

        if not isinstance(adj["delta"], int):
            raise ValueError(
                f"Adjustment #{idx + 1} delta must be an integer."
            )

        if not isinstance(adj["reason"], str):
            raise ValueError(f"Adjustment #{idx + 1} reason must be a string.")

        player: str = adj["player"]
        delta: int = adj["delta"]
        adj_reason: str = adj["reason"]
        typed_adjustments.append(
            ScoreAdjustment(player=player, delta=delta, reason=adj_reason)
        )

    private_thoughts_s: str = data["private_thoughts"]
    return ParseJudgeScoreResponse(
        private_thoughts=private_thoughts_s,
        score_adjustments=typed_adjustments,
    )


def parse_revision_response(response_text: str) -> RevisionResponse:
    """
    Parse and validate a revision response from an LLM.

    Expected JSON format:
    {
        "private_thoughts": "Strategic analysis...",
        "action": "KEEP" | "MODIFY" | "WITHDRAW",
        "new_text": "New rule text..." | null,
        "rationale": "New rationale..." | null
    }

    Args:
        response_text: The raw text response from the LLM.

    Returns:
        A validated RevisionResponse with keys: private_thoughts, action,
        new_text, rationale

    Raises:
        ValueError: If the response is not valid JSON, missing required keys,
                   contains invalid values, or violates revision logic
                   constraints. Error messages are descriptive to aid debugging
                   and can be sent back to the LLM.
    """
    # Step 1: Extract JSON from potential markdown/conversational wrapping
    cleaned_text = _extract_json_string(response_text)

    # Step 2: Parse JSON
    try:
        data = json.loads(cleaned_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Response is not valid JSON. Error: {e}. "
            f"Expected a JSON object with keys: private_thoughts, action, "
            f"new_text, rationale."
        )

    # Step 3: Validate that it's a dictionary
    if not isinstance(data, dict):
        raise ValueError(
            f"Response must be a JSON object (dict), "
            f"got {type(data).__name__}."
        )

    # Step 4: Validate required keys
    required_keys = ["private_thoughts", "action"]
    missing_keys = [key for key in required_keys if key not in data]
    if missing_keys:
        raise ValueError(
            f"Missing required key(s): {', '.join(missing_keys)}. "
            f"Required keys are: private_thoughts, action, new_text, "
            f"rationale."
        )

    # Step 5: Validate action value (case-insensitive)
    action_value = data["action"]
    if not isinstance(action_value, str):
        raise ValueError(
            f"action must be a string, got {type(action_value).__name__}."
        )

    # Normalize to uppercase for validation
    action_normalized = action_value.upper()
    action_lit_map: dict[str, Literal["KEEP", "MODIFY", "WITHDRAW"]] = {
        "KEEP": "KEEP",
        "MODIFY": "MODIFY",
        "WITHDRAW": "WITHDRAW",
    }
    if action_normalized not in action_lit_map:
        raise ValueError(
            f"Invalid action value: '{action_value}'. "
            f"Must be one of: {', '.join(action_lit_map)} (case-insensitive)."
        )

    action_lit = action_lit_map[action_normalized]

    # Step 6: Validate that private_thoughts is a string
    if not isinstance(data["private_thoughts"], str):
        raise ValueError(
            f"private_thoughts must be a string, "
            f"got {type(data['private_thoughts']).__name__}."
        )

    # Step 7: Validate new_text type (string or null)
    new_text = data.get("new_text")
    if new_text is not None and not isinstance(new_text, str):
        raise ValueError(
            f"new_text must be a string or null, "
            f"got {type(new_text).__name__}."
        )

    # Step 8: Validate rationale type (string or null)
    rationale = data.get("rationale")
    if rationale is not None and not isinstance(rationale, str):
        raise ValueError(
            f"rationale must be a string or null, "
            f"got {type(rationale).__name__}."
        )

    # Step 9: CRITICAL Game Logic Validation for MODIFY action
    if action_normalized == "MODIFY":
        # MODIFY: At least one of new_text or rationale must be provided
        if not new_text and not rationale:
            raise ValueError(
                "MODIFY action requires at least one of 'new_text' or "
                "'rationale' to be provided. If you want to keep the proposal "
                "unchanged, use 'KEEP' instead."
            )

    private_thoughts_r: str = data["private_thoughts"]
    new_text_r: str | None = new_text
    rationale_r: str | None = rationale
    return RevisionResponse(
        private_thoughts=private_thoughts_r,
        action=action_lit,
        new_text=new_text_r,
        rationale=rationale_r,
    )


def parse_judge_maintain_state_response(
    response_text: str,
) -> MaintainStateResponse:
    """
    Parse and validate a maintain_state response from the Judge LLM.

    Expected JSON format:
    {
        "private_thoughts": "Reasoning about state changes...",
        "flags": {"vote_mode": "majority"},  # or {}
        "target_score": 100  # or null
    }

    Args:
        response_text: The raw text response from the LLM.

    Returns:
        A validated MaintainStateResponse with keys: private_thoughts,
        flags, target_score

    Raises:
        ValueError: If the response is not valid JSON, missing required
            keys, contains invalid values, or violates flag schema
            constraints. Error messages are descriptive to aid debugging
            and can be sent back to the LLM.
    """
    from ..utils.flag_schema import validate_state_updates

    # Step 1: Extract JSON from potential markdown/conversational wrapping
    cleaned_text = _extract_json_string(response_text)

    # Step 2: Parse JSON
    try:
        data = json.loads(cleaned_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Response is not valid JSON. Error: {e}. "
            f"Expected a JSON object with keys: private_thoughts, flags, "
            f"target_score."
        )

    # Step 3: Validate that it's a dictionary
    if not isinstance(data, dict):
        raise ValueError(
            f"Response must be a JSON object (dict), "
            f"got {type(data).__name__}."
        )

    # Step 4: Validate required keys
    required_keys = ["private_thoughts", "flags", "target_score"]
    missing_keys = [key for key in required_keys if key not in data]
    if missing_keys:
        raise ValueError(
            f"Missing required key(s): {', '.join(missing_keys)}. "
            f"Required keys are: {', '.join(required_keys)}."
        )

    # Step 5: Validate private_thoughts is a string
    if not isinstance(data["private_thoughts"], str):
        raise ValueError(
            f"private_thoughts must be a string, "
            f"got {type(data['private_thoughts']).__name__}."
        )

    # Step 6: Validate flags is a dict
    flags = data["flags"]
    if not isinstance(flags, dict):
        raise ValueError(
            f"flags must be a dict/object, got {type(flags).__name__}."
        )

    # Step 7: Validate target_score is int or None
    target_score = data["target_score"]
    if target_score is not None and not isinstance(target_score, int):
        raise ValueError(
            f"target_score must be an integer or null, "
            f"got {type(target_score).__name__}."
        )

    # Step 8: Build StateUpdates and validate against schema
    state_updates: dict[str, Any] = {}
    if flags:
        state_updates["flags"] = flags
    if target_score is not None:
        state_updates["target_score"] = target_score

    # This will validate flag names and values against the schema
    validate_state_updates(state_updates)

    private_thoughts_m: str = data["private_thoughts"]
    flags_m: dict[str, Any] = flags
    target_score_m: int | None = target_score
    return MaintainStateResponse(
        private_thoughts=private_thoughts_m,
        flags=flags_m,
        target_score=target_score_m,
    )
