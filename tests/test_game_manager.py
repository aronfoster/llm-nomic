"""
Comprehensive unit tests for GameManager and GameLogger classes.

These tests validate loading, saving, and logging operations while ensuring
test isolation via temporary directories and files.
"""

import json
import tempfile
from pathlib import Path

import pytest
import yaml

from src.nomic_engine.constants import (
    CONFIG_FILE,
    GAME_LOG_FILE,
    GAME_STATE_FILE,
    GAME_TRANSCRIPT_FILE,
    RULES_JSONL_FILE,
    RULES_MD_FILE,
)
from src.nomic_engine.data_models import (
    GameState,
    Rule,
    RuleStatus,
)
from src.nomic_engine.game_logger import GameLogger
from src.nomic_engine.game_manager import GameManager

# --- Fixtures ---


@pytest.fixture
def temp_game_dir():
    """
    Fixture providing a temporary game directory with all required files.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        game_dir = Path(tmpdir)

        # Create config.yml
        config_data = {
            "players": [
                {"name": "Alice", "model_id": "claude-3-5-sonnet"},
                {"name": "Bob", "model_id": "gpt-4"},
            ]
        }
        config_path = game_dir / CONFIG_FILE
        with config_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(config_data, f)

        # Create game_state.json
        state_data = {
            "scores": {"Alice": 10, "Bob": 5},
            "current_player_name": "Alice",
            "move_number": 3,
            "turn_order": ["Alice", "Bob"],
            "next_proposal_id": 301,
        }
        state_path = game_dir / GAME_STATE_FILE
        with state_path.open("w", encoding="utf-8") as f:
            json.dump(state_data, f)

        # Create rules.jsonl
        rules = [
            {
                "rule_id": "101",
                "text": "All players must follow the rules.",
                "status": "immutable",
            },
            {
                "rule_id": "201",
                "text": "Players can propose rule changes.",
                "status": "mutable",
            },
        ]
        rules_path = game_dir / RULES_JSONL_FILE
        with rules_path.open("w", encoding="utf-8") as f:
            for rule in rules:
                f.write(json.dumps(rule) + "\n")

        # Create empty log files
        (game_dir / GAME_LOG_FILE).touch()
        (game_dir / GAME_TRANSCRIPT_FILE).touch()

        yield game_dir


@pytest.fixture
def sample_game_state():
    """Fixture providing a sample GameState object."""
    return GameState(
        scores={"Alice": 10, "Bob": 5},
        current_player_name="Alice",
        move_number=3,
        turn_order=["Alice", "Bob"],
        next_proposal_id=301,
    )


# --- Tests for GameLogger ---


def test_game_logger_init():
    """Test GameLogger initialization sets correct paths."""
    with tempfile.TemporaryDirectory() as tmpdir:
        game_dir = Path(tmpdir)
        logger = GameLogger(game_dir)

        assert logger.log_path == game_dir / GAME_LOG_FILE
        assert logger.transcript_path == game_dir / GAME_TRANSCRIPT_FILE


def test_game_logger_log_event():
    """Test logging an event to game_log.jsonl."""
    with tempfile.TemporaryDirectory() as tmpdir:
        game_dir = Path(tmpdir)
        log_path = game_dir / GAME_LOG_FILE
        log_path.touch()

        logger = GameLogger(game_dir)
        logger.log_event("move_start", {"player": "Alice", "move_number": 1})

        # Read back and verify
        with log_path.open("r", encoding="utf-8") as f:
            lines = f.readlines()

        assert len(lines) == 1
        event = json.loads(lines[0])

        assert "timestamp" in event
        assert event["event_type"] == "move_start"
        assert event["data"]["player"] == "Alice"
        assert event["data"]["move_number"] == 1


def test_game_logger_log_multiple_events():
    """Test logging multiple events appends to the log file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        game_dir = Path(tmpdir)
        log_path = game_dir / GAME_LOG_FILE
        log_path.touch()

        logger = GameLogger(game_dir)
        logger.log_event("event1", {"data": "first"})
        logger.log_event("event2", {"data": "second"})
        logger.log_event("event3", {"data": "third"})

        # Read back and verify
        with log_path.open("r", encoding="utf-8") as f:
            lines = f.readlines()

        assert len(lines) == 3

        event1 = json.loads(lines[0])
        event2 = json.loads(lines[1])
        event3 = json.loads(lines[2])

        assert event1["event_type"] == "event1"
        assert event2["event_type"] == "event2"
        assert event3["event_type"] == "event3"


