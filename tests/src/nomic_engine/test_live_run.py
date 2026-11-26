"""Offline proof of the one-command bounded live run (LN-14).

The "grok" executable is a wrapper around ``fake_grok_game_cli.py``, so
the real ``live_run`` entry, ``GrokCliApiClient``, adapter (subprocess,
env allowlist, caps) and usage guard all run. No sign-in, network or
paid call is involved.
"""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

from src.nomic_engine import live_run
from src.nomic_engine.data_models import GameState, ModelDefinition
from src.nomic_engine.llm.api_clients import create_api_client

_FAKE = Path(__file__).resolve().parents[2] / "fixtures"
_FAKE = _FAKE / "fake_grok_game_cli.py"


def _grok(tmp_path: Path, *fake_flags: str) -> Path:
    wrapper = tmp_path / "grok"
    flags = " ".join(fake_flags)
    wrapper.write_text(
        f'#!/bin/sh\nexec {sys.executable} {_FAKE} {flags} "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
    return wrapper


def _signed_in_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    (home / ".grok").mkdir(parents=True)
    (home / ".grok" / "session.json").write_text("{}", encoding="utf-8")
    return home


def _args(tmp_path: Path, grok: Path, *extra: str) -> list[str]:
    return [
        "grok-cli",
        "--grok-path",
        str(grok),
        "--home",
        str(tmp_path / "home"),
        "--games-dir",
        str(tmp_path / "games"),
        *extra,
    ]


def _only_game(tmp_path: Path) -> Path:
    games = list((tmp_path / "games").iterdir())
    assert len(games) == 1
    return games[0]


def _state(game_dir: Path) -> GameState:
    return GameState.model_validate_json(
        (game_dir / "game_state.json").read_text(encoding="utf-8")
    )


def test_dry_run_creates_nothing_and_spawns_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "calls.jsonl"
    grok = _grok(tmp_path, "--log", str(log))
    code = live_run.main([*_args(tmp_path, grok), "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Dry run: nothing was created" in out
    assert "login --device-auth" in out
    assert "--max-turns" not in out and "--always-approve" not in out
    assert not (tmp_path / "games").exists()
    assert not (tmp_path / "home").exists()
    assert not log.exists()


def test_live_run_is_refused_without_the_acknowledgement(
    tmp_path: Path,
) -> None:
    _signed_in_home(tmp_path)
    log = tmp_path / "calls.jsonl"
    grok = _grok(tmp_path, "--log", str(log))
    assert live_run.main(_args(tmp_path, grok)) == live_run.EXIT_REFUSED
    assert not log.exists()
    assert not (tmp_path / "games").exists()


def test_live_run_is_refused_when_not_signed_in(tmp_path: Path) -> None:
    log = tmp_path / "calls.jsonl"
    grok = _grok(tmp_path, "--log", str(log))
    code = live_run.main(
        [
            *_args(tmp_path, grok),
            "--acknowledge-unverified-tool-isolation",
        ]
    )
    assert code == live_run.EXIT_REFUSED
    assert not log.exists()
    assert not (tmp_path / "games").exists()


def test_the_real_home_and_a_relative_cli_path_are_refused(
    tmp_path: Path,
) -> None:
    grok = _grok(tmp_path)
    real = ["--home", str(Path.home())]
    base = ["grok-cli", "--grok-path", str(grok), "--dry-run"]
    assert live_run.main([*base, *real]) == live_run.EXIT_REFUSED
    relative = ["grok-cli", "--grok-path", "grok", "--dry-run"]
    assert live_run.main(relative) == live_run.EXIT_REFUSED


def test_bounded_game_runs_to_victory_on_the_cli_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _signed_in_home(tmp_path)
    log = tmp_path / "calls.jsonl"
    grok = _grok(tmp_path, "--log", str(log))
    code = live_run.main(
        [
            *_args(tmp_path, grok),
            "--acknowledge-unverified-tool-isolation",
            "--target-score",
            "4",
            "--turns",
            "10",
            "--max-calls",
            "200",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    game_dir = _only_game(tmp_path)
    assert _state(game_dir).scores == {"Ada": 6, "Grace": 3}
    assert "victory" in out.lower()

    config = (game_dir / "config.yml").read_text(encoding="utf-8")
    assert "max_calls_per_game: 200" in config
    assert "max_total_tokens_per_game: 200000" in config

    calls = [json.loads(x) for x in log.read_text().splitlines()]
    phases = {c["phase"] for c in calls}
    assert {"propose", "vote", "judge_score"} <= phases
    first = calls[0]
    # Dedicated home, allowlisted env, no keys, no tool-approval flags.
    assert first["home"] == str(tmp_path / "home")
    assert not any("API_KEY" in key for key in first["env_keys"])
    flat = " ".join(first["argv"])
    for forbidden in ("--always-approve", "--yolo", "--max-turns"):
        assert forbidden not in flat
    # The factory is closed again once the run is over.
    model = ModelDefinition(
        id="grok-cli",
        provider="grok_cli",
        api_model_id="default",
        env_key_name=None,
    )
    with pytest.raises(ValueError, match="disabled in the game factory"):
        create_api_client(model)


def test_call_cap_stops_the_run_before_the_next_call(
    tmp_path: Path,
) -> None:
    _signed_in_home(tmp_path)
    log = tmp_path / "calls.jsonl"
    grok = _grok(tmp_path, "--log", str(log))
    with pytest.raises(SystemExit) as stopped:
        live_run.main(
            [
                *_args(tmp_path, grok),
                "--acknowledge-unverified-tool-isolation",
                "--max-calls",
                "3",
            ]
        )
    assert stopped.value.code == 3
    assert len(log.read_text().splitlines()) == 3


def test_missing_usage_stops_a_token_capped_run(tmp_path: Path) -> None:
    _signed_in_home(tmp_path)
    log = tmp_path / "calls.jsonl"
    grok = _grok(tmp_path, "--no-usage", "--log", str(log))
    with pytest.raises(SystemExit) as stopped:
        live_run.main(
            [
                *_args(tmp_path, grok),
                "--acknowledge-unverified-tool-isolation",
            ]
        )
    assert stopped.value.code == 3
    assert len(log.read_text().splitlines()) == 1


def test_allow_missing_usage_leaves_only_the_call_cap(
    tmp_path: Path,
) -> None:
    _signed_in_home(tmp_path)
    log = tmp_path / "calls.jsonl"
    grok = _grok(tmp_path, "--no-usage", "--log", str(log))
    with pytest.raises(SystemExit) as stopped:
        live_run.main(
            [
                *_args(tmp_path, grok),
                "--acknowledge-unverified-tool-isolation",
                "--allow-missing-usage",
                "--max-calls",
                "5",
            ]
        )
    assert stopped.value.code == 3
    assert len(log.read_text().splitlines()) == 5
    config = (_only_game(tmp_path) / "config.yml").read_text()
    assert "max_total_tokens_per_game: null" in config
