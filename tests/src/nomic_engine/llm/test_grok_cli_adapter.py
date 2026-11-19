"""Offline tests for the opt-in grok CLI process adapter.

The fake CLI is a local Python script. These tests do not run the real
grok binary and do not open a network connection.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from src.nomic_engine.data_models import ModelDefinition
from src.nomic_engine.llm.api_clients import create_api_client
from src.nomic_engine.llm.providers.grok_cli_adapter import (
    CHILD_ENV_KEYS,
    TOOL_ISOLATION_GATE,
    GrokCliAdapterDisabled,
    GrokCliAuthError,
    GrokCliCancelledError,
    GrokCliError,
    GrokCliMalformedOutputError,
    GrokCliNetworkError,
    GrokCliNonZeroExitError,
    GrokCliProcessAdapter,
    GrokCliQuotaError,
    GrokCliResponse,
    GrokCliTimeoutError,
    GrokCliTruncatedOutputError,
    select_grok_cli_adapter,
)

_FAKE = Path(__file__).resolve().parents[3] / "fixtures" / "fake_grok_cli.py"
_REPO = Path(__file__).resolve().parents[4]


def _adapter(
    tmp_path: Path,
    mode: str,
    payload: Path,
    *,
    enabled: bool = True,
    acknowledge_unverified_tool_isolation: bool = True,
    wall_timeout_seconds: float = 2.0,
    stdout_byte_cap: int = 65536,
    stderr_byte_cap: int = 65536,
    work_dir: Path | None = None,
    home_dir: Path | None = None,
    model: str | None = None,
    terminate_grace_seconds: float = 0.25,
    extra_executable: tuple[str, ...] = (),
) -> GrokCliProcessAdapter:
    home = home_dir if home_dir is not None else tmp_path / "home"
    work = work_dir if work_dir is not None else tmp_path / "work"
    return select_grok_cli_adapter(
        enabled=enabled,
        acknowledge_unverified_tool_isolation=(
            acknowledge_unverified_tool_isolation
        ),
        executable=(
            sys.executable,
            str(_FAKE),
            mode,
            str(payload),
            *extra_executable,
        ),
        home_dir=home,
        work_dir=work,
        wall_timeout_seconds=wall_timeout_seconds,
        stdout_byte_cap=stdout_byte_cap,
        stderr_byte_cap=stderr_byte_cap,
        model=model,
        terminate_grace_seconds=terminate_grace_seconds,
    )


def _wait_until_gone(pid: int) -> None:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if not Path(f"/proc/{pid}").exists():
            return
        time.sleep(0.02)
    os.kill(pid, signal.SIGKILL)
    raise AssertionError(f"process {pid} was still alive")


def _wait_for_file(path: Path) -> None:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size > 0:
            return
        time.sleep(0.02)
    raise AssertionError(f"{path} was not written")


def _read_pid(path: Path) -> int:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if path.is_file() and path.read_text(encoding="utf-8").strip():
            return int(path.read_text(encoding="utf-8").strip())
        time.sleep(0.02)
    raise AssertionError(f"pid file {path} was not written")


def test_game_factory_refuses_grok_cli_without_spawning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default factory cannot select the CLI adapter."""

    def _fail_popen(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("game factory spawned a process")

    monkeypatch.setattr(subprocess, "Popen", _fail_popen)
    model = ModelDefinition(
        id="grok-cli",
        provider="grok_cli",
        api_model_id="grok-4",
        env_key_name="XAI_API_KEY",
    )
    with pytest.raises(ValueError, match=TOOL_ISOLATION_GATE) as exc_info:
        create_api_client(model)
    assert "no paid API fallback" in str(exc_info.value)
    assert "XAI_API_KEY" not in str(exc_info.value)


def test_factory_refuses_when_disabled(tmp_path: Path) -> None:
    with pytest.raises(GrokCliAdapterDisabled, match="disabled"):
        _adapter(
            tmp_path,
            "valid",
            tmp_path / "dump.json",
            enabled=False,
        )


def test_factory_refuses_without_the_isolation_gate(tmp_path: Path) -> None:
    with pytest.raises(GrokCliAdapterDisabled, match=TOOL_ISOLATION_GATE):
        _adapter(
            tmp_path,
            "valid",
            tmp_path / "dump.json",
            acknowledge_unverified_tool_isolation=False,
        )


def test_factory_refuses_a_repository_working_directory(
    tmp_path: Path,
) -> None:
    with pytest.raises(GrokCliAdapterDisabled, match="git working tree"):
        _adapter(
            tmp_path,
            "valid",
            tmp_path / "dump.json",
            work_dir=_REPO,
        )


def test_factory_refuses_the_real_home(tmp_path: Path) -> None:
    with pytest.raises(GrokCliAdapterDisabled, match="synthetic home_dir"):
        _adapter(
            tmp_path,
            "valid",
            tmp_path / "dump.json",
            home_dir=Path.home(),
        )


def test_factory_refuses_an_auth_cache(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cache = home / ".grok"
    cache.mkdir(parents=True)
    (cache / "auth.json").write_text("{}", encoding="utf-8")
    with pytest.raises(GrokCliAdapterDisabled, match="auth cache"):
        _adapter(
            tmp_path,
            "valid",
            tmp_path / "dump.json",
            home_dir=home,
        )


def test_refuses_always_approve_before_spawn(tmp_path: Path) -> None:
    dump = tmp_path / "dump.json"
    adapter = _adapter(
        tmp_path,
        "valid",
        dump,
        extra_executable=("--always-approve",),
    )
    with pytest.raises(GrokCliAdapterDisabled, match="always-approve"):
        adapter.run("hello")
    assert not dump.exists()


def test_valid_json_contract_env_and_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XAI_API_KEY", "secret-value")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-value")
    monkeypatch.setenv("SENTINEL_SHOULD_NOT_LEAK", "parent")
    dump = tmp_path / "dump.json"
    home = tmp_path / "home"
    work = tmp_path / "work"
    adapter = _adapter(
        tmp_path,
        "valid",
        dump,
        home_dir=home,
        work_dir=work,
        model="grok-test",
    )
    response = adapter.run("hello from the test")
    assert isinstance(response, GrokCliResponse)
    assert response.text == "hello from the fake cli"
    assert response.stop_reason == "end_turn"
    assert response.usage_available is True
    assert response.input_tokens == 3
    assert response.output_tokens == 1
    assert response.exit_code == 0

    recorded = json.loads(dump.read_text(encoding="utf-8"))
    argv = recorded["argv"]
    assert argv[0] == str(_FAKE)
    assert argv[1:3] == ["valid", str(dump)]
    assert "--output-format" in argv
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("-p") + 1] == "hello from the test"
    assert argv[argv.index("--cwd") + 1] == str(work.resolve())
    assert argv[argv.index("--model") + 1] == "grok-test"
    for flag in (
        "--no-alt-screen",
        "--no-plan",
        "--no-subagents",
        "--disable-web-search",
    ):
        assert flag in argv
    for forbidden in (
        "--always-approve",
        "--yolo",
        "--dangerously-skip-permissions",
        "bypassPermissions",
        "--tools",
        "--disallowed-tools",
        "--max-turns",
        "--plugin-dir",
        "--allow",
    ):
        assert forbidden not in argv
    assert recorded["cwd"] == str(work.resolve())
    child_env = recorded["env"]
    assert child_env["HOME"] == str(home.resolve())
    assert child_env["GROK_HOME"] == str((home / ".grok").resolve())
    assert child_env["TMPDIR"] == str((home / "tmp").resolve())
    assert child_env["PATH"] == "/usr/bin:/bin"
    assert "XAI_API_KEY" not in child_env
    assert "OPENAI_API_KEY" not in child_env
    assert "SENTINEL_SHOULD_NOT_LEAK" not in child_env
    assert child_env["GROK_SUBAGENTS"] == "0"
    assert child_env["GROK_DISABLE_AUTOUPDATER"] == "1"
    assert set(child_env) == set(CHILD_ENV_KEYS)
    assert "secret-value" not in json.dumps(child_env)


