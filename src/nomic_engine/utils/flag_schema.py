"""
Flag schema loader and validator.

Loads flag definitions from flag_schema.json and provides utilities for:
- Building default flag values from schema
- Validating flag values against the schema
- Formatting flag information for prompts
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..constants import FLAG_SCHEMA_FILE

logger = logging.getLogger(__name__)

# Cached schema to avoid repeated disk reads
_cached_schema: dict[str, Any] | None = None


class FlagSchemaError(Exception):
    """Raised when the flag schema file is missing or malformed."""


def load_flag_schema() -> dict[str, Any]:
    """
    Load and return the flag schema from flag_schema.json.

    Returns:
        Dictionary mapping flag names to their schema definitions.
        Each definition contains: type, valid_values, default, description.

    Raises:
        FlagSchemaError: If the file is missing, unreadable, or malformed.
    """
    global _cached_schema
    if _cached_schema is not None:
        return _cached_schema

    schema_path = Path(FLAG_SCHEMA_FILE)

    try:
        with schema_path.open("r", encoding="utf-8") as f:
            schema = json.load(f)
    except FileNotFoundError:
        raise FlagSchemaError(f"Flag schema file not found: {schema_path}")
    except json.JSONDecodeError as e:
        raise FlagSchemaError(f"Malformed JSON in {schema_path}: {e}") from e
    except OSError as e:
        raise FlagSchemaError(f"Cannot read {schema_path}: {e}") from e

    if not isinstance(schema, dict):
        raise FlagSchemaError(
            f"Flag schema must be a JSON object, "
            f"got {type(schema).__name__}"
        )

    # Validate each flag entry has required fields
    required_fields = {"type", "valid_values", "default", "description"}
    for flag_name, definition in schema.items():
        if not isinstance(definition, dict):
            raise FlagSchemaError(
                f"Flag '{flag_name}' must be an object, "
                f"got {type(definition).__name__}"
            )
        missing = required_fields - set(definition.keys())
        if missing:
            raise FlagSchemaError(
                f"Flag '{flag_name}' is missing required fields: "
                f"{', '.join(sorted(missing))}"
            )

    _cached_schema = schema
    return schema


def clear_schema_cache() -> None:
    """Clear the cached schema (useful for testing)."""
    global _cached_schema
    _cached_schema = None


def get_flag_defaults() -> dict[str, Any]:
    """
    Build the default flags dictionary from the schema.

    Returns:
        Dictionary mapping flag names to their default values,
        excluding flags with null defaults.
    """
    schema = load_flag_schema()
    defaults: dict[str, Any] = {}
    for flag_name, definition in schema.items():
        if definition["default"] is not None:
            defaults[flag_name] = definition["default"]
    return defaults


def validate_flag_value(flag_name: str, value: Any) -> None:
    """
    Validate a single flag value against the schema.

    Args:
        flag_name: The name of the flag to validate.
        value: The value to validate.

    Raises:
        ValueError: If the flag is unknown or the value is invalid.
    """
    schema = load_flag_schema()

    if flag_name not in schema:
        raise ValueError(f"Unknown flag: '{flag_name}'")

    definition = schema[flag_name]
    expected_type = definition["type"]
    valid_values = definition["valid_values"]

    # Type checking
    type_map: dict[str, type] = {
        "string": str,
        "integer": int,
        "boolean": bool,
    }
    python_type = type_map.get(expected_type)
    if python_type is not None and not isinstance(value, python_type):
        raise ValueError(
            f"Flag '{flag_name}' expects type '{expected_type}', "
            f"got {type(value).__name__}"
        )

    # Valid values checking (for enum-style flags)
    if valid_values is not None and value not in valid_values:
        raise ValueError(
            f"Flag '{flag_name}' value '{value}' is not valid. "
            f"Allowed values: {valid_values}"
        )


def validate_flags(flags: dict[str, Any]) -> None:
    """
    Validate all flags in a dictionary against the schema.

    Args:
        flags: Dictionary of flag name -> value pairs.

    Raises:
        ValueError: If any flag name is unknown or value is invalid.
    """
    for flag_name, value in flags.items():
        validate_flag_value(flag_name, value)


def format_current_flags(flags: dict[str, Any]) -> str:
    """
    Format current flag values for inclusion in prompts.

    Args:
        flags: Dictionary of current flag name -> value pairs.

    Returns:
        Formatted string like:
        - vote_mode: "unanimous"
    """
    if not flags:
        return "No flags currently set."
    lines = []
    for name, value in sorted(flags.items()):
        lines.append(f'- {name}: "{value}"')
    return "\n".join(lines)


def format_supported_flags() -> str:
    """
    Format all supported flags from the schema for inclusion in prompts.

    Returns:
        Formatted string with descriptions and valid values, like:
        - vote_mode (string): Determines voting threshold. ...
          Valid values: unanimous, majority
    """
    schema = load_flag_schema()
    if not schema:
        return "No supported flags defined."
    lines = []
    for name, definition in sorted(schema.items()):
        desc = definition["description"]
        flag_type = definition["type"]
        parts = [f"- {name} ({flag_type}): {desc}"]
        if definition["valid_values"] is not None:
            vals = ", ".join(str(v) for v in definition["valid_values"])
            parts.append(f" Valid values: {vals}")
        lines.append("".join(parts))
    return "\n".join(lines)
