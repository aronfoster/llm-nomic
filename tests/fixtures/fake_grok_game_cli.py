"""Stand-in for ``grok -p ... --output-format json`` that plays Nomic.

Offline by construction: it only reads argv and writes JSON. Each call
is one process, like the real CLI. Flags before the grok flags select a
mode: ``--no-usage`` omits the usage object and ``--log PATH`` appends
one JSON line per call (phase, argv, env keys, HOME, cwd).
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType


def _load_replies() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripted_replies.py"
    spec = importlib.util.spec_from_file_location("scripted_replies", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: list[str]) -> int:
    replies = _load_replies()
    args = argv[1:]
    no_usage = False
    log: str | None = None
    while args and args[0] in ("--no-usage", "--log"):
        flag = args.pop(0)
        if flag == "--no-usage":
            no_usage = True
        else:
            log = args.pop(0)
    prompt = args[args.index("-p") + 1]
    phase = replies.phase_of(prompt)
    if log:
        entry = {
            "phase": phase,
            "argv": args[: args.index("-p")],
            "env_keys": sorted(os.environ),
            "home": os.environ.get("HOME"),
            "cwd": os.getcwd(),
        }
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
    last_user = max(prompt.rfind("=== USER ==="), 0)
    text = replies.reply_for(
        phase,
        owner="cli",
        score_delta=3,
        proposal_count=1,
        context=prompt,
        last_prompt=prompt[last_user:],
    )
    body: dict[str, object] = {
        "text": text,
        "stopReason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    if no_usage:
        del body["usage"]
    sys.stdout.write(json.dumps(body))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