def test_game_logger_log_transcript():
    """Test logging to game transcript."""
    with tempfile.TemporaryDirectory() as tmpdir:
        game_dir = Path(tmpdir)
        transcript_path = game_dir / GAME_TRANSCRIPT_FILE
        transcript_path.touch()

        logger = GameLogger(game_dir)
        logger.log_transcript("Player Alice made a proposal.")

        # Read back and verify
        with transcript_path.open("r", encoding="utf-8") as f:
            content = f.read()

        assert "####" in content  # Timestamp header
        assert "Player Alice made a proposal." in content


def test_game_logger_log_multiple_transcripts():
    """Test logging multiple transcript entries."""
    with tempfile.TemporaryDirectory() as tmpdir:
        game_dir = Path(tmpdir)
        transcript_path = game_dir / GAME_TRANSCRIPT_FILE
        transcript_path.touch()

        logger = GameLogger(game_dir)
        logger.log_transcript("First entry.")
        logger.log_transcript("Second entry.")

        # Read back and verify
        with transcript_path.open("r", encoding="utf-8") as f:
            content = f.read()

        assert "First entry." in content
        assert "Second entry." in content
        # Should have two timestamp headers
        assert content.count("####") == 2


# --- Tests for GameManager Initialization ---


def test_game_manager_init(temp_game_dir):
    """Test GameManager initialization sets correct paths and attributes."""
    manager = GameManager(temp_game_dir)

    assert manager.game_dir == temp_game_dir
    assert manager.config_path == temp_game_dir / CONFIG_FILE
    assert manager.game_state_path == temp_game_dir / GAME_STATE_FILE
    assert manager.rules_jsonl_path == temp_game_dir / RULES_JSONL_FILE
    assert manager.rules_md_path == temp_game_dir / RULES_MD_FILE

    assert isinstance(manager.logger, GameLogger)

    assert manager.game_config is None
    assert manager.game_state is None
    assert manager.rules_manager is None


def test_game_manager_init_with_string_path(temp_game_dir):
    """Test GameManager can be initialized with a string path."""
    manager = GameManager(str(temp_game_dir))

    assert manager.game_dir == temp_game_dir
    assert isinstance(manager.game_dir, Path)


# --- Tests for GameManager.load_game ---


def test_game_manager_load_game_success(temp_game_dir):
    """Test successful loading of all game files."""
    manager = GameManager(temp_game_dir)
    manager.load_game()

    # Verify config loaded
    assert manager.game_config is not None
    assert len(manager.game_config.players) == 2
    assert manager.game_config.players[0].name == "Alice"
    assert manager.game_config.players[1].name == "Bob"

    # Verify state loaded
    assert manager.game_state is not None
    assert manager.game_state.move_number == 3
    assert manager.game_state.current_player_name == "Alice"
    assert manager.game_state.scores["Alice"] == 10
    assert manager.game_state.scores["Bob"] == 5

    # Verify rules loaded
    assert manager.rules_manager is not None
    assert len(manager.rules_manager.rules) == 2
    assert manager.rules_manager.rules[0].rule_id == "101"
    assert manager.rules_manager.rules[1].rule_id == "201"


