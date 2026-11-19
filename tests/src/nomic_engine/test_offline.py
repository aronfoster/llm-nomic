"""Prove pytest cannot use live credentials or send a provider request.

``python-dotenv`` walks upward from ``config.py``. A ``.env`` in the
checkout, or in a parent directory when the checkout has none, used to
be applied at import. These tests place fake files on that walk and
fake provider variables in the process environment. The suite must not
observe them. A real game run still loads the nearest file, which a
fresh interpreter (without the pytest guard) checks.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
from anthropic import Anthropic
from openai import OpenAI

from src.nomic_engine.config import get_api_key_from_env, load_env_vars
from src.nomic_engine.data_models import ModelDefinition
from src.nomic_engine.startup_validation import (
    _validate_google,
    _validate_local,
    _validate_openai,
    _validate_xai,
)
from tests.offline_guard import (
    PROVIDER_CREDENTIAL_ENV_VARS,
    blocked_destinations,
    caused_by_offline_block,
    scrub_provider_credentials,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PROVIDER_KEYS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "XAI_API_KEY",
)
_CHECKOUT_VALUES = {
    "OPENAI_API_KEY": "offline-checkout-openai",
    "ANTHROPIC_API_KEY": "offline-checkout-anthropic",
    "GOOGLE_API_KEY": "offline-checkout-google",
    "XAI_API_KEY": "offline-checkout-xai",
}
_PARENT_VALUES = {
    "OPENAI_API_KEY": "offline-parent-openai",
    "ANTHROPIC_API_KEY": "offline-parent-anthropic",
    "GOOGLE_API_KEY": "offline-parent-google",
    "XAI_API_KEY": "offline-parent-xai",
}
_CWD_VALUE = "offline-cwd-should-not-load"

_PROBE = """\
import json
import os
import src.nomic_engine.config as config

