"""Unit tests for main.py instantiate_players and instantiate_judge."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.nomic_engine.data_models import (
    EngineTuningConfig,
    JudgeType,
    ModelDefinition,
    ModelLibrary,
)
from src.nomic_engine.game_discovery import GameInfo
from src.nomic_engine.main import instantiate_judge, instantiate_players
from src.nomic_engine.memory.memory_manager import MemoryManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_model_library(model_id: str = "gpt-4o") -> ModelLibrary:
    model = ModelDefinition(
        id=model_id,
        provider="openai",
        api_model_id=model_id,
        env_key_name="OPENAI_API_KEY",
    )
    return ModelLibrary(models=[model])


def _player_config(
    name: str,
    model_id: str = "gpt-4o",
    personality: str = "friendly",
):
    cfg = MagicMock()
    cfg.name = name
    cfg.model_id = model_id
    cfg.personality = personality
    return cfg


def _make_game_manager(
    player_configs,
    judge_type: JudgeType = JudgeType.LLM,
    judge_model=None,
    memory_manager=None,
):
    game_config = MagicMock()
    game_config.players = player_configs
    game_config.judge_type = judge_type
    game_config.judge_model = judge_model or ModelDefinition(
        id="gpt-4o",
        provider="openai",
        api_model_id="gpt-4o",
        env_key_name="OPENAI_API_KEY",
    )
    game_config.tuning = EngineTuningConfig()

    manager = MagicMock()
    manager.game_config = game_config
    manager.memory_manager = memory_manager
    return manager


# ---------------------------------------------------------------------------
# instantiate_players tests
# ---------------------------------------------------------------------------


@patch("src.nomic_engine.players.llm_player.create_api_client")
def test_instantiate_players_passes_memory_manager_to_llm_player(
    mock_create_api_client,
):
    """instantiate_players passes memory_manager to each LLMPlayer."""
    mock_create_api_client.return_value = MagicMock()
    mock_memory_manager = MagicMock(spec=MemoryManager)

    player_configs = [_player_config("Alice", "gpt-4o")]
    manager = _make_game_manager(
        player_configs, memory_manager=mock_memory_manager
    )
    model_library = _make_model_library("gpt-4o")

    from src.nomic_engine.players.llm_player import LLMPlayer

    players = instantiate_players(manager, model_library)

    assert len(players) == 1
    assert isinstance(players[0], LLMPlayer)
    assert players[0].memory_manager is mock_memory_manager


@patch("src.nomic_engine.players.llm_player.create_api_client")
def test_instantiate_players_passes_none_memory_manager(
    mock_create_api_client,
):
    """instantiate_players passes None memory_manager gracefully."""
    mock_create_api_client.return_value = MagicMock()

    player_configs = [_player_config("Bob", "gpt-4o")]
    manager = _make_game_manager(player_configs, memory_manager=None)
    model_library = _make_model_library("gpt-4o")

    from src.nomic_engine.players.llm_player import LLMPlayer

    players = instantiate_players(manager, model_library)

    assert len(players) == 1
    assert isinstance(players[0], LLMPlayer)
    assert players[0].memory_manager is None


# ---------------------------------------------------------------------------
# instantiate_judge tests
# ---------------------------------------------------------------------------


@patch("src.nomic_engine.judge.llm_judge.create_api_client")
def test_instantiate_judge_passes_memory_manager_to_llm_judge(
    mock_create_api_client,
):
    """instantiate_judge passes memory_manager to LLMJudge."""
    mock_create_api_client.return_value = MagicMock()
    mock_memory_manager = MagicMock(spec=MemoryManager)

    manager = _make_game_manager([], memory_manager=mock_memory_manager)

    from src.nomic_engine.judge.llm_judge import LLMJudge

    judge = instantiate_judge(manager)

    assert isinstance(judge, LLMJudge)
    assert judge.memory_manager is mock_memory_manager


@patch("src.nomic_engine.judge.llm_judge.create_api_client")
def test_instantiate_judge_passes_none_memory_manager(
    mock_create_api_client,
):
    """instantiate_judge passes None memory_manager gracefully."""
    mock_create_api_client.return_value = MagicMock()

    manager = _make_game_manager([], memory_manager=None)

    from src.nomic_engine.judge.llm_judge import LLMJudge

    judge = instantiate_judge(manager)

    assert isinstance(judge, LLMJudge)
    assert judge.memory_manager is None


# ---------------------------------------------------------------------------
# Multi-turn CLI flag tests
# ---------------------------------------------------------------------------

# Shared patch targets for main() end-to-end tests
_PATCHES = [
    "src.nomic_engine.main.load_model_library",
    "src.nomic_engine.main.GameManager",
    "src.nomic_engine.main.instantiate_players",
    "src.nomic_engine.main.instantiate_judge",
    "src.nomic_engine.main.validate_startup",
    "src.nomic_engine.main.GameLoop",
    "src.nomic_engine.main.setup_logging",
]


def _run_main_with_argv(argv: list[str]) -> None:
    """Invoke main() with the given sys.argv."""
    from src.nomic_engine.main import main

    with patch.object(sys, "argv", ["nomic"] + argv):
        main()


def _make_game_loop_mock(run_turn_side_effects: list[bool]) -> MagicMock:
    """Return a mock GameLoop whose run_turn() yields the given booleans."""
    loop = MagicMock()
    loop.check_existing_victory.return_value = (False, [], 0)
    loop.run_turn.side_effect = run_turn_side_effects
    return loop


class TestMultiTurnFlags:
    """Tests for --turns and --until-victory CLI flags."""

    def _patch_all(
        self, run_turn_results: list[bool]
    ) -> tuple[list[MagicMock], MagicMock]:
        """Start all required patches and return (patchers, loop_mock)."""
        loop_mock = _make_game_loop_mock(run_turn_results)
        patchers = []
        mocks = {}
        for target in _PATCHES:
            p = patch(target)
            m = p.start()
            patchers.append(p)
            mocks[target] = m

        # Wire GameLoop() constructor to return our loop_mock
        mocks["src.nomic_engine.main.GameLoop"].return_value = loop_mock
        # load_model_library returns a trivial object
        mocks["src.nomic_engine.main.load_model_library"].return_value = (
            MagicMock()
        )
        # GameManager().game_config.players = []
        gm = MagicMock()
        gm.game_config.players = []
        mocks["src.nomic_engine.main.GameManager"].return_value = gm
        # instantiate_players / judge return lists/objects
        mocks["src.nomic_engine.main.instantiate_players"].return_value = [
            MagicMock()
        ]
        mocks["src.nomic_engine.main.instantiate_judge"].return_value = (
            MagicMock()
        )
        return patchers, loop_mock

    def _stop_all(self, patchers: list[MagicMock]) -> None:
        for p in patchers:
            p.stop()

    # ------------------------------------------------------------------
    # Default: no flags → continuous loop until victory
    # ------------------------------------------------------------------

    def test_default_runs_continuous_until_victory(self) -> None:
        """Without flags, the loop runs continuously until victory."""
        patchers, loop = self._patch_all([False, False, True])
        try:
            _run_main_with_argv(["--game_dir", "/fake"])
        finally:
            self._stop_all(patchers)
        assert loop.run_turn.call_count == 3

    def test_default_does_not_stop_after_one_turn(self) -> None:
        """Without flags, the loop does NOT stop after a single non-victory
        turn."""
        patchers, loop = self._patch_all([False, True])
        try:
            _run_main_with_argv(["--game_dir", "/fake"])
        finally:
            self._stop_all(patchers)
        assert loop.run_turn.call_count == 2

    # ------------------------------------------------------------------
    # --turns N
    # ------------------------------------------------------------------

    def test_turns_runs_n_turns(self) -> None:
        patchers, loop = self._patch_all([False, False, False])
        try:
            _run_main_with_argv(["--game_dir", "/fake", "--turns", "3"])
        finally:
            self._stop_all(patchers)
        assert loop.run_turn.call_count == 3

    def test_turns_stops_early_on_victory(self) -> None:
        # Victory on turn 2 of 5 requested turns
        patchers, loop = self._patch_all([False, True])
        try:
            _run_main_with_argv(["--game_dir", "/fake", "--turns", "5"])
        finally:
            self._stop_all(patchers)
        assert loop.run_turn.call_count == 2

    def test_turns_one_is_valid(self) -> None:
        patchers, loop = self._patch_all([False])
        try:
            _run_main_with_argv(["--game_dir", "/fake", "--turns", "1"])
        finally:
            self._stop_all(patchers)
        assert loop.run_turn.call_count == 1

    def test_turns_zero_is_rejected(self) -> None:
        patchers, loop = self._patch_all([])
        try:
            with pytest.raises(SystemExit) as exc_info:
                _run_main_with_argv(["--game_dir", "/fake", "--turns", "0"])
            assert exc_info.value.code != 0
        finally:
            self._stop_all(patchers)
        loop.run_turn.assert_not_called()

    def test_turns_negative_is_rejected(self) -> None:
        patchers, loop = self._patch_all([])
        try:
            with pytest.raises(SystemExit) as exc_info:
                _run_main_with_argv(["--game_dir", "/fake", "--turns", "-3"])
            assert exc_info.value.code != 0
        finally:
            self._stop_all(patchers)
        loop.run_turn.assert_not_called()

    def test_turns_non_integer_is_rejected(self) -> None:
        patchers, loop = self._patch_all([])
        try:
            with pytest.raises(SystemExit) as exc_info:
                _run_main_with_argv(["--game_dir", "/fake", "--turns", "abc"])
            assert exc_info.value.code != 0
        finally:
            self._stop_all(patchers)
        loop.run_turn.assert_not_called()

    # ------------------------------------------------------------------
    # --until-victory
    # ------------------------------------------------------------------

    def test_until_victory_runs_until_game_over(self) -> None:
        # 4 turns before victory
        patchers, loop = self._patch_all([False, False, False, True])
        try:
            _run_main_with_argv(["--game_dir", "/fake", "--until-victory"])
        finally:
            self._stop_all(patchers)
        assert loop.run_turn.call_count == 4

    # ------------------------------------------------------------------
    # Mutually exclusive
    # ------------------------------------------------------------------

    def test_turns_and_until_victory_together_is_an_error(self) -> None:
        patchers, loop = self._patch_all([])
        try:
            with pytest.raises(SystemExit) as exc_info:
                _run_main_with_argv(
                    [
                        "--game_dir",
                        "/fake",
                        "--turns",
                        "3",
                        "--until-victory",
                    ]
                )
            assert exc_info.value.code != 0
        finally:
            self._stop_all(patchers)
        loop.run_turn.assert_not_called()

    # ------------------------------------------------------------------
    # Error in turn stops immediately
    # ------------------------------------------------------------------

    def test_error_in_turn_stops_immediately(self) -> None:
        patchers, loop = self._patch_all([])
        loop.run_turn.side_effect = [False, RuntimeError("boom")]
        try:
            with pytest.raises(SystemExit) as exc_info:
                _run_main_with_argv(["--game_dir", "/fake", "--turns", "5"])
            assert exc_info.value.code == 1
        finally:
            self._stop_all(patchers)
        # Only 2 calls: first succeeded, second raised
        assert loop.run_turn.call_count == 2

    def test_budget_stop_exits_nonzero_and_saves_partial_state(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A budget stop saves state, prints the report, and exits 2."""
        import src.nomic_engine.main as main_mod
        from src.nomic_engine.usage_budget import UsageBudgetExceeded

        patchers, loop = self._patch_all([])
        loop.run_turn.side_effect = UsageBudgetExceeded(
            "Usage budget exceeded: max_calls_per_game=1 already used. "
            "Refusing the next provider call.",
            limit_name="max_calls_per_game",
        )
        log_path = tmp_path / "token_usage.jsonl"
        rows = [
            {
                "move_number": 1,
                "usage_available": False,
                "input_tokens": None,
                "output_tokens": None,
                "error_kind": "quota",
            },
            {
                "move_number": 1,
                "usage_available": True,
                "input_tokens": 0,
                "output_tokens": 0,
                "finish_reason": "stop",
            },
        ]
        log_path.write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n",
            encoding="utf-8",
        )
        game_manager = main_mod.GameManager.return_value
        game_manager.token_usage_path = log_path
        try:
            with pytest.raises(SystemExit) as exc_info:
                _run_main_with_argv(["--game_dir", "/fake", "--turns", "3"])
            assert exc_info.value.code == 3
        finally:
            self._stop_all(patchers)

        assert loop.run_turn.call_count == 1
        game_manager.save_game_state.assert_called_once()
        game_manager.save_rules.assert_called_once()
        output = capsys.readouterr().out
        assert "Usage budget exceeded" in output
        assert "The next provider call was not made" in output
        assert "calls_with_unavailable_usage: 1" in output
        assert "calls_with_zero_tokens: 1" in output
        assert "not counted as zero" in output


