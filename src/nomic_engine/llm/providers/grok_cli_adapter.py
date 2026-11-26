"""Offline process adapter for ``grok -p --output-format json``.

This module is a contract-proof prototype. It is not a game provider.
``create_api_client`` refuses ``provider="grok_cli"``. The only way to
spawn the CLI is ``select_grok_cli_adapter`` with ``enabled=True`` and
``acknowledge_unverified_tool_isolation=True``.

Zero-tool isolation is not established. The inspected binary is
``grok 1.0.89 (28be5bb1bf65)``. Its ``--help`` / ``grok help`` text
exposes ``--tools`` and ``--disallowed-tools`` for built-in tools,
``--no-subagents``, and ``--disable-web-search``. It does not document
an empty ``--tools`` value as "no tools", and it has no flag that
disables MCP, hooks, plugins, and project instructions together.
``--max-turns`` limits agent turns. It is not a bound on internal model
requests or retries, so this adapter does not pass it and does not
claim LN-5 enforcement.

The child process gets a fresh allowlisted environment, a synthetic
``HOME`` / ``GROK_HOME``, and a disposable working directory that is
not a git checkout. Provider API keys are not copied from the parent.
``--always-approve``, ``--yolo``, ``--dangerously-skip-permissions``,
and ``bypassPermissions`` are refused.
"""

from __future__ import annotations

import json
import logging
import os
import select
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

INSPECTED_GROK_CLI_VERSION = "1.0.89"
INSPECTED_GROK_CLI_COMMIT = "28be5bb1bf65"

# Named gate. Zero-tool isolation was not established offline for the
# inspected CLI, so the adapter stays disabled until a caller sets this
# explicitly. See docs/evidence/ln4-grok-cli-contract.md.
TOOL_ISOLATION_GATE = "acknowledge_unverified_tool_isolation"

# Help text for 1.0.89 describes these as feature switches, not as a
# proof that the process has no tools. They are passed anyway so an
# opted-in run is narrower than the CLI defaults. They are not a
# zero-tool mode.
_PARTIAL_CONTAINMENT_FLAGS: tuple[str, ...] = (
    "--no-alt-screen",
    "--no-plan",
    "--no-subagents",
    "--disable-web-search",
)

# Exact argv elements that approve tools, resume a session, or pretend
# to select a tool set. The prompt is one element, so a prompt whose
# entire text is one of these tokens is refused.
_FORBIDDEN_ARGUMENTS: frozenset[str] = frozenset(
    {
        "--always-approve",
        "--yolo",
        "--dangerously-skip-permissions",
        "--permission-mode",
        "bypassPermissions",
        "--plugin-dir",
        "--tools",
        "--disallowed-tools",
        "--disallowedTools",
        "--allowedTools",
        "--allowed-tools",
        "--allow",
        "--deny",
        "--max-turns",
        "--oauth",
        "--resume",
        "--continue",
        "--session-id",
        "-c",
        "-r",
        "-s",
    }
)

# Documented Cursor/Claude scanners default on. Turning them off does
# not disable grok-native tools, MCP, hooks, or plugins. ``GROK_WRITE_FILE``
# only disables the write tool. None of these establish zero-tool mode.
CHILD_ENV_KEYS: frozenset[str] = frozenset(
    {
        "HOME",
        "GROK_HOME",
        "TMPDIR",
        "PATH",
        "LANG",
        "LC_ALL",
        "PYTHONDONTWRITEBYTECODE",
        "GROK_DISABLE_AUTOUPDATER",
        "GROK_SUBAGENTS",
        "GROK_MEMORY",
        "GROK_WEB_FETCH",
        "GROK_WRITE_FILE",
        "GROK_CURSOR_SKILLS_ENABLED",
        "GROK_CURSOR_RULES_ENABLED",
        "GROK_CURSOR_AGENTS_ENABLED",
        "GROK_CURSOR_MCPS_ENABLED",
        "GROK_CURSOR_HOOKS_ENABLED",
        "GROK_CLAUDE_SKILLS_ENABLED",
        "GROK_CLAUDE_RULES_ENABLED",
        "GROK_CLAUDE_AGENTS_ENABLED",
        "GROK_CLAUDE_MCPS_ENABLED",
        "GROK_CLAUDE_HOOKS_ENABLED",
    }
)

