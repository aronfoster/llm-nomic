"""Prove pytest cannot use live credentials or send a provider request.

``python-dotenv`` walks upward from the file that calls ``load_dotenv``.
These tests copy ``config.py`` into a disposable tree and put dummy
``.env`` files only there. The probe prints a fixed token, never the
loaded values, and its environment contains only those dummies. The
pytest process itself still refuses ``.env`` via the offline guard.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
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
_CONFIG_SOURCE = _REPO_ROOT / "src" / "nomic_engine" / "config.py"
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
_NEAR_VALUES = {
    "OPENAI_API_KEY": "offline-near-openai",
    "ANTHROPIC_API_KEY": "offline-near-anthropic",
    "GOOGLE_API_KEY": "offline-near-google",
    "XAI_API_KEY": "offline-near-xai",
}
_CWD_VALUE = "offline-cwd-should-not-load"
_PROBE_OK = "ok"
_PROBE_TOKENS = frozenset({_PROBE_OK, "IMPORT_LOADED", "LOAD_MISMATCH"})

# Fixed tokens only. Loaded key material is compared inside the probe
# and is never written to stdout or stderr.
_PROBE = """\
import json
import os
import sys

KEYS = [
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "XAI_API_KEY",
]
import nomic_engine.config as config

before = {key: os.environ.get(key) for key in KEYS}
config.load_env_vars()
after = {key: os.environ.get(key) for key in KEYS}
expected = json.loads(os.environ["OFFLINE_EXPECTED_JSON"])
if any(value is not None for value in before.values()):
    sys.stdout.write("IMPORT_LOADED\\n")
    sys.exit(4)
if after != expected:
    sys.stdout.write("LOAD_MISMATCH\\n")
    sys.exit(5)
sys.stdout.write("ok\\n")
"""


def _env_text(values: dict[str, str]) -> str:
    return "".join(f"{name}={value}\n" for name, value in values.items())


def _assert_provider_keys_absent() -> None:
    """Fail without echoing a credential that is still set."""
    for name in _PROVIDER_KEYS:
        if os.environ.get(name) is not None:
            raise AssertionError(f"{name} is visible in the test process")


def _isolated_package(
    tmp_path: Path,
    *,
    near: dict[str, str] | None = None,
    checkout: dict[str, str] | None = None,
    parent: dict[str, str] | None = None,
) -> tuple[Path, Path]:
    """Copy ``config.py`` into a tree that contains only dummy ``.env`` files.

    Layout, from the copied module upward:

    * ``checkout/app/nomic_engine/.env`` when ``near`` is set
    * ``checkout/.env`` when ``checkout`` is set
    * ``isolated/.env`` when ``parent`` is set

    The working directory is a sibling of that tree and has its own
    ``.env``. python-dotenv must not use it when the probe is a real
    file, matching ``python -m src.nomic_engine.main``.
    """
    if not _CONFIG_SOURCE.is_file():
        raise AssertionError("config.py source is missing")
    root = tmp_path / "isolated"
    package = root / "checkout" / "app" / "nomic_engine"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    shutil.copyfile(_CONFIG_SOURCE, package / "config.py")
    if near is not None:
        (package / ".env").write_text(_env_text(near))
    if checkout is not None:
        (root / "checkout" / ".env").write_text(_env_text(checkout))
    if parent is not None:
        (root / ".env").write_text(_env_text(parent))
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / ".env").write_text(f"OPENAI_API_KEY={_CWD_VALUE}\n")
    return package.parent, cwd


def _probe_env(app_dir: Path, expected: dict[str, str]) -> dict[str, str]:
    """Environment for the probe: dummies plus process basics, no secrets."""
    env: dict[str, str] = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(app_dir),
        "PYTHONDONTWRITEBYTECODE": "1",
        "OFFLINE_EXPECTED_JSON": json.dumps(expected),
    }
    for name in ("HOME", "LANG", "LC_ALL", "TZ"):
        value = os.environ.get(name)
        if value is not None:
            env[name] = value
    return env


def _run_isolated_loader(
    app_dir: Path, cwd: Path, expected: dict[str, str]
) -> str:
    """Run the copied config outside the pytest dotenv guard.

    Returns the probe token. stdout is that token only.
    """
    probe = cwd / "_offline_probe.py"
    probe.write_text(_PROBE)
    completed = subprocess.run(
        [sys.executable, str(probe)],
        cwd=cwd,
        env=_probe_env(app_dir, expected),
        capture_output=True,
        text=True,
        check=False,
    )
    token = completed.stdout.strip()
    if token not in _PROBE_TOKENS:
        token = "UNRECOGNIZED_OUTPUT"
    if completed.returncode != 0 or token != _PROBE_OK:
        raise AssertionError(
            "isolated loader probe failed with status "
            f"{completed.returncode} ({token})"
        )
    if _CWD_VALUE in completed.stdout or _CWD_VALUE in completed.stderr:
        raise AssertionError("probe output included the cwd dummy")
    return token


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
        if os.environ.get(name) is not None:
            raise AssertionError(f"{name} is visible in the test process")
    assert os.environ.get("PYTHON_DOTENV_DISABLED") == "1"


def test_pytest_guard_hides_dotenv_without_printing_values() -> None:
    """Calling the real loader inside pytest does not reveal a key."""
    load_env_vars()
    _assert_provider_keys_absent()
    try:
        get_api_key_from_env("OPENAI_API_KEY")
    except ValueError as exc:
        if "OPENAI_API_KEY" not in str(exc):
            raise AssertionError(
                "missing-key error did not name the variable"
            ) from None
        return
    raise AssertionError("get_api_key_from_env returned a key")


def test_isolated_checkout_dotenv_loads_for_a_game_run(
    tmp_path: Path,
) -> None:
    """In a disposable tree, the checkout file beats the parent file."""
    app_dir, cwd = _isolated_package(
        tmp_path, checkout=_CHECKOUT_VALUES, parent=_PARENT_VALUES
    )
    token = _run_isolated_loader(app_dir, cwd, _CHECKOUT_VALUES)
    assert token == _PROBE_OK
    _assert_provider_keys_absent()


def test_isolated_parent_dotenv_loads_when_nothing_is_nearer(
    tmp_path: Path,
) -> None:
    """In a disposable tree, a parent ``.env`` loads when it is nearest."""
    app_dir, cwd = _isolated_package(tmp_path, parent=_PARENT_VALUES)
    token = _run_isolated_loader(app_dir, cwd, _PARENT_VALUES)
    assert token == _PROBE_OK
    _assert_provider_keys_absent()


def test_isolated_nearer_package_dotenv_beats_checkout(
    tmp_path: Path,
) -> None:
    """A ``.env`` beside the copied module beats one further up the walk."""
    app_dir, cwd = _isolated_package(
        tmp_path, near=_NEAR_VALUES, checkout=_CHECKOUT_VALUES
    )
    token = _run_isolated_loader(app_dir, cwd, _NEAR_VALUES)
    assert token == _PROBE_OK


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