# ---------------------------------------------------------------------------
# Interactive menu tests
# ---------------------------------------------------------------------------

_MENU_PATCHES = [
    "src.nomic_engine.main.load_model_library",
    "src.nomic_engine.main.GameManager",
    "src.nomic_engine.main.instantiate_players",
    "src.nomic_engine.main.instantiate_judge",
    "src.nomic_engine.main.validate_startup",
    "src.nomic_engine.main.GameLoop",
    "src.nomic_engine.main.setup_logging",
]


def _make_fake_game_info(name: str = "mygame") -> GameInfo:
    return GameInfo(
        display_name=name,
        path=Path(f"/fake/games/{name}"),
        turn_number=3,
        current_player="Alice",
        is_complete=False,
    )


class TestInteractiveMenu:
    """Tests for the interactive console menu (no --game_dir)."""

    def _start_patches(self) -> tuple[list, dict]:
        patchers = []
        mocks: dict = {}
        for target in _MENU_PATCHES:
            p = patch(target)
            m = p.start()
            patchers.append(p)
            mocks[target] = m

        loop_mock = MagicMock()
        loop_mock.check_existing_victory.return_value = (False, [], 0)
        loop_mock.run_turn.return_value = False
        mocks["src.nomic_engine.main.GameLoop"].return_value = loop_mock

        mocks["src.nomic_engine.main.load_model_library"].return_value = (
            MagicMock()
        )
        gm = MagicMock()
        gm.game_config.players = []
        mocks["src.nomic_engine.main.GameManager"].return_value = gm
        mocks["src.nomic_engine.main.instantiate_players"].return_value = [
            MagicMock()
        ]
        mocks["src.nomic_engine.main.instantiate_judge"].return_value = (
            MagicMock()
        )
        return patchers, mocks

    def _stop_all(self, patchers: list) -> None:
        for p in patchers:
            p.stop()

    def test_no_game_dir_shows_menu_then_quit(self, capsys) -> None:
        """Without --game_dir, the menu is shown; option 3 exits cleanly."""
        patchers, _ = self._start_patches()
        try:
            with patch("builtins.input", return_value="3"):
                with pytest.raises(SystemExit) as exc_info:
                    _run_main_with_argv([])
                assert exc_info.value.code == 0
        finally:
            self._stop_all(patchers)
        out = capsys.readouterr().out
        assert "Main Menu" in out

    def test_quit_exits_zero(self, capsys) -> None:
        """Selecting 'Quit' exits with code 0."""
        patchers, _ = self._start_patches()
        try:
            with patch("builtins.input", return_value="3"):
                with pytest.raises(SystemExit) as exc_info:
                    _run_main_with_argv([])
                assert exc_info.value.code == 0
        finally:
            self._stop_all(patchers)

    def test_continue_game_no_games_prints_message(self, capsys) -> None:
        """Continue a game with no games prints a message, returns to menu."""
        patchers, _ = self._start_patches()
        # First input picks option 1, second picks option 3 (Quit)
        inputs = iter(["1", "3"])
        try:
            with patch(
                "src.nomic_engine.main.discover_games", return_value=[]
            ):
                with patch("builtins.input", side_effect=inputs):
                    with pytest.raises(SystemExit) as exc_info:
                        _run_main_with_argv([])
                    assert exc_info.value.code == 0
        finally:
            self._stop_all(patchers)
        out = capsys.readouterr().out
        assert "No existing games found" in out

    def test_continue_game_selects_and_runs(self) -> None:
        """'Continue a game' with a game listed runs that game."""
        patchers, mocks = self._start_patches()
        game = _make_fake_game_info("mygame")
        # inputs: pick option 1, select game 1, then quit
        inputs = iter(["1", "1", "3"])
        loop_mock = mocks["src.nomic_engine.main.GameLoop"].return_value
        loop_mock.run_turn.return_value = False
        try:
            with patch(
                "src.nomic_engine.main.discover_games", return_value=[game]
            ):
                with patch("builtins.input", side_effect=inputs):
                    with pytest.raises(SystemExit) as exc_info:
                        _run_main_with_argv(["--turns", "1"])
                    assert exc_info.value.code == 0
        finally:
            self._stop_all(patchers)
        assert loop_mock.run_turn.call_count == 1

    def test_new_game_decline_to_play(self, capsys) -> None:
        """'New game' flow: create game, decline to play, return to menu."""
        patchers, _ = self._start_patches()
        fake_dir = Path("/fake/games/newgame")
        # inputs: option 2, then "n" for play now, then option 3 to quit
        inputs = iter(["2", "n", "3"])
        try:
            with patch(
                "src.nomic_engine.main.run_creation_flow",
                return_value=fake_dir,
            ):
                with patch("builtins.input", side_effect=inputs):
                    with pytest.raises(SystemExit) as exc_info:
                        _run_main_with_argv([])
                    assert exc_info.value.code == 0
        finally:
            self._stop_all(patchers)

    def test_new_game_play_immediately(self) -> None:
        """'New game' flow: create game, choose to play, game runs."""
        patchers, mocks = self._start_patches()
        fake_dir = Path("/fake/games/newgame")
        loop_mock = mocks["src.nomic_engine.main.GameLoop"].return_value
        loop_mock.run_turn.return_value = False
        # inputs: option 2, "y" to play now, then option 3 to quit
        inputs = iter(["2", "y", "3"])
        try:
            with patch(
                "src.nomic_engine.main.run_creation_flow",
                return_value=fake_dir,
            ):
                with patch("builtins.input", side_effect=inputs):
                    with pytest.raises(SystemExit) as exc_info:
                        _run_main_with_argv(["--turns", "1"])
                    assert exc_info.value.code == 0
        finally:
            self._stop_all(patchers)
        assert loop_mock.run_turn.call_count == 1

    def test_game_dir_bypasses_menu(self) -> None:
        """--game_dir bypasses the menu and runs the game directly."""
        patchers, mocks = self._start_patches()
        loop_mock = mocks["src.nomic_engine.main.GameLoop"].return_value
        loop_mock.run_turn.return_value = False
        try:
            # No SystemExit expected — run_game returns normally
            with patch("builtins.input") as mock_input:
                _run_main_with_argv(["--game_dir", "/fake", "--turns", "1"])
                mock_input.assert_not_called()
        finally:
            self._stop_all(patchers)
        assert loop_mock.run_turn.call_count == 1

    def test_invalid_menu_option_loops(self, capsys) -> None:
        """Invalid menu input loops back to the menu prompt."""
        patchers, _ = self._start_patches()
        # Enter invalid option, then quit
        inputs = iter(["9", "3"])
        try:
            with patch("builtins.input", side_effect=inputs):
                with pytest.raises(SystemExit) as exc_info:
                    _run_main_with_argv([])
                assert exc_info.value.code == 0
        finally:
            self._stop_all(patchers)
        out = capsys.readouterr().out
        assert "Invalid option" in out

    def test_continue_game_back_returns_to_menu(self, capsys) -> None:
        """Entering 0 in game selection returns to the main menu."""
        patchers, _ = self._start_patches()
        game = _make_fake_game_info("mygame")
        # inputs: option 1, then 0 (back), then quit
        inputs = iter(["1", "0", "3"])
        try:
            with patch(
                "src.nomic_engine.main.discover_games", return_value=[game]
            ):
                with patch("builtins.input", side_effect=inputs):
                    with pytest.raises(SystemExit) as exc_info:
                        _run_main_with_argv([])
                    assert exc_info.value.code == 0
        finally:
            self._stop_all(patchers)
