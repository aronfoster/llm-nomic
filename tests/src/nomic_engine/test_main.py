"""Unit tests for main.py instantiate_players and instantiate_judge."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from src.nomic_engine.data_models import (
    EngineTuningConfig,
    JudgeType,
    ModelDefinition,
    ModelLibrary,
)
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
    # Default: no flags → exactly one turn
    # ------------------------------------------------------------------

    def test_default_runs_one_turn(self) -> None:
        patchers, loop = self._patch_all([False])
        try:
            _run_main_with_argv(["--game_dir", "/fake"])
        finally:
            self._stop_all(patchers)
        assert loop.run_turn.call_count == 1

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