def test_explicit_zero_usage_stays_zero(tmp_path: Path) -> None:
    response = _adapter(tmp_path, "zero-usage", tmp_path / "unused").run(
        "hello"
    )
    assert response.usage_available is True
    assert response.input_tokens == 0
    assert response.output_tokens == 0


def test_missing_usage_is_unavailable_not_zero(tmp_path: Path) -> None:
    response = _adapter(tmp_path, "missing-usage", tmp_path / "unused").run(
        "hello"
    )
    assert response.text == "hello from the fake cli"
    assert response.usage_available is False
    assert response.input_tokens is None
    assert response.output_tokens is None


@pytest.mark.parametrize("mode", ["malformed-usage", "bool-usage"])
def test_malformed_usage_is_unavailable_not_zero(
    tmp_path: Path, mode: str
) -> None:
    response = _adapter(tmp_path, mode, tmp_path / "unused").run("hello")
    assert response.usage_available is False
    assert response.input_tokens is None
    assert response.output_tokens is None


def test_incomplete_usage_is_unavailable_not_zero(tmp_path: Path) -> None:
    response = _adapter(tmp_path, "incomplete-usage", tmp_path / "unused").run(
        "hello"
    )
    assert response.usage_available is False
    assert response.input_tokens is None
    assert response.output_tokens is None


