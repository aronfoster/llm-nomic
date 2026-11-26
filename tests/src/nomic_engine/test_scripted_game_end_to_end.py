"""Offline end-to-end proof: a whole game runs through ``run_game``.

Every model call is answered by ``ScriptedApiClient``. No credentials,
network, or paid inference are involved. The test creates a real game
directory with ``create_game_files``, runs the real ``run_game`` entry
point (players, judge, turn loop, rule application, scoring, state
files), and checks the saved results on disk.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from src.nomic_engine.data_models import (
    GameState,
    JudgeType,
    ModelDefinition,
    ModelLibrary,
    PlayerConfig,
)
from src.nomic_engine.game_creator import (
    create_game_files,
    load_initial_rules,
)
from src.nomic_engine.main import run_game
from tests.scripted_client import ScriptedApiClient

SCRIPTED_MODEL = ModelDefinition(
    id="scripted-model",
    provider="openai",
    api_model_id="scripted-model",
    env_key_name="OPENAI_API_KEY",
)
PLAYERS = ["Ada", "Grace"]
TARGET_SCORE = 4
SCORE_DELTA = 3


def _make_game(game_dir: Path) -> None:
    create_game_files(
        game_dir=game_dir,
        players=[
            PlayerConfig(
                name=name, model_id="scripted-model", personality="none"
            )
            for name in PLAYERS
        ],
        initial_rules=load_initial_rules(),
        judge_type=JudgeType.LLM,
        judge_model=SCRIPTED_MODEL,
        target_score=TARGET_SCORE,
    )


def _run(
    game_dir: Path, max_turns: int | None
) -> tuple[Counter[str], Counter[str]]:
    """Run the game with scripted clients; return call counts."""
    player_calls: Counter[str] = Counter()
    judge_calls: Counter[str] = Counter()

    def fake_create_api_client(model_config: Any, **_: Any) -> Any:
        # Players and the judge both use "scripted-model"; the judge
        # module gets its own factory below so calls stay separable.
        return ScriptedApiClient(
            "player", score_delta=SCORE_DELTA, calls=player_calls
        )

    def fake_judge_client(model_config: Any, **_: Any) -> Any:
        return ScriptedApiClient(
            "judge", score_delta=SCORE_DELTA, calls=judge_calls
        )

    library = ModelLibrary(models=[SCRIPTED_MODEL])
    with (
        patch(
            "src.nomic_engine.main.load_model_library", return_value=library
        ),
        patch("src.nomic_engine.main.validate_startup"),
        patch(
            "src.nomic_engine.players.llm_player.create_api_client",
            fake_create_api_client,
        ),
        patch(
            "src.nomic_engine.judge.llm_judge.create_api_client",
            fake_judge_client,
        ),
    ):
        run_game(str(game_dir), max_turns=max_turns)
    return player_calls, judge_calls


def _load_state(game_dir: Path) -> GameState:
    return GameState.model_validate_json(
        (game_dir / "game_state.json").read_text(encoding="utf-8")
    )


def _rule_texts(game_dir: Path) -> list[str]:
    lines = (game_dir / "rules.jsonl").read_text(encoding="utf-8")
    return [
        json.loads(line)["text"] for line in lines.splitlines() if line.strip()
    ]


def test_scripted_game_runs_to_victory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    game_dir = tmp_path / "scripted-game"
    _make_game(game_dir)
    rules_before = len(_rule_texts(game_dir))

    player_calls, judge_calls = _run(game_dir, max_turns=10)

    out = capsys.readouterr().out
    state = _load_state(game_dir)

    # Ada and Grace alternate, each passed proposal scores 3, so Ada
    # reaches the target of 4 on the third turn (6 points) and wins.
    assert state.scores == {"Ada": 2 * SCORE_DELTA, "Grace": SCORE_DELTA}
    assert state.move_number >= 3
    assert "Ada" in out and "victory" in out.lower()

    # Three passed proposals each added one rule to rules.jsonl.
    new_rules = [t for t in _rule_texts(game_dir) if "Scripted rule" in t]
    assert len(new_rules) == 3
    assert len(_rule_texts(game_dir)) == rules_before + 3

    # Every phase of the engine was exercised, for players and judge.
    assert player_calls["propose"] == 3
    assert player_calls["vote"] >= 3
    assert player_calls["discuss"] >= 3
    assert judge_calls["judge_veto"] == 3
    assert judge_calls["judge_score"] == 3
    assert judge_calls["judge_maintain_state"] == 3


def test_scripted_game_is_resumable_from_saved_state(
    tmp_path: Path,
) -> None:
    """One turn, stop, restart: state on disk drives the next turn."""
    game_dir = tmp_path / "scripted-resume"
    _make_game(game_dir)

    _run(game_dir, max_turns=1)
    after_one = _load_state(game_dir)
    assert after_one.scores == {"Ada": SCORE_DELTA, "Grace": 0}
    assert after_one.current_player_name == "Grace"

    _run(game_dir, max_turns=10)
    final = _load_state(game_dir)
    assert final.scores == {"Ada": 2 * SCORE_DELTA, "Grace": SCORE_DELTA}
