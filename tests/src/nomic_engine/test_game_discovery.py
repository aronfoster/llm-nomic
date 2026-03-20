"""
Unit tests for the game_discovery module.

Coverage:
- empty GAMES_DIR (directory exists but has no sub-directories)
- multiple valid game directories
- mixed valid/invalid directories (missing config.yml or game_state.json)
- GAMES_DIR absent (does not exist at all)
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.nomic_engine.game_discovery import GameInfo, discover_games

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(
    move_number: int = 1,
    current_player_name: str = "Alice",
    scores: dict[str, int] | None = None,
    target_score: int | None = None,
) -> dict:
    return {
        "move_number": move_number,
        "current_player_name": current_player_name,
        "scores": scores if scores is not None else {"Alice": 0},
        "target_score": target_score,
    }


def _write_files(
    game_dir: Path,
    include_config: bool = True,
    include_state: bool = True,
    state: dict | None = None,
) -> None:
    game_dir.mkdir(parents=True, exist_ok=True)
    if include_config:
        (game_dir / "config.yml").write_text("players: []\n", encoding="utf-8")
    if include_state:
        data = state if state is not None else _make_state()
        (game_dir / "game_state.json").write_text(
            json.dumps(data), encoding="utf-8"
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDiscoverGamesAbsent:
    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        result = discover_games(tmp_path / "nonexistent")
        assert result == []


class TestDiscoverGamesEmpty:
    def test_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        result = discover_games(games_dir)
        assert result == []


class TestDiscoverGamesValid:
    def test_single_valid_game(self, tmp_path: Path) -> None:
        games_dir = tmp_path / "games"
        _write_files(
            games_dir / "my_game",
            state=_make_state(
                move_number=5,
                current_player_name="Bob",
                scores={"Bob": 10},
            ),
        )
        result = discover_games(games_dir)
        assert len(result) == 1
        info = result[0]
        assert isinstance(info, GameInfo)
        assert info.display_name == "my_game"
        assert info.path == games_dir / "my_game"
        assert info.turn_number == 5
        assert info.current_player == "Bob"
        assert info.is_complete is False

    def test_multiple_valid_games_sorted(self, tmp_path: Path) -> None:
        games_dir = tmp_path / "games"
        for name in ("bravo", "alpha", "charlie"):
            _write_files(games_dir / name)
        result = discover_games(games_dir)
        names = [g.display_name for g in result]
        assert names == ["alpha", "bravo", "charlie"]

    def test_game_metadata_turn_and_player(self, tmp_path: Path) -> None:
        games_dir = tmp_path / "games"
        _write_files(
            games_dir / "game1",
            state=_make_state(
                move_number=3,
                current_player_name="Carol",
                scores={"Carol": 0, "Dave": 0},
            ),
        )
        result = discover_games(games_dir)
        assert result[0].turn_number == 3
        assert result[0].current_player == "Carol"


class TestDiscoverGamesCompletion:
    def test_game_not_complete_no_target(self, tmp_path: Path) -> None:
        games_dir = tmp_path / "games"
        _write_files(
            games_dir / "g",
            state=_make_state(
                scores={"Alice": 200},
                target_score=None,
            ),
        )
        result = discover_games(games_dir)
        assert result[0].is_complete is False

    def test_game_not_complete_below_target(self, tmp_path: Path) -> None:
        games_dir = tmp_path / "games"
        _write_files(
            games_dir / "g",
            state=_make_state(
                scores={"Alice": 50},
                target_score=100,
            ),
        )
        result = discover_games(games_dir)
        assert result[0].is_complete is False

    def test_game_complete_at_target(self, tmp_path: Path) -> None:
        games_dir = tmp_path / "games"
        _write_files(
            games_dir / "g",
            state=_make_state(
                scores={"Alice": 100},
                target_score=100,
            ),
        )
        result = discover_games(games_dir)
        assert result[0].is_complete is True

    def test_game_complete_above_target(self, tmp_path: Path) -> None:
        games_dir = tmp_path / "games"
        _write_files(
            games_dir / "g",
            state=_make_state(
                scores={"Alice": 120},
                target_score=100,
            ),
        )
        result = discover_games(games_dir)
        assert result[0].is_complete is True


class TestDiscoverGamesMixedValidity:
    def test_missing_config_skipped(self, tmp_path: Path) -> None:
        games_dir = tmp_path / "games"
        _write_files(games_dir / "no_config", include_config=False)
        _write_files(games_dir / "valid_game")
        result = discover_games(games_dir)
        assert len(result) == 1
        assert result[0].display_name == "valid_game"

    def test_missing_state_skipped(self, tmp_path: Path) -> None:
        games_dir = tmp_path / "games"
        _write_files(games_dir / "no_state", include_state=False)
        _write_files(games_dir / "valid_game")
        result = discover_games(games_dir)
        assert len(result) == 1
        assert result[0].display_name == "valid_game"

    def test_missing_both_files_skipped(self, tmp_path: Path) -> None:
        games_dir = tmp_path / "games"
        _write_files(
            games_dir / "empty_game",
            include_config=False,
            include_state=False,
        )
        result = discover_games(games_dir)
        assert result == []

    def test_non_directory_entries_skipped(self, tmp_path: Path) -> None:
        games_dir = tmp_path / "games"
        games_dir.mkdir()
        (games_dir / "some_file.txt").write_text("data", encoding="utf-8")
        _write_files(games_dir / "valid_game")
        result = discover_games(games_dir)
        assert len(result) == 1
        assert result[0].display_name == "valid_game"

    def test_mix_of_valid_and_invalid(self, tmp_path: Path) -> None:
        games_dir = tmp_path / "games"
        _write_files(games_dir / "good1")
        _write_files(games_dir / "good2")
        _write_files(games_dir / "bad_no_config", include_config=False)
        _write_files(games_dir / "bad_no_state", include_state=False)
        result = discover_games(games_dir)
        assert sorted(g.display_name for g in result) == ["good1", "good2"]


class TestDiscoverGamesDefaultDir:
    def test_uses_default_games_dir(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """discover_games() with no argument falls back to GAMES_DIR."""
        import src.nomic_engine.game_discovery as gd

        with tempfile.TemporaryDirectory() as tmp:
            fake_dir = Path(tmp) / "games"
            _write_files(
                fake_dir / "demo",
                state=_make_state(move_number=7, current_player_name="Eve"),
            )
            monkeypatch.setattr(gd, "GAMES_DIR", str(fake_dir))
            result = discover_games()
        assert len(result) == 1
        assert result[0].display_name == "demo"
        assert result[0].turn_number == 7