_AUTH_MARKERS: tuple[str, ...] = (
    "unauthenticated",
    "not authenticated",
    "authentication required",
    "invalid api key",
    "invalid xai_api_key",
    "unauthorized",
    "http 401",
    "status 401",
    " 401",
    "please login",
    "please log in",
    "grok login",
    "sign in",
)
_QUOTA_MARKERS: tuple[str, ...] = (
    "rate limit",
    "ratelimit",
    "too many requests",
    "quota",
    "http 429",
    "status 429",
    " 429",
    "billing",
    "insufficient_quota",
)
_NETWORK_MARKERS: tuple[str, ...] = (
    "network",
    "connection refused",
    "connection reset",
    "econnrefused",
    "econnreset",
    "name or service not known",
    "temporary failure in name resolution",
    "dns",
    "unreachable",
    "tls handshake",
    "certificate verify failed",
)

_TRUNCATED_STOP_REASONS: frozenset[str] = frozenset(
    {"max_tokens", "length", "max_completion_tokens"}
)
_CANCELLED_STOP_REASONS: frozenset[str] = frozenset({"cancelled", "canceled"})


class GrokCliError(Exception):
    """Visible failure from the grok CLI adapter.

    The adapter never falls back to a paid HTTP provider.
    """

    def __init__(
        self,
        message: str,
        *,
        kind: str,
        exit_code: int | None = None,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


class GrokCliAdapterDisabled(GrokCliError):
    """The adapter refused to start. No process was spawned."""

    def __init__(self, message: str) -> None:
        super().__init__(message, kind="disabled")


class GrokCliAuthError(GrokCliError):
    """The CLI reported an authentication failure."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, kind="auth", **kwargs)


class GrokCliQuotaError(GrokCliError):
    """The CLI reported quota or a rate limit. No other provider is tried."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, kind="quota", **kwargs)


class GrokCliNetworkError(GrokCliError):
    """The CLI reported a network failure. No other provider is tried."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, kind="network", **kwargs)


class GrokCliMalformedOutputError(GrokCliError):
    """Stdout was not one JSON object with the expected shape."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, kind="malformed", **kwargs)


class GrokCliTruncatedOutputError(GrokCliError):
    """Stdout or stderr hit its byte cap, or the CLI stop reason was cut."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, kind="truncated", **kwargs)


class GrokCliCancelledError(GrokCliError):
    """The run was cancelled and the child process group was killed."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, kind="cancelled", **kwargs)


class GrokCliNonZeroExitError(GrokCliError):
    """The CLI exited non-zero without a more specific classification."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, kind="nonzero_exit", **kwargs)


class GrokCliTimeoutError(GrokCliError):
    """The wall clock expired. The child process group was killed."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, kind="timeout", **kwargs)


@dataclass(frozen=True)
class GrokCliAdapterConfig:
    """Explicit settings for one opted-in adapter.

    ``enabled`` and ``acknowledge_unverified_tool_isolation`` have no
    true default. ``select_grok_cli_adapter`` requires both to be True.
    """

    enabled: bool
    acknowledge_unverified_tool_isolation: bool
    executable: tuple[str, ...]
    home_dir: Path
    wall_timeout_seconds: float
    stdout_byte_cap: int
    stderr_byte_cap: int
    work_dir: Path | None = None
    model: str | None = None
    terminate_grace_seconds: float = 0.25
    allow_auth_cache: bool = False


@dataclass(frozen=True)
class GrokCliResponse:
    """Parsed ``--output-format json`` object.

    ``input_tokens`` and ``output_tokens`` are null when usage is missing
    or malformed. Null is unavailable, not zero. ``usage_available`` is
    the flag for that distinction, matching LN-5.
    """

    text: str
    stop_reason: str | None
    usage_available: bool
    input_tokens: int | None
    output_tokens: int | None
    exit_code: int


@dataclass
class _Captured:
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool
    cancelled: bool
    truncated: bool
    truncated_stream: str | None


class GrokCliProcessAdapter:
    """Run one headless CLI prompt in an isolated process group."""

    def __init__(self, config: GrokCliAdapterConfig) -> None:
        self._config = config
        self._cancel = threading.Event()
        self._run_lock = threading.Lock()
        self._work_dir = _prepare_directories(config)

    def cancel(self) -> None:
        """Ask the in-flight run to kill its process group.

        Cancel is permanent for this adapter. Later ``run`` calls raise
        ``GrokCliCancelledError`` without spawning. Build a new adapter
        to continue.
        """
        self._cancel.set()

    def run(self, prompt: str) -> GrokCliResponse:
        """Spawn the CLI once and return the validated JSON response.

        Raises a ``GrokCliError`` subclass for every unsuccessful outcome.
        Does not call a paid API.
        """
        if not isinstance(prompt, str):
            raise GrokCliAdapterDisabled("prompt must be a string")
        if not self._run_lock.acquire(blocking=False):
            raise GrokCliAdapterDisabled(
                "this adapter is already running a prompt; use one "
                "adapter per concurrent caller"
            )
        try:
            if self._cancel.is_set():
                raise GrokCliCancelledError(
                    "this adapter was cancelled earlier; no process was "
                    "spawned. Create a new adapter. No paid API fallback."
                )
            argv = build_grok_cli_argv(
                self._config.executable,
                prompt,
                work_dir=self._work_dir,
                model=self._config.model,
            )
            env = build_child_env(self._config.home_dir)
            captured = _run_process(
                argv,
                cwd=self._work_dir,
                env=env,
                wall_timeout_seconds=self._config.wall_timeout_seconds,
                stdout_byte_cap=self._config.stdout_byte_cap,
                stderr_byte_cap=self._config.stderr_byte_cap,
                terminate_grace_seconds=self._config.terminate_grace_seconds,
                cancel_event=self._cancel,
            )
            return _interpret(captured)
        finally:
            self._run_lock.release()


def select_grok_cli_adapter(
    *,
    enabled: bool,
    acknowledge_unverified_tool_isolation: bool,
    executable: Sequence[str],
    home_dir: Path,
    wall_timeout_seconds: float,
    stdout_byte_cap: int,
    stderr_byte_cap: int,
    work_dir: Path | None = None,
    model: str | None = None,
    terminate_grace_seconds: float = 0.25,
    allow_auth_cache: bool = False,
) -> GrokCliProcessAdapter:
    """Return an adapter only when both opt-in flags are exactly True.

    There is no default selection. ``enabled=False`` or a missing
    isolation acknowledgement raises ``GrokCliAdapterDisabled`` before
    a process is created.
    """
    if enabled is not True:
        raise GrokCliAdapterDisabled(
            "grok CLI adapter is disabled. Pass enabled=True to opt in. "
            "create_api_client never does this, and there is no paid "
            "API fallback."
        )
    if acknowledge_unverified_tool_isolation is not True:
        raise GrokCliAdapterDisabled(
            "zero-tool isolation is not established for grok CLI "
            f"{INSPECTED_GROK_CLI_VERSION} ({INSPECTED_GROK_CLI_COMMIT}). "
            "The adapter stays behind "
            f"{TOOL_ISOLATION_GATE}=True. --tools, a denylist, and "
            "read-only mode are not a guarantee that tools, MCP, hooks, "
            "plugins, and project instructions are off."
        )
    command = _command_tuple(executable)
    config = GrokCliAdapterConfig(
        enabled=True,
        acknowledge_unverified_tool_isolation=True,
        executable=command,
        home_dir=home_dir,
        wall_timeout_seconds=wall_timeout_seconds,
        stdout_byte_cap=stdout_byte_cap,
        stderr_byte_cap=stderr_byte_cap,
        work_dir=work_dir,
        model=model,
        terminate_grace_seconds=terminate_grace_seconds,
        allow_auth_cache=allow_auth_cache,
    )
    _validate_limits(config)
    return GrokCliProcessAdapter(config)


def build_grok_cli_argv(
    executable: Sequence[str],
    prompt: str,
    *,
    work_dir: Path,
    model: str | None,
) -> list[str]:
    """Build the argv the adapter will exec.

    The prompt is a single argument to ``-p``. Flags that approve tools
    or that this help text does not establish as a full disable are
    rejected if they appear anywhere in the vector.
    """
    argv = [*_command_tuple(executable)]
    argv.extend(_PARTIAL_CONTAINMENT_FLAGS)
    argv.extend(["--cwd", str(work_dir)])
    if model is not None:
        if model.startswith("-") or model.strip() == "":
            raise GrokCliAdapterDisabled(
                "model must be a plain model id, not a flag"
            )
        argv.extend(["--model", model])
    argv.extend(["--output-format", "json", "-p", prompt])
    _reject_forbidden(argv)
    return argv


def build_child_env(home_dir: Path) -> dict[str, str]:
    """Return the only environment the child is allowed to see.

    The parent environment is not copied. Provider API keys are absent.
    ``HOME`` and ``GROK_HOME`` point at the synthetic directory.
    """
    root = home_dir.resolve()
    grok_home = root / ".grok"
    tmp_dir = root / "tmp"
    env = {
        "HOME": str(root),
        "GROK_HOME": str(grok_home),
        "TMPDIR": str(tmp_dir),
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "GROK_DISABLE_AUTOUPDATER": "1",
        "GROK_SUBAGENTS": "0",
        "GROK_MEMORY": "0",
        "GROK_WEB_FETCH": "0",
        "GROK_WRITE_FILE": "0",
        "GROK_CURSOR_SKILLS_ENABLED": "0",
        "GROK_CURSOR_RULES_ENABLED": "0",
        "GROK_CURSOR_AGENTS_ENABLED": "0",
        "GROK_CURSOR_MCPS_ENABLED": "0",
        "GROK_CURSOR_HOOKS_ENABLED": "0",
        "GROK_CLAUDE_SKILLS_ENABLED": "0",
        "GROK_CLAUDE_RULES_ENABLED": "0",
        "GROK_CLAUDE_AGENTS_ENABLED": "0",
        "GROK_CLAUDE_MCPS_ENABLED": "0",
        "GROK_CLAUDE_HOOKS_ENABLED": "0",
    }
    if set(env) != CHILD_ENV_KEYS:
        raise GrokCliAdapterDisabled(
            "child environment allowlist does not match the built env"
        )
    return env


def _command_tuple(executable: Sequence[str]) -> tuple[str, ...]:
    if isinstance(executable, (str, bytes)):
        raise GrokCliAdapterDisabled(
            "executable must be a sequence of arguments, not a shell string"
        )
    command = tuple(executable)
    if not command or any(part == "" for part in command):
        raise GrokCliAdapterDisabled(
            "executable must be a non-empty argument vector"
        )
    if not Path(command[0]).is_absolute():
        raise GrokCliAdapterDisabled(
            "executable[0] must be an absolute path. The child PATH is "
            "fixed, so a bare name would not resolve."
        )
    return command


def _validate_limits(config: GrokCliAdapterConfig) -> None:
    if config.wall_timeout_seconds <= 0:
        raise GrokCliAdapterDisabled("wall_timeout_seconds must be positive")
    if config.stdout_byte_cap <= 0 or config.stderr_byte_cap <= 0:
        raise GrokCliAdapterDisabled(
            "stdout and stderr byte caps must be positive"
        )
    if config.terminate_grace_seconds <= 0:
        raise GrokCliAdapterDisabled(
            "terminate_grace_seconds must be positive"
        )


def _prepare_directories(config: GrokCliAdapterConfig) -> Path:
    home = config.home_dir.expanduser().resolve()
    _reject_real_home(home)
    if not config.allow_auth_cache:
        _reject_auth_cache(home)
    home.mkdir(parents=True, exist_ok=True)
    (home / ".grok").mkdir(parents=True, exist_ok=True)
    (home / "tmp").mkdir(parents=True, exist_ok=True)
    if config.work_dir is None:
        work = Path(
            tempfile.mkdtemp(prefix="grok-cli-wd-", dir=str(home / "tmp"))
        )
    else:
        work = config.work_dir.expanduser().resolve()
        work.mkdir(parents=True, exist_ok=True)
    _reject_repository(work)
    return work


def _reject_real_home(home: Path) -> None:
    real_home = Path.home().resolve()
    real_grok = (real_home / ".grok").resolve()
    if home == real_home or home == real_grok:
        raise GrokCliAdapterDisabled(
            "refusing the real HOME and ~/.grok auth cache; pass a "
            "synthetic home_dir"
        )


def _reject_auth_cache(home: Path) -> None:
    """Refuse a home that already holds a sign-in unless opted in.

    ``allow_auth_cache=True`` is the separately gated way to run on a
    subscription sign-in. The home must be a dedicated directory that
    only this adapter uses, never the real ``~`` or ``~/.grok``.
    """
    candidates = (
        home / "auth.json",
        home / ".grok" / "auth.json",
    )
    for path in candidates:
        if path.is_file():
            raise GrokCliAdapterDisabled(
                "refusing to start with a grok auth cache present at "
                f"{path}. Pass allow_auth_cache=True only for a "
                "dedicated, adapter-only home after a deliberate "
                "sign-in."
            )


def _reject_repository(work_dir: Path) -> None:
    resolved = work_dir.resolve()
    for candidate in (resolved, *resolved.parents):
        if (candidate / ".git").exists():
            raise GrokCliAdapterDisabled(
                "refusing to run the grok CLI inside a git working tree "
                f"({resolved})"
            )
        if candidate == candidate.parent:
            break


def _reject_forbidden(argv: Sequence[str]) -> None:
    for argument in argv:
        if (
            argument in _FORBIDDEN_ARGUMENTS
            or argument.split("=", 1)[0] in _FORBIDDEN_ARGUMENTS
        ):
            raise GrokCliAdapterDisabled(
                f"refusing forbidden grok CLI argument {argument!r}. "
                "always-approve, bypassPermissions, tool allowlists, "
                "and session resume are not used."
            )


def _run_process(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    wall_timeout_seconds: float,
    stdout_byte_cap: int,
    stderr_byte_cap: int,
    terminate_grace_seconds: float,
    cancel_event: threading.Event,
) -> _Captured:
    try:
        proc = subprocess.Popen(
            list(argv),
            cwd=str(cwd),
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            bufsize=0,
        )
    except OSError as exc:
        raise GrokCliError(
            f"failed to spawn grok CLI: {exc}",
            kind="spawn_failed",
        ) from exc
    stdout_pipe = proc.stdout
    stderr_pipe = proc.stderr
    if stdout_pipe is None or stderr_pipe is None:
        _terminate_then_kill(proc, grace=terminate_grace_seconds)
        raise GrokCliError(
            "grok CLI pipes were not created",
            kind="spawn_failed",
        )
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        pgid = None
    stdout = bytearray()
    stderr = bytearray()
    streams: dict[int, tuple[Any, bytearray, int, str]] = {
        stdout_pipe.fileno(): (stdout_pipe, stdout, stdout_byte_cap, "stdout"),
        stderr_pipe.fileno(): (stderr_pipe, stderr, stderr_byte_cap, "stderr"),
    }
    for pipe, _buf, _cap, _name in streams.values():
        os.set_blocking(pipe.fileno(), False)
    deadline = time.monotonic() + wall_timeout_seconds
    timed_out = False
    cancelled = False
    truncated = False
    truncated_stream: str | None = None
    try:
        while streams:
            if cancel_event.is_set():
                cancelled = True
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            try:
                readable, _, _ = select.select(
                    list(streams),
                    [],
                    [],
                    min(0.05, remaining),
                )
            except InterruptedError:
                continue
            for fd in readable:
                pipe, buf, cap, name = streams[fd]
                try:
                    chunk = os.read(fd, 65536)
                except BlockingIOError:
                    continue
                if chunk == b"":
                    del streams[fd]
                    continue
                room = cap - len(buf)
                if len(chunk) > room:
                    if room > 0:
                        buf.extend(chunk[:room])
                    truncated = True
                    truncated_stream = name
                    break
                buf.extend(chunk)
            if truncated:
                break
        if not (timed_out or cancelled or truncated):
            # Both pipes closed. Give the CLI the rest of the wall-clock
            # budget to exit on its own, not just the kill grace period.
            try:
                proc.wait(timeout=max(deadline - time.monotonic(), 0.0))
            except subprocess.TimeoutExpired:
                timed_out = True
    finally:
        try:
            if timed_out or cancelled or truncated or proc.poll() is None:
                _terminate_then_kill(
                    proc,
                    grace=terminate_grace_seconds,
                    pgid=pgid,
                )
            elif pgid is not None:
                # The leader exited. Sweep helpers it left in the group.
                _killpg(pgid, signal.SIGKILL)
        finally:
            stdout_pipe.close()
            stderr_pipe.close()
    return _Captured(
        exit_code=proc.returncode,
        stdout=bytes(stdout),
        stderr=bytes(stderr),
        timed_out=timed_out,
        cancelled=cancelled,
        truncated=truncated,
        truncated_stream=truncated_stream,
    )


def _terminate_then_kill(
    proc: subprocess.Popen[bytes],
    *,
    grace: float,
    pgid: int | None = None,
) -> None:
    """SIGTERM the process group, then SIGKILL it, then reap the child.

    ``start_new_session=True`` put the child in its own group. ``killpg``
    hits that group, including descendants that did not leave it.
    """
    if pgid is None:
        try:
            pgid = os.getpgid(proc.pid)
        except ProcessLookupError:
            pgid = None
    if pgid is not None:
        _killpg(pgid, signal.SIGTERM)
    _wait_grace(proc, grace)
    if pgid is not None:
        _killpg(pgid, signal.SIGKILL)
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired as exc:
        raise GrokCliError(
            "failed to reap the grok CLI process group after SIGKILL",
            kind="reap_failed",
        ) from exc


def _wait_grace(proc: subprocess.Popen[bytes], grace: float) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        return


def _killpg(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        return


def _interpret(captured: _Captured) -> GrokCliResponse:
    stdout_text = _excerpt(captured.stdout)
    stderr_text = _excerpt(captured.stderr)
    if captured.timed_out:
        logger.error(
            "grok CLI wall clock expired; process group killed; "
            "no paid API fallback"
        )
        raise GrokCliTimeoutError(
            "grok CLI exceeded the wall-clock limit and its process "
            "group was killed. No paid API fallback.",
            exit_code=captured.exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
        )
    if captured.cancelled:
        logger.error(
            "grok CLI run cancelled; process group killed; "
            "no paid API fallback"
        )
        raise GrokCliCancelledError(
            "grok CLI run was cancelled and its process group was killed. "
            "No paid API fallback.",
            exit_code=captured.exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
        )
    if captured.truncated:
        stream = captured.truncated_stream or "output"
        logger.error(
            "grok CLI %s exceeded its byte cap; process group killed; "
            "no paid API fallback",
            stream,
        )
        raise GrokCliTruncatedOutputError(
            f"grok CLI {stream} exceeded its byte cap. "
            "No paid API fallback.",
            exit_code=captured.exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
        )
    if captured.exit_code is None:
        raise GrokCliError(
            "grok CLI process was not reaped",
            kind="reap_failed",
            stdout=stdout_text,
            stderr=stderr_text,
        )
    payload, parse_error = _parse_object(captured.stdout)
    detail = _failure_text(payload, stdout_text, stderr_text)
    if payload is not None and payload.get("type") == "error":
        _raise_classified(
            detail,
            exit_code=captured.exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
        )
    if captured.exit_code != 0:
        if _classify(detail) is not None:
            _raise_classified(
                detail,
                exit_code=captured.exit_code,
                stdout=stdout_text,
                stderr=stderr_text,
            )
        if captured.exit_code in (130, 143) or captured.exit_code < 0:
            raise GrokCliCancelledError(
                "grok CLI exited from a signal "
                f"({captured.exit_code}). No paid API fallback.",
                exit_code=captured.exit_code,
                stdout=stdout_text,
                stderr=stderr_text,
            )
        raise GrokCliNonZeroExitError(
            f"grok CLI exited {captured.exit_code}. No paid API fallback.",
            exit_code=captured.exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
        )
    if parse_error is not None:
        raise GrokCliMalformedOutputError(
            parse_error,
            exit_code=captured.exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
        )
    if payload is None:
        raise GrokCliMalformedOutputError(
            "grok CLI produced no JSON object",
            exit_code=captured.exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
        )
    stop_reason = payload.get("stopReason")
    if not isinstance(stop_reason, str):
        stop_reason = None
    if stop_reason is not None:
        normalized = stop_reason.strip().lower()
        if normalized in _TRUNCATED_STOP_REASONS:
            raise GrokCliTruncatedOutputError(
                f"grok CLI stopReason is {stop_reason}. "
                "No paid API fallback.",
                exit_code=captured.exit_code,
                stdout=stdout_text,
                stderr=stderr_text,
            )
        if normalized in _CANCELLED_STOP_REASONS:
            raise GrokCliCancelledError(
                f"grok CLI stopReason is {stop_reason}. "
                "No paid API fallback.",
                exit_code=captured.exit_code,
                stdout=stdout_text,
                stderr=stderr_text,
            )
    text = payload.get("text")
    if not isinstance(text, str):
        raise GrokCliMalformedOutputError(
            "grok CLI JSON object has no string text field",
            exit_code=captured.exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
        )
    available, input_tokens, output_tokens = _read_usage(payload)
    return GrokCliResponse(
        text=text,
        stop_reason=stop_reason,
        usage_available=available,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        exit_code=captured.exit_code,
    )


def _parse_object(raw: bytes) -> tuple[dict[str, Any] | None, str | None]:
    if not raw.strip():
        return None, "grok CLI stdout was empty"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, f"grok CLI stdout was not utf-8: {exc}"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"grok CLI stdout was not valid JSON: {exc}"
    if not isinstance(parsed, dict):
        return None, "grok CLI stdout JSON was not an object"
    return parsed, None


def _read_usage(
    payload: Mapping[str, Any],
) -> tuple[bool, int | None, int | None]:
    """Return token counts, or unavailable when usage cannot be trusted.

    A missing object, a non-object, a non-integer count, a boolean, or
    ``usage_is_incomplete: true`` yields null counts. Integer zero stays
    zero and is marked available. Counts are never coerced to zero.
    """
    if payload.get("usage_is_incomplete") is True:
        return False, None, None
    if "usage" not in payload or payload.get("usage") is None:
        return False, None, None
    usage = payload["usage"]
    if not isinstance(usage, dict):
        return False, None, None
    input_tokens = _optional_token(usage.get("input_tokens"))
    output_tokens = _optional_token(usage.get("output_tokens"))
    if input_tokens is None or output_tokens is None:
        return False, None, None
    return True, input_tokens, output_tokens


def _optional_token(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _failure_text(
    payload: dict[str, Any] | None,
    stdout_text: str,
    stderr_text: str,
) -> str:
    if payload is not None:
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message
    parts = [part for part in (stdout_text, stderr_text) if part.strip()]
    return "\n".join(parts)


def _classify(detail: str) -> str | None:
    lowered = detail.lower()
    if any(marker in lowered for marker in _AUTH_MARKERS):
        return "auth"
    if any(marker in lowered for marker in _QUOTA_MARKERS):
        return "quota"
    if any(marker in lowered for marker in _NETWORK_MARKERS):
        return "network"
    return None


def _raise_classified(
    detail: str,
    *,
    exit_code: int,
    stdout: str,
    stderr: str,
) -> None:
    kind = _classify(detail)
    message = (
        f"grok CLI failed ({kind or 'cli_error'}): {detail}. "
        "No paid API fallback."
    )
    logger.error("%s", message)
    kwargs: dict[str, Any] = {
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
    }
    if kind == "auth":
        raise GrokCliAuthError(message, **kwargs)
    if kind == "quota":
        raise GrokCliQuotaError(message, **kwargs)
    if kind == "network":
        raise GrokCliNetworkError(message, **kwargs)
    if exit_code != 0:
        raise GrokCliNonZeroExitError(
            f"grok CLI exited {exit_code}: {detail}. No paid API fallback.",
            **kwargs,
        )
    raise GrokCliError(message, kind="cli_error", **kwargs)


def _excerpt(raw: bytes, limit: int = 500) -> str:
    text = raw.decode("utf-8", errors="replace")
    if len(text) <= limit:
        return text
    return text[:limit]