KEYS = [
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "XAI_API_KEY",
]
before = {key: os.environ.get(key) for key in KEYS}
config.load_env_vars()
after = {key: os.environ.get(key) for key in KEYS}
print(json.dumps({"before": before, "after": after}))
"""


def _env_text(values: dict[str, str]) -> str:
    return "".join(f"{name}={value}\n" for name, value in values.items())


def _dotenv_pair() -> tuple[Path, Path]:
    """Return ``(closer, higher)`` paths the dotenv walk will see.

    Prefer the checkout root and its parent: that is where a real
    ``.env`` sits when the game runs. If either file already exists,
    use directories under ``src/`` instead so a developer's secrets
    are never overwritten. Both pairs are on the walk that starts at
    ``config.py``.
    """
    checkout = _REPO_ROOT / ".env"
    parent = _REPO_ROOT.parent / ".env"
    if not checkout.exists() and not parent.exists():
        return checkout, parent
    closer = _REPO_ROOT / "src" / "nomic_engine" / ".env"
    higher = _REPO_ROOT / "src" / ".env"
    if closer.exists() or higher.exists():
        raise AssertionError(
            "offline dotenv test cannot find a free .env path"
        )
    return closer, higher


def _assert_provider_keys_absent() -> None:
    for name in _PROVIDER_KEYS:
        assert os.environ.get(name) is None


@contextmanager
def _temporary_files(files: dict[Path, str]) -> Iterator[None]:
    for path in files:
        if path.exists():
            raise AssertionError(f"refusing to overwrite {path}")
    try:
        for path, contents in files.items():
            path.write_text(contents)
        yield
    finally:
        for path in files:
            path.unlink(missing_ok=True)


def _run_real_loader(cwd: Path) -> dict[str, dict[str, str | None]]:
    """Import config and call ``load_env_vars`` outside the pytest guard.

    The probe is a real file. ``python -c`` has no ``__main__.__file__``,
    and python-dotenv then searches the working directory instead of
    walking from ``config.py`` the way ``python -m src.nomic_engine.main``
    does.
    """
    probe = cwd / "_offline_probe.py"
    probe.write_text(_PROBE)
    env = os.environ.copy()
    env.pop("PYTHON_DOTENV_DISABLED", None)
    for name in PROVIDER_CREDENTIAL_ENV_VARS:
        env.pop(name, None)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(_REPO_ROOT), str(_REPO_ROOT / "src")]
    )
    completed = subprocess.run(
        [sys.executable, str(probe)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    payload = json.loads(completed.stdout)
    before = payload["before"]
    after = payload["after"]
    assert isinstance(before, dict)
    assert isinstance(after, dict)
    return {"before": before, "after": after}


def _clear_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop inherited proxy settings so client construction stays direct.

    A SOCKS proxy would import socksio while the client is built. This
    suite does not require that dependency. The proxy-setup test sets
    the variables itself.
    """
    for name in list(os.environ):
        if name.lower().endswith("_proxy"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("REQUEST_METHOD", raising=False)


def _accept_one(listener: socket.socket, received: list[bytes]) -> None:
    try:
        conn, _addr = listener.accept()
    except (TimeoutError, OSError):
        return
    with conn:
        conn.settimeout(0.2)
        try:
            received.append(conn.recv(65536))
        except (TimeoutError, OSError):
            received.append(b"")


def test_scrub_provider_credentials_leaves_other_variables() -> None:
    """The scrubber removes provider secrets and nothing else."""
    environ = {
        "OPENAI_API_KEY": "offline-env-openai",
        "ANTHROPIC_API_KEY": "offline-env-anthropic",
        "GOOGLE_API_KEY": "offline-env-google",
        "GEMINI_API_KEY": "offline-env-gemini",
        "XAI_API_KEY": "offline-env-xai",
        "PATH": "/usr/bin",
        "HOME": "/tmp/offline-home",
    }
    removed = scrub_provider_credentials(environ)
    assert "OPENAI_API_KEY" not in environ
    assert "ANTHROPIC_API_KEY" not in environ
    assert "GOOGLE_API_KEY" not in environ
    assert "GEMINI_API_KEY" not in environ
    assert "XAI_API_KEY" not in environ
    assert environ["PATH"] == "/usr/bin"
    assert environ["HOME"] == "/tmp/offline-home"
    assert "PATH" not in removed
    assert "HOME" not in removed


def test_inherited_provider_credentials_are_absent() -> None:
    """Credentials that were in the environment are gone before tests run."""
    for name in PROVIDER_CREDENTIAL_ENV_VARS:
        assert os.environ.get(name) is None
    assert os.environ.get("PYTHON_DOTENV_DISABLED") == "1"


def test_checkout_dotenv_is_hidden_from_tests_and_loaded_for_a_game(
    tmp_path: Path,
) -> None:
    """A checkout ``.env`` beats a parent file, and tests see neither."""
    closer, higher = _dotenv_pair()
    assert (_REPO_ROOT / "src" / "nomic_engine" / "config.py").is_file()
    files = {
        closer: _env_text(_CHECKOUT_VALUES),
        higher: _env_text(_PARENT_VALUES),
        tmp_path / ".env": f"OPENAI_API_KEY={_CWD_VALUE}\n",
    }
    with _temporary_files(files):
        load_env_vars()
        _assert_provider_keys_absent()
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            get_api_key_from_env("OPENAI_API_KEY")

        loaded = _run_real_loader(tmp_path)

    assert list(loaded["before"].values()) == [None, None, None, None]
    assert loaded["after"] == _CHECKOUT_VALUES
    _assert_provider_keys_absent()


def test_parent_dotenv_is_hidden_from_tests_and_loaded_for_a_game(
    tmp_path: Path,
) -> None:
    """With no closer file, a parent ``.env`` loads only for a game run."""
    _closer, higher = _dotenv_pair()
    files = {
        higher: _env_text(_PARENT_VALUES),
        tmp_path / ".env": f"OPENAI_API_KEY={_CWD_VALUE}\n",
    }
    with _temporary_files(files):
        load_env_vars()
        _assert_provider_keys_absent()
        loaded = _run_real_loader(tmp_path)

    assert list(loaded["before"].values()) == [None, None, None, None]
    assert loaded["after"] == _PARENT_VALUES
    _assert_provider_keys_absent()


def test_main_loads_env_when_the_game_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI loads ``.env`` at startup, before it parses arguments."""
    calls: list[str] = []

    def _record() -> None:
        calls.append("loaded")

    monkeypatch.setattr("src.nomic_engine.main.load_env_vars", _record)
    monkeypatch.setattr(sys, "argv", ["nomic", "--help"])
    from src.nomic_engine.main import main

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    assert calls == ["loaded"]


def test_provider_clients_construct_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Building httpx, OpenAI, and Anthropic clients does not connect.

    The SOCKS proxy setup constructs the same clients with ``socket``
    patched to fail. This guard must keep that possible: it blocks
    ``connect``, not construction.
    """
    _clear_proxy_env(monkeypatch)
    before = len(blocked_destinations)
    with httpx.Client() as http_client:
        assert http_client is not None
    with OpenAI(api_key="offline-test-key") as openai_client:
        assert openai_client.api_key == "offline-test-key"
    with Anthropic(api_key="offline-test-key") as anthropic_client:
        assert anthropic_client.api_key == "offline-test-key"
    assert blocked_destinations[before:] == []


def test_socket_patch_still_allows_client_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replacing ``socket.socket`` must not be required for construction.

    PR 142's SOCKS test points ``socket.socket`` and
    ``socket.create_connection`` at a function that raises, then builds
    the clients. Construction has to succeed under that patch.
    """
    _clear_proxy_env(monkeypatch)

    def _fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("client construction opened a socket")

    monkeypatch.setattr(socket, "socket", _fail)
    monkeypatch.setattr(socket, "create_connection", _fail)
    with httpx.Client() as http_client:
        assert http_client is not None
    with OpenAI(api_key="offline-test-key") as openai_client:
        assert openai_client.api_key == "offline-test-key"
    with Anthropic(api_key="offline-test-key") as anthropic_client:
        assert anthropic_client.api_key == "offline-test-key"


@pytest.mark.attempts_network
def test_provider_call_and_startup_pings_stop_before_transmission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider call and the startup pings fail before any bytes leave.

    ``startup_validation`` really calls OpenAI, xAI, Google, and Ollama.
    Those calls must not succeed, and the local listener that stands in
    for the provider must receive nothing.
    """
    _clear_proxy_env(monkeypatch)
    received: list[bytes] = []
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(0.3)
    port = listener.getsockname()[1]
    thread = threading.Thread(
        target=_accept_one, args=(listener, received), daemon=True
    )
    thread.start()
    before = len(blocked_destinations)
    try:
        client = OpenAI(
            api_key="offline-not-a-real-key",
            base_url=f"http://127.0.0.1:{port}/v1",
            max_retries=0,
            timeout=1.0,
        )
        with pytest.raises(Exception) as exc_info:
            client.chat.completions.create(
                model="offline-test-model",
                messages=[{"role": "user", "content": "ping"}],
            )
        assert caused_by_offline_block(exc_info.value)

        local_result = _validate_local(
            ModelDefinition(
                id="offline-test",
                provider="local",
                api_model_id=f"http://127.0.0.1:{port}/v1",
                env_key_name=None,
            ),
            'Player "Local"',
        )
        assert local_result is not None
        assert "Ollama unreachable" in local_result

        monkeypatch.setenv("OPENAI_API_KEY", "offline-not-a-real-openai-key")
        openai_result = _validate_openai("OPENAI_API_KEY", 'Player "OpenAI"')
        assert openai_result is not None
        assert openai_result != ""

        monkeypatch.setenv("XAI_API_KEY", "offline-not-a-real-xai-key")
        xai_result = _validate_xai("XAI_API_KEY", 'Player "xAI"')
        assert xai_result is not None

        monkeypatch.setenv("GOOGLE_API_KEY", "offline-not-a-real-google-key")
        google_result = _validate_google("GOOGLE_API_KEY", "Judge")
        assert google_result is not None
    finally:
        listener.close()
        thread.join(timeout=2)

    attempted = blocked_destinations[before:]
    hosts = [
        dest[0]
        for dest in attempted
        if isinstance(dest, tuple) and len(dest) >= 1
    ]
    # Real provider endpoints are rejected inside create_connection,
    # before name resolution. The local listener stands in for Ollama
    # and for a direct OpenAI completion, and it must see no bytes.
    assert "api.openai.com" in hosts
    assert "api.x.ai" in hosts
    assert "generativelanguage.googleapis.com" in hosts
    assert ("127.0.0.1", port) in attempted
    assert received == []
