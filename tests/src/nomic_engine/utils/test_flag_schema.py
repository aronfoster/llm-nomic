"""
Unit tests for the flag schema loader and validator.

Covers:
1. Schema loading and parsing
2. Flag validation against schema (valid and invalid values)
3. GameState initialization with schema defaults
4. Backward compatibility (existing game states load correctly)
5. Error handling for malformed schema or invalid flag values
6. Dynamic prompt building with current and supported flags
"""

import json
from pathlib import Path

import pytest

from src.nomic_engine.data_models import GameState
from src.nomic_engine.utils.flag_schema import (
    FlagSchemaError,
    clear_schema_cache,
    format_current_flags,
    format_supported_flags,
    get_flag_defaults,
    load_flag_schema,
    validate_flag_value,
    validate_flags,
    validate_state_updates,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """Clear the schema cache before and after each test."""
    clear_schema_cache()
    yield  # type: ignore[misc]
    clear_schema_cache()


# =========================================================================
# 1. Schema loading and parsing
# =========================================================================


class TestSchemaLoading:
    """Tests for loading the flag schema from disk."""

    def test_load_flag_schema_returns_dict(self) -> None:
        """Schema loads as a dictionary."""
        schema = load_flag_schema()
        assert isinstance(schema, dict)

    def test_load_flag_schema_contains_vote_mode(self) -> None:
        """Schema contains the vote_mode flag."""
        schema = load_flag_schema()
        assert "vote_mode" in schema

    def test_vote_mode_has_required_fields(self) -> None:
        """vote_mode has type, valid_values, default, description."""
        schema = load_flag_schema()
        definition = schema["vote_mode"]
        assert definition["type"] == "string"
        assert definition["valid_values"] == ["unanimous", "majority"]
        assert definition["default"] == "unanimous"
        assert isinstance(definition["description"], str)
        assert len(definition["description"]) > 0

    def test_load_flag_schema_caches_result(self) -> None:
        """Second call returns the same cached object."""
        first = load_flag_schema()
        second = load_flag_schema()
        assert first is second

    def test_clear_schema_cache_forces_reload(self) -> None:
        """Clearing cache causes a fresh load."""
        first = load_flag_schema()
        clear_schema_cache()
        second = load_flag_schema()
        # Same content but different objects
        assert first == second


class TestSchemaLoadingErrors:
    """Tests for error handling when schema is missing or malformed."""

    def test_missing_schema_raises_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FlagSchemaError raised when schema file doesn't exist."""
        monkeypatch.chdir(tmp_path)
        with pytest.raises(FlagSchemaError, match="not found"):
            load_flag_schema()

    def test_malformed_json_raises_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FlagSchemaError raised when file has invalid JSON."""
        (tmp_path / "config").mkdir()
        bad_file = tmp_path / "config" / "flag_schema.json"
        bad_file.write_text("{ invalid json }")
        monkeypatch.chdir(tmp_path)
        with pytest.raises(FlagSchemaError, match="Malformed JSON"):
            load_flag_schema()

    def test_non_object_schema_raises_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FlagSchemaError raised when schema root is not an object."""
        (tmp_path / "config").mkdir()
        bad_file = tmp_path / "config" / "flag_schema.json"
        bad_file.write_text('["not", "an", "object"]')
        monkeypatch.chdir(tmp_path)
        with pytest.raises(FlagSchemaError, match="must be a JSON object"):
            load_flag_schema()

    def test_missing_required_fields_raises_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FlagSchemaError raised when a flag entry is missing fields."""
        (tmp_path / "config").mkdir()
        bad_file = tmp_path / "config" / "flag_schema.json"
        bad_file.write_text(json.dumps({"test_flag": {"type": "string"}}))
        monkeypatch.chdir(tmp_path)
        with pytest.raises(FlagSchemaError, match="missing required fields"):
            load_flag_schema()

    def test_non_dict_flag_entry_raises_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FlagSchemaError raised when a flag value is not a dict."""
        (tmp_path / "config").mkdir()
        bad_file = tmp_path / "config" / "flag_schema.json"
        bad_file.write_text(json.dumps({"test_flag": "not_a_dict"}))
        monkeypatch.chdir(tmp_path)
        with pytest.raises(FlagSchemaError, match="must be an object"):
            load_flag_schema()


# =========================================================================
# 2. Flag validation
# =========================================================================


class TestFlagValidation:
    """Tests for validating flag values against the schema."""

    def test_valid_vote_mode_unanimous(self) -> None:
        """'unanimous' is a valid vote_mode value."""
        validate_flag_value("vote_mode", "unanimous")

    def test_valid_vote_mode_majority(self) -> None:
        """'majority' is a valid vote_mode value."""
        validate_flag_value("vote_mode", "majority")

    def test_invalid_vote_mode_value(self) -> None:
        """Invalid vote_mode value raises ValueError."""
        with pytest.raises(ValueError, match="not valid"):
            validate_flag_value("vote_mode", "consensus")

    def test_invalid_vote_mode_type(self) -> None:
        """Wrong type for vote_mode raises ValueError."""
        with pytest.raises(ValueError, match="expects type"):
            validate_flag_value("vote_mode", 42)

    def test_unknown_flag_raises_error(self) -> None:
        """Unknown flag name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown flag"):
            validate_flag_value("nonexistent_flag", "value")

    def test_validate_flags_valid_dict(self) -> None:
        """validate_flags succeeds with valid flag dictionary."""
        validate_flags({"vote_mode": "unanimous"})

    def test_validate_flags_empty_dict(self) -> None:
        """validate_flags succeeds with empty dictionary."""
        validate_flags({})

    def test_validate_flags_invalid_value(self) -> None:
        """validate_flags raises ValueError for invalid value."""
        with pytest.raises(ValueError, match="not valid"):
            validate_flags({"vote_mode": "invalid"})

    def test_validate_flags_unknown_flag(self) -> None:
        """validate_flags raises ValueError for unknown flag."""
        with pytest.raises(ValueError, match="Unknown flag"):
            validate_flags({"unknown_flag": "value"})


class TestFlagValidationWithCustomSchema:
    """Test validation with custom schemas for various types."""

    def test_boolean_flag_validation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Boolean flags validate type correctly."""
        (tmp_path / "config").mkdir()
        schema_file = tmp_path / "config" / "flag_schema.json"
        schema_file.write_text(
            json.dumps(
                {
                    "debug_mode": {
                        "type": "boolean",
                        "valid_values": None,
                        "default": False,
                        "description": "Enable debug mode.",
                    }
                }
            )
        )
        monkeypatch.chdir(tmp_path)
        validate_flag_value("debug_mode", True)
        validate_flag_value("debug_mode", False)
        with pytest.raises(ValueError, match="expects type"):
            validate_flag_value("debug_mode", "true")

    def test_integer_flag_validation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Integer flags validate type correctly."""
        (tmp_path / "config").mkdir()
        schema_file = tmp_path / "config" / "flag_schema.json"
        schema_file.write_text(
            json.dumps(
                {
                    "max_retries": {
                        "type": "integer",
                        "valid_values": None,
                        "default": 3,
                        "description": "Maximum retry count.",
                    }
                }
            )
        )
        monkeypatch.chdir(tmp_path)
        validate_flag_value("max_retries", 5)
        with pytest.raises(ValueError, match="expects type"):
            validate_flag_value("max_retries", "five")


# =========================================================================
# 3. GameState initialization with schema defaults
# =========================================================================


class TestGameStateDefaults:
    """Tests for GameState flag defaults derived from schema."""

    def test_default_flags_match_schema(self) -> None:
        """GameState default flags come from the schema."""
        state = GameState(
            scores={"Alice": 0},
            current_player_name="Alice",
            move_number=1,
            turn_order=["Alice"],
            next_proposal_id=301,
        )
        assert state.flags == {
            "vote_mode": "unanimous",
            "majority_after_loops": 2,
            "allow_abstention": False,
        }

    def test_custom_flags_override_defaults(self) -> None:
        """Explicit flags override schema defaults."""
        state = GameState(
            scores={"Alice": 0},
            current_player_name="Alice",
            move_number=1,
            turn_order=["Alice"],
            next_proposal_id=301,
            flags={"vote_mode": "majority"},
        )
        assert state.flags == {"vote_mode": "majority"}

    def test_invalid_flag_value_raises_error(self) -> None:
        """GameState rejects invalid flag values at construction."""
        with pytest.raises(ValueError, match="not valid"):
            GameState(
                scores={"Alice": 0},
                current_player_name="Alice",
                move_number=1,
                turn_order=["Alice"],
                next_proposal_id=301,
                flags={"vote_mode": "consensus"},
            )


# =========================================================================
# 4. Backward compatibility
# =========================================================================


class TestBackwardCompatibility:
    """Ensure existing game states continue to work."""

    def test_existing_state_with_unanimous(self) -> None:
        """States from existing games with 'unanimous' still load."""
        state = GameState(
            scores={"Alice": 10, "Bob": 5},
            current_player_name="Bob",
            move_number=3,
            turn_order=["Alice", "Bob"],
            next_proposal_id=303,
            flags={"vote_mode": "unanimous"},
        )
        assert state.flags["vote_mode"] == "unanimous"

    def test_existing_state_with_majority(self) -> None:
        """States from existing games with 'majority' still load."""
        state = GameState(
            scores={"Alice": 10, "Bob": 5},
            current_player_name="Bob",
            move_number=3,
            turn_order=["Alice", "Bob"],
            next_proposal_id=303,
            flags={"vote_mode": "majority"},
        )
        assert state.flags["vote_mode"] == "majority"

    def test_state_serialization_round_trip(self) -> None:
        """GameState can serialize and deserialize with flags."""
        original = GameState(
            scores={"Alice": 0},
            current_player_name="Alice",
            move_number=1,
            turn_order=["Alice"],
            next_proposal_id=301,
            flags={"vote_mode": "majority"},
        )
        json_str = original.model_dump_json()
        restored = GameState.model_validate_json(json_str)
        assert restored.flags == {"vote_mode": "majority"}


# =========================================================================
# 5. get_flag_defaults
# =========================================================================


class TestGetFlagDefaults:
    """Tests for the get_flag_defaults function."""

    def test_returns_defaults_from_schema(self) -> None:
        """Returns the default values from the schema."""
        defaults = get_flag_defaults()
        assert defaults == {
            "vote_mode": "unanimous",
            "majority_after_loops": 2,
            "allow_abstention": False,
        }

    def test_excludes_null_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Flags with null defaults are excluded."""
        (tmp_path / "config").mkdir()
        schema_file = tmp_path / "config" / "flag_schema.json"
        schema_file.write_text(
            json.dumps(
                {
                    "has_default": {
                        "type": "string",
                        "valid_values": ["a", "b"],
                        "default": "a",
                        "description": "Has a default.",
                    },
                    "no_default": {
                        "type": "string",
                        "valid_values": ["x", "y"],
                        "default": None,
                        "description": "No default.",
                    },
                }
            )
        )
        monkeypatch.chdir(tmp_path)
        defaults = get_flag_defaults()
        assert defaults == {"has_default": "a"}
        assert "no_default" not in defaults


# =========================================================================
# 6. Prompt formatting
# =========================================================================


class TestPromptFormatting:
    """Tests for formatting flags for prompt inclusion."""

    def test_format_current_flags_single(self) -> None:
        """Formats a single flag correctly."""
        result = format_current_flags({"vote_mode": "unanimous"})
        assert result == '- vote_mode: "unanimous"'

    def test_format_current_flags_multiple(self) -> None:
        """Formats multiple flags, sorted alphabetically."""
        result = format_current_flags(
            {"vote_mode": "majority", "debug": "true"}
        )
        assert '- debug: "true"' in result
        assert '- vote_mode: "majority"' in result
        # debug should come before vote_mode
        lines = result.split("\n")
        assert lines[0].startswith("- debug")
        assert lines[1].startswith("- vote_mode")

    def test_format_current_flags_empty(self) -> None:
        """Formats empty flags dict."""
        result = format_current_flags({})
        assert result == "No flags currently set."

    def test_format_supported_flags(self) -> None:
        """Formats supported flags from schema."""
        result = format_supported_flags()
        assert "vote_mode" in result
        assert "string" in result
        assert "unanimous" in result
        assert "majority" in result
        assert "Determines voting threshold" in result

    def test_format_supported_flags_includes_valid_values(
        self,
    ) -> None:
        """Supported flags output includes valid values."""
        result = format_supported_flags()
        assert "Valid values:" in result


# =========================================================================
# 7. Dynamic prompt building integration
# =========================================================================


class TestJudgeVetoPromptIntegration:
    """Test the judge veto prompt includes dynamic flag information."""

    def test_veto_prompt_includes_current_flags(self) -> None:
        """Judge veto prompt includes current flag values."""
        from src.nomic_engine.llm.prompt_builder import PromptBuilder

        builder = PromptBuilder()
        game_state = GameState(
            scores={"Alice": 0},
            current_player_name="Alice",
            move_number=1,
            turn_order=["Alice"],
            next_proposal_id=301,
        )
        msg = builder.build_judge_veto_prompt(game_state=game_state)
        assert '- vote_mode: "unanimous"' in msg.content

    def test_veto_prompt_includes_supported_flags(self) -> None:
        """Judge veto prompt includes supported flag descriptions."""
        from src.nomic_engine.llm.prompt_builder import PromptBuilder

        builder = PromptBuilder()
        game_state = GameState(
            scores={"Alice": 0},
            current_player_name="Alice",
            move_number=1,
            turn_order=["Alice"],
            next_proposal_id=301,
        )
        msg = builder.build_judge_veto_prompt(game_state=game_state)
        assert "Supported Engine Capabilities" in msg.content
        assert "vote_mode (string)" in msg.content
        assert "Valid values: unanimous, majority" in msg.content

    def test_veto_prompt_includes_veto_criteria(self) -> None:
        """Judge veto prompt includes veto criteria."""
        from src.nomic_engine.llm.prompt_builder import PromptBuilder

        builder = PromptBuilder()
        game_state = GameState(
            scores={"Alice": 0},
            current_player_name="Alice",
            move_number=1,
            turn_order=["Alice"],
            next_proposal_id=301,
        )
        msg = builder.build_judge_veto_prompt(game_state=game_state)
        assert "engine capabilities" in msg.content

    def test_veto_prompt_without_game_state(self) -> None:
        """Veto prompt works without game_state (backward compat)."""
        from src.nomic_engine.llm.prompt_builder import PromptBuilder

        builder = PromptBuilder()
        msg = builder.build_judge_veto_prompt()
        assert "No flags currently set." in msg.content
        assert "Supported Engine Capabilities" in msg.content

    def test_veto_prompt_with_majority_mode(self) -> None:
        """Judge veto prompt reflects current game flag state."""
        from src.nomic_engine.llm.prompt_builder import PromptBuilder

        builder = PromptBuilder()
        game_state = GameState(
            scores={"Alice": 0},
            current_player_name="Alice",
            move_number=1,
            turn_order=["Alice"],
            next_proposal_id=301,
            flags={"vote_mode": "majority"},
        )
        msg = builder.build_judge_veto_prompt(game_state=game_state)
        assert '- vote_mode: "majority"' in msg.content


# =========================================================================
# 8. StateUpdates validation
# =========================================================================


class TestStateUpdatesValidation:
    """Tests for validating StateUpdates dictionaries."""

    def test_valid_empty_state_updates(self) -> None:
        """Empty StateUpdates is valid."""
        validate_state_updates({})

    def test_valid_flags_only(self) -> None:
        """StateUpdates with only flags is valid."""
        validate_state_updates({"flags": {"vote_mode": "majority"}})

    def test_valid_target_score_only(self) -> None:
        """StateUpdates with only target_score is valid."""
        validate_state_updates({"target_score": 100})

    def test_valid_both_fields(self) -> None:
        """StateUpdates with both fields is valid."""
        validate_state_updates(
            {"flags": {"vote_mode": "unanimous"}, "target_score": 50}
        )

    def test_valid_target_score_none(self) -> None:
        """StateUpdates with target_score=None is valid."""
        validate_state_updates({"target_score": None})

    def test_invalid_not_dict(self) -> None:
        """Non-dict StateUpdates raises ValueError."""
        with pytest.raises(ValueError, match="must be a dict"):
            validate_state_updates("not a dict")  # type: ignore[arg-type]

    def test_invalid_unexpected_key(self) -> None:
        """Unexpected keys allowed (TypedDict enforces at type-check)."""
        # This should not raise - TypedDict enforces keys at type-check time
        validate_state_updates(
            {"flags": {}, "extra_key": "value"}  # type: ignore[arg-type]
        )

    def test_invalid_flags_not_dict(self) -> None:
        """Non-dict flags raise ValueError."""
        with pytest.raises(ValueError, match="flags.*must be a dict"):
            validate_state_updates({"flags": "not a dict"})  # type: ignore[arg-type]

    def test_invalid_flag_value(self) -> None:
        """Invalid flag value raises ValueError."""
        with pytest.raises(ValueError, match="not valid"):
            validate_state_updates({"flags": {"vote_mode": "invalid"}})

    def test_invalid_unknown_flag(self) -> None:
        """Unknown flag name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown flag"):
            validate_state_updates({"flags": {"unknown_flag": "value"}})

    def test_invalid_target_score_not_int(self) -> None:
        """Non-int target_score raises ValueError."""
        with pytest.raises(ValueError, match="target_score.*must be int"):
            validate_state_updates({"target_score": "100"})  # type: ignore[arg-type]


# =========================================================================
# 9. majority_after_loops flag (nullable + min_value)
# =========================================================================


class TestMajorityAfterLoopsFlag:
    """Tests for the majority_after_loops flag schema validation."""

    def test_valid_positive_integer(self) -> None:
        """Positive integers are valid for majority_after_loops."""
        validate_flag_value("majority_after_loops", 1)
        validate_flag_value("majority_after_loops", 2)
        validate_flag_value("majority_after_loops", 10)

    def test_valid_null_value(self) -> None:
        """None is a valid value (nullable=true)."""
        validate_flag_value("majority_after_loops", None)

    def test_rejects_zero(self) -> None:
        """0 is below min_value=1 and must be rejected."""
        with pytest.raises(ValueError, match="below minimum"):
            validate_flag_value("majority_after_loops", 0)

    def test_rejects_negative_integer(self) -> None:
        """Negative integers are below min_value=1 and must be rejected."""
        with pytest.raises(ValueError, match="below minimum"):
            validate_flag_value("majority_after_loops", -5)

    def test_rejects_float(self) -> None:
        """Floats are rejected (type mismatch)."""
        with pytest.raises(ValueError, match="expects type"):
            validate_flag_value("majority_after_loops", 1.5)

    def test_rejects_string(self) -> None:
        """Strings are rejected (type mismatch)."""
        with pytest.raises(ValueError, match="expects type"):
            validate_flag_value("majority_after_loops", "2")

    def test_state_updates_accepts_null(self) -> None:
        """StateUpdates with majority_after_loops=null is valid."""
        validate_state_updates({"flags": {"majority_after_loops": None}})

    def test_state_updates_accepts_positive_integer(self) -> None:
        """StateUpdates with majority_after_loops=3 is valid."""
        validate_state_updates({"flags": {"majority_after_loops": 3}})

    def test_state_updates_rejects_zero(self) -> None:
        """StateUpdates with majority_after_loops=0 raises ValueError."""
        with pytest.raises(ValueError, match="below minimum"):
            validate_state_updates({"flags": {"majority_after_loops": 0}})

    def test_schema_contains_majority_after_loops(self) -> None:
        """Schema contains the majority_after_loops flag."""
        schema = load_flag_schema()
        assert "majority_after_loops" in schema
        defn = schema["majority_after_loops"]
        assert defn["type"] == "integer"
        assert defn["nullable"] is True
        assert defn["min_value"] == 1
        assert defn["default"] == 2

    def test_format_current_flags_renders_null(self) -> None:
        """format_current_flags renders None as null (not 'None')."""
        result = format_current_flags({"majority_after_loops": None})
        assert "- majority_after_loops: null" in result
        assert "None" not in result

    def test_format_current_flags_renders_integer(self) -> None:
        """format_current_flags renders integer values correctly."""
        result = format_current_flags({"majority_after_loops": 2})
        assert '- majority_after_loops: "2"' in result

    def test_format_supported_flags_shows_nullable_type(self) -> None:
        """format_supported_flags shows 'integer or null' for nullable flag."""
        result = format_supported_flags()
        assert "majority_after_loops (integer or null" in result

    def test_format_supported_flags_shows_min_value(self) -> None:
        """format_supported_flags includes min value constraint."""
        result = format_supported_flags()
        assert "min 1" in result

    def test_get_flag_defaults_includes_majority_after_loops(self) -> None:
        """get_flag_defaults includes majority_after_loops with default=2."""
        defaults = get_flag_defaults()
        assert "majority_after_loops" in defaults
        assert defaults["majority_after_loops"] == 2