def test_game_manager_load_game_missing_config():
    """
    Test that load_game raises FileNotFoundError if config.yml
    is missing.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        game_dir = Path(tmpdir)
        # Create only some files, not config.yml
        (game_dir / GAME_STATE_FILE).write_text("{}")
        (game_dir / RULES_JSONL_FILE).touch()

        manager = GameManager(game_dir)

        with pytest.raises(FileNotFoundError):
            manager.load_game()


def test_game_manager_load_game_missing_state():
    """
    Test that load_game raises FileNotFoundError if game_state.json
    is missing.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        game_dir = Path(tmpdir)
        # Create only config.yml
        config_data = {"players": [{"name": "Alice", "model_id": "test"}]}
        config_path = game_dir / CONFIG_FILE
        with config_path.open("w") as f:
            yaml.safe_dump(config_data, f)

        manager = GameManager(game_dir)

        with pytest.raises(FileNotFoundError):
            manager.load_game()


def test_game_manager_load_game_missing_rules():
    """
    Test that load_game raises FileNotFoundError if rules.jsonl
    is missing.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        game_dir = Path(tmpdir)

        # Create config.yml
        config_data = {"players": [{"name": "Alice", "model_id": "test"}]}
        (game_dir / CONFIG_FILE).write_text(yaml.safe_dump(config_data))

        # Create game_state.json
        state_data = {
            "scores": {"Alice": 0},
            "current_player_name": "Alice",
            "move_number": 1,
            "turn_order": ["Alice"],
            "next_proposal_id": 301,
        }
        (game_dir / GAME_STATE_FILE).write_text(json.dumps(state_data))

        manager = GameManager(game_dir)

        with pytest.raises(FileNotFoundError):
            manager.load_game()


def test_game_manager_load_game_invalid_config():
    """Test that load_game raises ValidationError for invalid config data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        game_dir = Path(tmpdir)

        # Create invalid config.yml (missing required fields)
        config_data = {"invalid_field": "value"}
        (game_dir / CONFIG_FILE).write_text(yaml.safe_dump(config_data))

        # Create valid state and rules
        state_data = {
            "scores": {},
            "current_player_name": "Alice",
            "move_number": 1,
            "turn_order": [],
        }
        (game_dir / GAME_STATE_FILE).write_text(json.dumps(state_data))
        (game_dir / RULES_JSONL_FILE).touch()

        manager = GameManager(game_dir)

        with pytest.raises(Exception):  # pydantic.ValidationError
            manager.load_game()


