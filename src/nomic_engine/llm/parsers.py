"""
Parsers for LLM response formats.

This module handles parsing and validating LLM responses,
particularly for the vote action which requires strict JSON format.
"""

import json
import logging

logger = logging.getLogger(__name__)


def parse_vote_response(response_text: str) -> dict[str, str]:
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
        A validated dictionary with keys: vote, public_reason, private_thoughts

    Raises:
        ValueError: If the response is not valid JSON, missing required keys,
                   or contains invalid values. Error messages are descriptive
                   to aid debugging and can be sent back to the LLM.
    """
    # TODO: Add string cleaning for responses wrapped in markdown code blocks
    # e.g., responses like: ```json\n{...}\n```
    # This will be implemented in a future iteration

    # Step 1: Parse JSON
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Response is not valid JSON. Error: {e}. "
            f"Expected a JSON object with keys: private_thoughts, "
            f"public_reason, vote."
        )

    # Step 2: Validate that it's a dictionary
    if not isinstance(data, dict):
        raise ValueError(
            f"Response must be a JSON object (dict), "
            f"got {type(data).__name__}."
        )

    # Step 3: Validate required keys
    required_keys = ["vote", "public_reason", "private_thoughts"]
    missing_keys = [key for key in required_keys if key not in data]
    if missing_keys:
        raise ValueError(
            f"Missing required key(s): {', '.join(missing_keys)}. "
            f"Required keys are: {', '.join(required_keys)}."
        )

    # Step 4: Validate vote value (case-insensitive)
    vote_value = data["vote"]
    if not isinstance(vote_value, str):
        raise ValueError(
            f"Vote must be a string, got {type(vote_value).__name__}."
        )

    # Normalize to uppercase for validation
    vote_normalized = vote_value.upper()
    valid_votes = ["YES", "NO", "ABSTAIN"]
    if vote_normalized not in valid_votes:
        raise ValueError(
            f"Invalid vote value: '{vote_value}'. "
            f"Must be one of: {', '.join(valid_votes)} (case-insensitive)."
        )

    # Update the vote to normalized uppercase
    data["vote"] = vote_normalized

    # Step 5: Validate that public_reason and private_thoughts are strings
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

    return data


def parse_discussion_response(response_text: str) -> dict[str, str]:
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
        A validated dictionary with keys: private_thoughts, discussion_text

    Raises:
        ValueError: If the response is not valid JSON, missing required keys,
                   or contains invalid values. Error messages are descriptive
                   to aid debugging and can be sent back to the LLM.
    """
    # Step 1: Parse JSON
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Response is not valid JSON. Error: {e}. "
            f"Expected a JSON object with keys: private_thoughts, "
            f"discussion_text."
        )

    # Step 2: Validate that it's a dictionary
    if not isinstance(data, dict):
        raise ValueError(
            f"Response must be a JSON object (dict), "
            f"got {type(data).__name__}."
        )

    # Step 3: Validate required keys
    required_keys = ["private_thoughts", "discussion_text"]
    missing_keys = [key for key in required_keys if key not in data]
    if missing_keys:
        raise ValueError(
            f"Missing required key(s): {', '.join(missing_keys)}. "
            f"Required keys are: {', '.join(required_keys)}."
        )

    # Step 4: Validate that both fields are strings
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

    return data
