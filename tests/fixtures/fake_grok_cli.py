"""Stand-in for the grok CLI. It never opens a socket.

The adapter passes ``<mode> <payload>`` before the grok flags. Payload is
a dump path or a directory, depending on the mode. This process is not
the pytest process, so it must stay offline by itself.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path


def main(argv: list[str]) -> int:
    args = argv[1:]
    mode = "valid"
    payload: str | None = None
    if args and not args[0].startswith("-"):
        mode = args.pop(0)
    if args and not args[0].startswith("-"):
        payload = args.pop(0)
    if mode == "valid":
        _dump(payload)
        _emit(_success(3, 1))
        return 0
    if mode == "zero-usage":
        _emit(_success(0, 0))
        return 0
    if mode == "missing-usage":
        body = _success(1, 1)
        del body["usage"]
        _emit(body)
        return 0
    if mode == "malformed-usage":
        body = _success(1, 1)
        body["usage"] = "not-an-object"
        _emit(body)
        return 0
    if mode == "bool-usage":
        body = _success(1, 1)
        body["usage"] = {"input_tokens": True, "output_tokens": 1}
        _emit(body)
        return 0
    if mode == "incomplete-usage":
        body = _success(4, 5)
        body["usage_is_incomplete"] = True
        _emit(body)
        return 0
    if mode == "auth":
        _emit({"type": "error", "message": "Run grok login first"})
        return 1
    if mode == "quota":
        _emit({"type": "error", "message": "429 rate limit exceeded"})
        return 1
    if mode == "network":
        _emit({"type": "error", "message": "network connection refused"})
        return 1
    if mode == "network-stderr":
        sys.stderr.write("connection refused\n")
        return 1
    if mode == "malformed":
        sys.stdout.write("{")
        return 0
    if mode == "nonzero":
        _emit(_success(1, 1))
        return 4
    if mode == "stop-truncated":
        body = _success(2, 2)
        body["stopReason"] = "max_tokens"
        _emit(body)
        return 0
    if mode == "stop-cancelled":
        body = _success(2, 2)
        body["stopReason"] = "cancelled"
        _emit(body)
        return 0
    if mode == "flood-stdout":
        _write_pid(payload)
        _flood(sys.stdout.buffer)
        return 0
    if mode == "flood-stderr":
        _write_pid(payload)
        _flood(sys.stderr.buffer)
        return 0
    if mode == "cancel":
        _write_pid(payload)
        if payload is not None:
            (Path(payload) / "ready").write_text("ready\n")
        _sleep_until_killed()
        return 0
    if mode == "slow-exit":
        _emit(_success(3, 1))
        os.close(1)
        os.close(2)
        time.sleep(1.0)
        return 0
    if mode == "descendant-ok":
        _descendant_then_succeed(payload)
        return 0
    if mode == "timeout-descendant":
        _timeout_descendant(payload)
        return 0
    sys.stderr.write(f"unknown fake grok mode {mode}\n")
    return 2


def _success(input_tokens: int, output_tokens: int) -> dict[str, object]:
    return {
        "text": "hello from the fake cli",
        "stopReason": "end_turn",
        "sessionId": "session-offline",
        "requestId": "request-offline",
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
    }


def _emit(body: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(body))
    sys.stdout.flush()


def _dump(payload: str | None) -> None:
    if payload is None:
        return
    Path(payload).write_text(
        json.dumps(
            {
                "argv": sys.argv,
                "cwd": os.getcwd(),
                "env": dict(os.environ),
            }
        ),
        encoding="utf-8",
    )


def _write_pid(payload: str | None) -> None:
    if payload is None:
        return
    (Path(payload) / "pid").write_text(str(os.getpid()), encoding="utf-8")


def _flood(stream: object) -> None:
    chunk = b"x" * 4096
    write = getattr(stream, "write")
    flush = getattr(stream, "flush")
    while True:
        write(chunk)
        flush()


def _sleep_until_killed() -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            time.sleep(0.05)
        except InterruptedError:
            continue


def _timeout_descendant(payload: str | None) -> None:
    if payload is None:
        sys.stderr.write("timeout-descendant requires a payload directory\n")
        sys.exit(2)
    root = Path(payload)
    _record_term(root / "parent-term")
    (root / "parent.pid").write_text(str(os.getpid()), encoding="utf-8")
    pid = os.fork()
    if pid == 0:
        try:
            _record_term(root / "child-term")
            (root / "child.pid").write_text(str(os.getpid()), encoding="utf-8")
            _sleep_until_killed()
        finally:
            os._exit(0)
    _sleep_until_killed()


def _descendant_then_succeed(payload: str | None) -> None:
    if payload is None:
        sys.stderr.write("descendant-ok requires a payload directory\n")
        sys.exit(2)
    root = Path(payload)
    pid = os.fork()
    if pid == 0:
        try:
            os.close(1)
            os.close(2)
            (root / "child.pid").write_text(str(os.getpid()), encoding="utf-8")
            _sleep_until_killed()
        finally:
            os._exit(0)
    deadline = time.monotonic() + 5
    while not (root / "child.pid").exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    _emit(_success(3, 1))


def _record_term(path: Path) -> None:
    def _handler(_signum: int, _frame: object) -> None:
        path.write_text("term\n", encoding="utf-8")

    signal.signal(signal.SIGTERM, _handler)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except BrokenPipeError:
        raise SystemExit(0) from None
