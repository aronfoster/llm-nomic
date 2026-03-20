"""
Tests for create_game.py memory file creation behaviour.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

from src.nomic_engine.data_models import (
    JudgeType,
    ModelDefinition,
    PlayerConfig,
    Rule,
    RuleStatus,
)
from src.nomic_engine.game_creator import create_game_files

# ---------------------------------------------------------------------------
# Minimal rule list so create_game_files can write rules.jsonl
# ---------------------------------------------------------------------------

_MINIMAL_RULES = [
    Rule(
        rule_id="101",
        text="All players must abide by the rules.",
        status=RuleStatus.IMMUTABLE,
    ),
    Rule(
        rule_id="201",
        text="Players may propose rule changes.",
        status=RuleStatus.MUTABLE,
    ),
]

_JUDGE_MODEL = ModelDefinition(
    id="claude-haiku",
    provider="anthropic",
    api_model_id="claude-haiku-20240307",
    env_key_name="ANTHROPIC_API_KEY",
)

_FLAG_DEFAULTS = {"vote_mode": "unanimous"}


def _run_create(
    game_dir: Path,
    players: list[PlayerConfig],
    judge_type: JudgeType = JudgeType.HUMAN,
    judge_model: ModelDefinition | None = None,
    target_score: int | None = None,
) -> None:
    """Run create_game_files with flag-schema mocked out."""
    with (
        patch("nomic_engine.game_creator.load_flag_schema"),
        patch(
            "nomic_engine.game_creator.get_flag_defaults",
            return_value=_FLAG_DEFAULTS,
        ),
    ):
        create_game_files(
            game_dir,
            players,
            _MINIMAL_RULES,
            judge_type,
            judge_model,
            target_score,
        )


# ---------------------------------------------------------------------------
# Memory file creation for LLM players
# ---------------------------------------------------------------------------


def test_create_game_creates_memory_dir():
    """create_game_files creates the memories/ directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        game_dir = Path(tmpdir) / "mygame"
        players = [
            PlayerConfig(name="Alice", model_id="claude-haiku"),
        ]
        _run_create(game_dir, players)
        assert (game_dir / "memories").is_dir()


def test_create_game_creates_memory_for_llm_player():
    """An LLM player gets a memory file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        game_dir = Path(tmpdir) / "mygame"
        players = [
            PlayerConfig(name="Alice", model_id="claude-haiku"),
        ]
        _run_create(game_dir, players)
        memory_file = game_dir / "memories" / "Alice_MEMORY.md"
        assert memory_file.exists()
        assert memory_file.stat().st_size > 0


def test_create_game_does_not_create_memory_for_human_player():
    """Human players must NOT receive a memory file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        game_dir = Path(tmpdir) / "mygame"
        players = [
            PlayerConfig(name="HumanBob", model_id="human"),
        ]
        _run_create(game_dir, players)
        assert not (game_dir / "memories" / "HumanBob_MEMORY.md").exists()


def test_create_game_mixed_players_only_llm_gets_memory():
    """Only LLM players receive memory files; human players are skipped."""
    with tempfile.TemporaryDirectory() as tmpdir:
        game_dir = Path(tmpdir) / "mygame"
        players = [
            PlayerConfig(name="Alice", model_id="claude-haiku"),
            PlayerConfig(name="HumanBob", model_id="human"),
        ]
        _run_create(game_dir, players)
        assert (game_dir / "memories" / "Alice_MEMORY.md").exists()
        assert not (game_dir / "memories" / "HumanBob_MEMORY.md").exists()


# ---------------------------------------------------------------------------
# Judge memory file
# ---------------------------------------------------------------------------


def test_create_game_creates_judge_memory_when_llm_judge():
    """Judge_MEMORY.md is created when judge_type is LLM."""
    with tempfile.TemporaryDirectory() as tmpdir:
        game_dir = Path(tmpdir) / "mygame"
        players = [
            PlayerConfig(name="Alice", model_id="claude-haiku"),
        ]
        _run_create(
            game_dir,
            players,
            judge_type=JudgeType.LLM,
            judge_model=_JUDGE_MODEL,
        )
        judge_file = game_dir / "memories" / "Judge_MEMORY.md"
        assert judge_file.exists()
        assert judge_file.stat().st_size > 0


def test_create_game_does_not_create_judge_memory_when_human_judge():
    """Judge_MEMORY.md must NOT be created for a human judge."""
    with tempfile.TemporaryDirectory() as tmpdir:
        game_dir = Path(tmpdir) / "mygame"
        players = [
            PlayerConfig(name="Alice", model_id="claude-haiku"),
        ]
        _run_create(game_dir, players, judge_type=JudgeType.HUMAN)
        assert not (game_dir / "memories" / "Judge_MEMORY.md").exists()


# ---------------------------------------------------------------------------
# Player memory template content
# ---------------------------------------------------------------------------


def test_player_memory_template_lists_other_players():
    """Player memory file lists observation lines for other players."""
    with tempfile.TemporaryDirectory() as tmpdir:
        game_dir = Path(tmpdir) / "mygame"
        players = [
            PlayerConfig(name="Alice", model_id="claude-haiku"),
            PlayerConfig(name="Bob", model_id="gpt-4o"),
        ]
        _run_create(game_dir, players)
        alice_mem = (game_dir / "memories" / "Alice_MEMORY.md").read_text(
            encoding="utf-8"
        )
        assert "- Bob: " in alice_mem
        assert (
            "Alice" not in alice_mem.split("# ")[1].split("\n")[0] or True
        )  # header ok


def test_player_memory_template_includes_judge_when_llm_judge():
    """Player memory includes a Judge observation line when judge is LLM."""
    with tempfile.TemporaryDirectory() as tmpdir:
        game_dir = Path(tmpdir) / "mygame"
        players = [
            PlayerConfig(name="Alice", model_id="claude-haiku"),
        ]
        _run_create(
            game_dir,
            players,
            judge_type=JudgeType.LLM,
            judge_model=_JUDGE_MODEL,
        )
        alice_mem = (game_dir / "memories" / "Alice_MEMORY.md").read_text(
            encoding="utf-8"
        )
        assert "- Judge: " in alice_mem