def test_game_manager_load_game_invalid_state():
    """Test that load_game raises ValidationError for invalid state data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        game_dir = Path(tmpdir)

        # Create valid config.yml
        config_data = {"players": [{"name": "Alice", "model_id": "test"}]}
        (game_dir / CONFIG_FILE).write_text(yaml.safe_dump(config_data))

        # Create invalid game_state.json (missing required fields)
        state_data = {"invalid_field": "value"}
        (game_dir / GAME_STATE_FILE).write_text(json.dumps(state_data))

        (game_dir / RULES_JSONL_FILE).touch()

        manager = GameManager(game_dir)

        with pytest.raises(Exception):  # pydantic.ValidationError
            manager.load_game()


# --- Tests for GameManager.save_game_state ---


def test_game_manager_save_game_state_success(
    temp_game_dir, sample_game_state
):
    """Test successful saving of game state."""
    manager = GameManager(temp_game_dir)
    manager.game_state = sample_game_state

    manager.save_game_state()

    # Read back and verify
    state_path = temp_game_dir / GAME_STATE_FILE
    with state_path.open("r", encoding="utf-8") as f:
        saved_data = json.load(f)

    assert saved_data["move_number"] == 3
    assert saved_data["current_player_name"] == "Alice"
    assert saved_data["scores"]["Alice"] == 10
    assert saved_data["scores"]["Bob"] == 5


def test_game_manager_save_game_state_none_raises_error(temp_game_dir):
    """Test that save_game_state raises ValueError if game_state is None."""
    manager = GameManager(temp_game_dir)
    manager.game_state = None

    with pytest.raises(ValueError, match="game_state is None"):
        manager.save_game_state()


def test_game_manager_save_game_state_overwrites(
    temp_game_dir, sample_game_state
):
    """Test that save_game_state overwrites existing file."""
    manager = GameManager(temp_game_dir)

    # Save first state
    manager.game_state = sample_game_state
    manager.save_game_state()

    # Modify and save again
    manager.game_state.move_number = 10
    manager.game_state.scores["Alice"] = 100
    manager.save_game_state()

    # Read back and verify updated values
    state_path = temp_game_dir / GAME_STATE_FILE
    with state_path.open("r", encoding="utf-8") as f:
        saved_data = json.load(f)

    assert saved_data["move_number"] == 10
    assert saved_data["scores"]["Alice"] == 100


# --- Tests for GameManager.save_rules ---


def test_game_manager_save_rules_success(temp_game_dir):
    """Test successful saving of rules to both JSONL and Markdown."""
    manager = GameManager(temp_game_dir)
    manager.load_game()

    # Modify rules
    manager.rules_manager.rules.append(
        Rule(
            rule_id="301",
            text="New rule added for testing.",
            status=RuleStatus.MUTABLE,
        )
    )

    manager.save_rules()

    # Verify JSONL file
    jsonl_path = temp_game_dir / RULES_JSONL_FILE
    with jsonl_path.open("r", encoding="utf-8") as f:
        lines = f.readlines()

    assert len(lines) == 3
    rule3 = json.loads(lines[2])
    assert rule3["rule_id"] == "301"
    assert rule3["text"] == "New rule added for testing."

    # Verify Markdown file exists and contains the new rule
    md_path = temp_game_dir / RULES_MD_FILE
    assert md_path.exists()

    with md_path.open("r", encoding="utf-8") as f:
        md_content = f.read()

    assert "### 301 (M)" in md_content
    assert "New rule added for testing." in md_content


def test_game_manager_save_rules_none_raises_error(temp_game_dir):
    """Test that save_rules raises ValueError if rules_manager is None."""
    manager = GameManager(temp_game_dir)
    manager.rules_manager = None

    with pytest.raises(ValueError, match="rules_manager is None"):
        manager.save_rules()


# --- Integration Tests ---


def test_game_manager_full_lifecycle(temp_game_dir):
    """Test complete load-modify-save lifecycle."""
    # Load game
    manager = GameManager(temp_game_dir)
    manager.load_game()

    initial_move = manager.game_state.move_number
    initial_rules_count = len(manager.rules_manager.rules)

    # Modify state
    manager.game_state.move_number += 1
    manager.game_state.scores["Alice"] += 5

    # Modify rules
    manager.rules_manager.rules.append(
        Rule(
            rule_id="302",
            text="Integration test rule.",
            status=RuleStatus.MUTABLE,
        )
    )

    # Save everything
    manager.save_game_state()
    manager.save_rules()

    # Log events
    manager.logger.log_event("test_event", {"test": "data"})
    manager.logger.log_transcript("Integration test transcript entry.")

    # Create new manager and reload to verify persistence
    manager2 = GameManager(temp_game_dir)
    manager2.load_game()

    assert manager2.game_state.move_number == initial_move + 1
    assert manager2.game_state.scores["Alice"] == 15
    assert len(manager2.rules_manager.rules) == initial_rules_count + 1
    assert manager2.rules_manager.rules[-1].rule_id == "302"

    # Verify logs
    log_path = temp_game_dir / GAME_LOG_FILE
    with log_path.open("r", encoding="utf-8") as f:
        log_lines = f.readlines()

    assert len(log_lines) >= 1
    last_event = json.loads(log_lines[-1])
    assert last_event["event_type"] == "test_event"

    transcript_path = temp_game_dir / GAME_TRANSCRIPT_FILE
    with transcript_path.open("r", encoding="utf-8") as f:
        transcript_content = f.read()

    assert "Integration test transcript entry." in transcript_content
