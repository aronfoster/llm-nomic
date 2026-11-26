"""Offline proof of the bounded ChatGPT-plan live run.

Sign-in runs against ``tests/fake_chatgpt_auth.py``. Responses calls go
to an ``httpx.MockTransport`` that answers like the Responses SSE stream
using the scripted game replies. The real ``live_run`` entry, token
provider, ``OpenAIChatGptPlanApiClient`` and usage guard all run. No
socket, sign-in or paid call is involved.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import pytest

from src.nomic_engine import live_run
from src.nomic_engine.data_models import ChatMessage, GameState
from src.nomic_engine.llm import api_clients
from src.nomic_engine.llm import chatgpt_oauth as oauth
from tests.fake_chatgpt_auth import FakeAuthServer
from tests.scripted_client import ScriptedApiClient

_REAL_CLIENT = httpx.Client


def _signed_in(config_dir: Path) -> oauth.ChatGptCredential:
    fake = FakeAuthServer()
    return oauth.sign_in(
        oauth.CredentialStore(config_dir),
        endpoints=fake.endpoints,
        http=_REAL_CLIENT(transport=fake.transport),
        open_browser=fake.authorize,
        port=0,
        timeout_seconds=5,
        notify=lambda _m: None,
        listener_factory=fake.listener_factory,
    )


class FakeResponses:
    """Responses API stand-in that plays the scripted game."""

    def __init__(self, *, usage: bool = True) -> None:
        self.usage = usage
        self.bodies: list[dict[str, Any]] = []
        self.auth: list[str] = []
        self.phases: Counter[str] = Counter()
        self._player = ScriptedApiClient("player", score_delta=3)
        self._judge = ScriptedApiClient("judge", score_delta=3)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.openai.com/v1/responses"
        body = json.loads(request.content)
        self.bodies.append(body)
        self.auth.append(request.headers["authorization"])
        messages = [ChatMessage(role="system", content=body["instructions"])]
        messages += [ChatMessage(**m) for m in body["input"]]
        phase = ScriptedApiClient.phase_of(messages[-1].content)
        self.phases[phase] += 1
        scripted = self._judge if phase.startswith("judge") else self._player
        text = scripted.get_completion(messages).text or ""
        done: dict[str, Any] = {"id": "resp_x", "status": "completed"}
        if self.usage:
            done["usage"] = {"input_tokens": 100, "output_tokens": 20}
        events = [
            {"type": "response.output_text.delta", "delta": text},
            {"type": "response.completed", "response": done},
        ]
        sse = "".join(f"data: {json.dumps(e)}\n\n" for e in events)
        return httpx.Response(200, content=sse.encode())


@pytest.fixture
def responses(monkeypatch: pytest.MonkeyPatch) -> FakeResponses:
    fake = FakeResponses()
    transport = httpx.MockTransport(fake)

    def client(*_a: Any, **_k: Any) -> httpx.Client:
        return _REAL_CLIENT(transport=transport)

    monkeypatch.setattr(httpx, "Client", client)
    return fake


def _args(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "openai-chatgpt-plan",
        "--config-dir",
        str(tmp_path / "cfg"),
        "--games-dir",
        str(tmp_path / "games"),
        *extra,
    ]


def test_dry_run_creates_nothing(
    tmp_path: Path, responses: FakeResponses, capsys: Any
) -> None:
    assert live_run.main(_args(tmp_path, "--dry-run")) == 0
    out = capsys.readouterr().out
    assert "Dry run: nothing was created" in out
    assert "signed in      : NO" in out
    assert "store=false, stream=true" in out
    assert not (tmp_path / "games").exists()
    assert not responses.bodies


def test_run_refused_when_not_signed_in(
    tmp_path: Path, responses: FakeResponses
) -> None:
    assert live_run.main(_args(tmp_path)) == live_run.EXIT_REFUSED
    assert not (tmp_path / "games").exists() and not responses.bodies


def test_config_dir_inside_repo_is_refused(
    tmp_path: Path, responses: FakeResponses
) -> None:
    inside = Path(oauth.__file__).resolve().parents[3] / "cfg"
    args = ["openai-chatgpt-plan", "--config-dir", str(inside), "--dry-run"]
    if not (inside.parent / ".git").exists():
        pytest.skip("not a git checkout")
    assert live_run.main(args) == live_run.EXIT_REFUSED


def test_status_reports_sign_in(tmp_path: Path, capsys: Any) -> None:
    assert live_run.main(_args(tmp_path, "status")) == live_run.EXIT_REFUSED
    _signed_in(tmp_path / "cfg")
    assert live_run.main(_args(tmp_path, "status")) == 0
    assert "chatgpt.tokens.use.direct" in capsys.readouterr().out


def test_bounded_game_runs_on_the_plan_client(
    tmp_path: Path, responses: FakeResponses, capsys: Any
) -> None:
    cred = _signed_in(tmp_path / "cfg")
    code = live_run.main(_args(tmp_path, "--turns", "2", "--max-calls", "200"))
    assert code == 0
    games = list((tmp_path / "games").iterdir())
    assert len(games) == 1
    state = GameState.model_validate_json(
        (games[0] / "game_state.json").read_text(encoding="utf-8")
    )
    assert sum(state.scores.values()) > 0
    assert {"propose", "vote"} <= set(responses.phases)
    assert any(p.startswith("judge") for p in responses.phases)
    assert set(responses.auth) == {f"Bearer {cred.access_token}"}
    for body in responses.bodies:
        assert body["store"] is False and body["stream"] is True
        assert body["model"] == "gpt-5.2"
        assert "max_output_tokens" not in body
    config = (games[0] / "config.yml").read_text(encoding="utf-8")
    assert "max_calls_per_game: 200" in config
    assert "max_total_tokens_per_game: 200000" in config
    usage = (games[0] / "token_usage.jsonl").read_text(encoding="utf-8")
    first = json.loads(usage.splitlines()[0])
    assert first["provider"] == "openai_chatgpt_plan"
    assert first["input_tokens"] == 100 and first["usage_available"]
    # The registration is removed after the run.
    assert api_clients._CHATGPT_PLAN_TOKENS is None


def test_call_cap_stops_the_game(
    tmp_path: Path, responses: FakeResponses
) -> None:
    _signed_in(tmp_path / "cfg")
    assert live_run.main(_args(tmp_path, "--max-calls", "3")) != 0
    assert len(responses.bodies) == 3
    assert api_clients._CHATGPT_PLAN_TOKENS is None


def test_missing_usage_stops_a_token_capped_run(
    tmp_path: Path, responses: FakeResponses
) -> None:
    responses.usage = False
    _signed_in(tmp_path / "cfg")
    assert live_run.main(_args(tmp_path, "--max-calls", "200")) != 0
    assert len(responses.bodies) == 1