@pytest.mark.parametrize(
    ("mode", "exc_type", "kind"),
    [
        ("auth", GrokCliAuthError, "auth"),
        ("quota", GrokCliQuotaError, "quota"),
        ("network", GrokCliNetworkError, "network"),
        ("network-stderr", GrokCliNetworkError, "network"),
    ],
)
def test_auth_quota_and_network_errors_are_typed(
    tmp_path: Path,
    mode: str,
    exc_type: type[Exception],
    kind: str,
) -> None:
    adapter = _adapter(tmp_path, mode, tmp_path / "unused")
    with pytest.raises(exc_type, match="No paid API fallback") as exc_info:
        adapter.run("hello")
    assert getattr(exc_info.value, "kind") == kind


def test_malformed_stdout_is_a_typed_error(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, "malformed", tmp_path / "unused")
    with pytest.raises(GrokCliMalformedOutputError, match="not valid JSON"):
        adapter.run("hello")


def test_nonzero_exit_is_a_typed_error(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, "nonzero", tmp_path / "unused")
    with pytest.raises(GrokCliNonZeroExitError, match="exited 4") as exc_info:
        adapter.run("hello")
    assert exc_info.value.exit_code == 4
    assert exc_info.value.kind == "nonzero_exit"


def test_stop_reason_max_tokens_is_truncated(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, "stop-truncated", tmp_path / "unused")
    with pytest.raises(GrokCliTruncatedOutputError, match="max_tokens"):
        adapter.run("hello")


def test_stop_reason_cancelled_is_cancelled(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, "stop-cancelled", tmp_path / "unused")
    with pytest.raises(GrokCliCancelledError, match="cancelled"):
        adapter.run("hello")


@pytest.mark.parametrize(
    ("mode", "cap_name", "stream_name"),
    [
        ("flood-stdout", "stdout_byte_cap", "stdout"),
        ("flood-stderr", "stderr_byte_cap", "stderr"),
    ],
)
def test_stdout_and_stderr_are_byte_capped(
    tmp_path: Path,
    mode: str,
    cap_name: str,
    stream_name: str,
) -> None:
    payload = tmp_path / "flood"
    payload.mkdir()
    kwargs = {cap_name: 128}
    adapter = _adapter(
        tmp_path,
        mode,
        payload,
        stdout_byte_cap=int(kwargs.get("stdout_byte_cap", 65536)),
        stderr_byte_cap=int(kwargs.get("stderr_byte_cap", 65536)),
    )
    with pytest.raises(
        GrokCliTruncatedOutputError, match=stream_name
    ) as exc_info:
        adapter.run("hello")
    assert exc_info.value.kind == "truncated"
    captured = (
        exc_info.value.stdout
        if stream_name == "stdout"
        else exc_info.value.stderr
    )
    assert len(captured.encode("utf-8")) <= 128
    pid = _read_pid(payload / "pid")
    _wait_until_gone(pid)


def test_cancel_kills_the_child(tmp_path: Path) -> None:
    payload = tmp_path / "cancel"
    payload.mkdir()
    adapter = _adapter(
        tmp_path,
        "cancel",
        payload,
        wall_timeout_seconds=5.0,
    )
    holder: dict[str, BaseException] = {}

    def _run() -> None:
        try:
            adapter.run("hello")
        except GrokCliError as exc:
            holder["error"] = exc

    thread = threading.Thread(target=_run)
    thread.start()
    _wait_for_file(payload / "ready")
    adapter.cancel()
    thread.join(timeout=6)
    assert not thread.is_alive()
    error = holder["error"]
    assert isinstance(error, GrokCliCancelledError)
    assert error.kind == "cancelled"
    _wait_until_gone(_read_pid(payload / "pid"))


def test_timeout_kills_descendant_process_group(tmp_path: Path) -> None:
    payload = tmp_path / "timeout"
    payload.mkdir()
    adapter = _adapter(
        tmp_path,
        "timeout-descendant",
        payload,
        wall_timeout_seconds=0.8,
        terminate_grace_seconds=0.3,
    )
    with pytest.raises(GrokCliTimeoutError, match="process group") as exc_info:
        adapter.run("hello")
    assert exc_info.value.kind == "timeout"
    parent_pid = _read_pid(payload / "parent.pid")
    child_pid = _read_pid(payload / "child.pid")
    assert (payload / "parent-term").read_text(encoding="utf-8") == "term\n"
    assert (payload / "child-term").read_text(encoding="utf-8") == "term\n"
    assert parent_pid != child_pid
    _wait_until_gone(parent_pid)
    _wait_until_gone(child_pid)
