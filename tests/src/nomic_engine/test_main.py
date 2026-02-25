"""Unit tests for main.py instantiate_players and instantiate_judge."""

from unittest.mock import MagicMock, patch

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
