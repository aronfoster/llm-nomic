"""One bounded command for a first game on a subscription sign-in.

    python -m src.nomic_engine.live_run grok-cli --dry-run
    python -m src.nomic_engine.live_run grok-cli \\
        --acknowledge-unverified-tool-isolation

``--dry-run`` creates nothing, spawns nothing, and prints the plan: the
players, every cap, the sign-in command and the exact CLI argv. A live
run refuses to start without the acknowledgement flag, without an
absolute CLI path, or inside the real ``~`` / ``~/.grok``. All caps
come from the game's ``budget`` block, so the existing usage guard stops
the run before the next call. There is no paid API fallback and no API
key is read.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from .data_models import (
    JudgeType,
    ModelDefinition,
    PlayerConfig,
    UsageBudget,
)
from .game_creator import create_game_files, load_initial_rules
from .llm.api_clients import (
    ApiClientProtocol,
    clear_grok_cli_client_builder,
    register_grok_cli_client_builder,
)
from .llm.providers.grok_cli_adapter import (
    build_grok_cli_argv,
    select_grok_cli_adapter,
)
from .llm.providers.grok_cli_client import GrokCliApiClient
from .usage_budget import LlmCallOptions

MODEL_ID = "grok-cli"
PLAYER_NAMES = ("Ada", "Grace")
DEFAULT_HOME = Path.home() / ".nomic-grok-home"
EXIT_REFUSED = 2


@dataclass(frozen=True)
class LiveRunPlan:
    """Everything a live run will do, decided before anything starts."""

    grok_path: Path
    home_dir: Path
    games_dir: Path
    turns: int
    max_calls: int
    max_tokens: int | None
    max_wall_seconds: float
    call_timeout_seconds: float
    target_score: int

    @property
    def budget(self) -> UsageBudget:
        return UsageBudget(
            max_calls_per_game=self.max_calls,
            max_total_tokens_per_game=self.max_tokens,
            max_wall_seconds=self.max_wall_seconds,
            per_call_timeout_seconds=self.call_timeout_seconds,
        )

    @property
    def login_command(self) -> str:
        grok_home = self.home_dir / ".grok"
        return (
            f"HOME={self.home_dir} GROK_HOME={grok_home} "
            f"{self.grok_path} login --device-auth"
        )

    @property
    def signed_in(self) -> bool:
        grok_home = self.home_dir / ".grok"
        return grok_home.is_dir() and any(grok_home.iterdir())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.nomic_engine.live_run",
        description="Bounded game on a subscription sign-in.",
    )
    parser.add_argument("provider", choices=["grok-cli"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--acknowledge-unverified-tool-isolation",
        action="store_true",
        help=(
            "Required for a live run. The grok CLI is an agent: its tool, "
            "MCP, hook and plugin isolation is not proven for 1.0.89."
        ),
    )
    parser.add_argument("--grok-path", default=None)
    parser.add_argument("--home", default=str(DEFAULT_HOME))
    parser.add_argument("--games-dir", default="games")
    parser.add_argument("--turns", type=int, default=2)
    parser.add_argument("--max-calls", type=int, default=40)
    parser.add_argument("--max-tokens", type=int, default=200_000)
    parser.add_argument(
        "--allow-missing-usage",
        action="store_true",
        help=(
            "Drop the token cap. Use only if the CLI reports no usage, "
            "so the call and time caps are the only bounds."
        ),
    )
    parser.add_argument("--max-wall-seconds", type=float, default=1200.0)
    parser.add_argument("--call-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--target-score", type=int, default=100)
    return parser


def resolve_plan(args: argparse.Namespace) -> LiveRunPlan | str:
    """Return a plan, or the reason it must be refused."""
    raw = args.grok_path or shutil.which("grok")
    if not raw:
        return "grok CLI not found. Pass --grok-path /absolute/path/to/grok."
    grok_path = Path(raw).expanduser()
    if not grok_path.is_absolute() or not grok_path.is_file():
        return f"--grok-path must be an existing absolute file: {grok_path}"
    home_dir = Path(args.home).expanduser().resolve()
    real_home = Path.home().resolve()
    if home_dir in (real_home, real_home / ".grok"):
        return "refusing your real home and ~/.grok; use a dedicated --home"
    if args.turns < 1 or args.max_calls < 1:
        return "--turns and --max-calls must be at least 1"
    return LiveRunPlan(
        grok_path=grok_path,
        home_dir=home_dir,
        games_dir=Path(args.games_dir),
        turns=args.turns,
        max_calls=args.max_calls,
        max_tokens=None if args.allow_missing_usage else args.max_tokens,
        max_wall_seconds=args.max_wall_seconds,
        call_timeout_seconds=args.call_timeout_seconds,
        target_score=args.target_score,
    )


def describe(plan: LiveRunPlan) -> str:
    """Plain-text plan, including the exact CLI argv sample."""
    argv = build_grok_cli_argv(
        (str(plan.grok_path),),
        "<prompt>",
        work_dir=plan.home_dir / "tmp" / "<work-dir>",
        model=None,
    )
    tokens = plan.max_tokens if plan.max_tokens is not None else "NONE"
    lines = [
        "Live run plan (grok CLI, subscription sign-in, no API key)",
        f"  players        : {', '.join(PLAYER_NAMES)} + LLM judge, all "
        f"model '{MODEL_ID}'",
        f"  turns          : {plan.turns}",
        f"  max calls      : {plan.max_calls} (retries count)",
        f"  max tokens     : {tokens} (a call with unknown usage stops "
        "the next call)",
        f"  max wall time  : {plan.max_wall_seconds:.0f}s",
        f"  per-call limit : {plan.call_timeout_seconds:.0f}s",
        f"  sign-in home   : {plan.home_dir} (dedicated, not ~)",
        f"  signed in      : {'yes' if plan.signed_in else 'NO'}",
        f"  game directory : {plan.games_dir}/live-<timestamp>",
        "  sign-in command (run once, on this computer):",
        f"    {plan.login_command}",
        "  each model call runs (prompt elided):",
        f"    {' '.join(argv)}",
    ]
    return "\n".join(lines)


def create_live_game(plan: LiveRunPlan) -> Path:
    """Create a bounded two-player game directory under games/."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    game_dir = plan.games_dir / f"live-{stamp}"
    model = ModelDefinition(
        id=MODEL_ID,
        provider="grok_cli",
        api_model_id="default",
        env_key_name=None,
    )
    create_game_files(
        game_dir=game_dir,
        players=[
            PlayerConfig(name=name, model_id=MODEL_ID, personality="none")
            for name in PLAYER_NAMES
        ],
        initial_rules=load_initial_rules(),
        judge_type=JudgeType.LLM,
        judge_model=model,
        target_score=plan.target_score,
    )
    config_path = game_dir / "config.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["budget"] = plan.budget.model_dump(mode="json")
    config["tuning"] = {
        "max_propose_retries": 2,
        "max_discuss_retries": 2,
        "max_revise_retries": 2,
        "max_vote_retries": 2,
        "max_judge_veto_retries": 2,
        "max_judge_score_retries": 2,
        "max_judge_maintain_state_retries": 2,
    }
    config["withdrawal_policy"] = "forfeit"
    config["max_withdrawal_retries"] = 0
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), "utf-8")
    return game_dir


def make_builder(
    plan: LiveRunPlan,
) -> Callable[[ModelDefinition, LlmCallOptions], ApiClientProtocol]:
    """Return the factory hook that builds one adapter per game actor."""

    def build(
        model: ModelDefinition, options: LlmCallOptions
    ) -> ApiClientProtocol:
        timeout = options.per_call_timeout_seconds
        adapter = select_grok_cli_adapter(
            enabled=True,
            acknowledge_unverified_tool_isolation=True,
            executable=(str(plan.grok_path),),
            home_dir=plan.home_dir,
            wall_timeout_seconds=timeout or plan.call_timeout_seconds,
            stdout_byte_cap=1_000_000,
            stderr_byte_cap=100_000,
            model=(
                None
                if model.api_model_id == "default"
                else (model.api_model_id)
            ),
            allow_auth_cache=True,
        )
        return GrokCliApiClient(adapter)

    return build


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    plan = resolve_plan(args)
    if isinstance(plan, str):
        print(f"refused: {plan}", file=sys.stderr)
        return EXIT_REFUSED
    print(describe(plan))
    if args.dry_run:
        print("\nDry run: nothing was created and nothing was started.")
        return 0
    if not args.acknowledge_unverified_tool_isolation:
        print(
            "\nrefused: pass --acknowledge-unverified-tool-isolation to "
            "run live. The CLI is an agent and its tool isolation is not "
            "proven.",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    if not plan.signed_in:
        print(
            "\nrefused: no sign-in found. Run the sign-in command above "
            "once, then re-run.",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    from .main import run_game

    game_dir = create_live_game(plan)
    print(f"\nStarting live game in {game_dir}")
    register_grok_cli_client_builder(make_builder(plan))
    try:
        run_game(str(game_dir), max_turns=plan.turns)
    finally:
        clear_grok_cli_client_builder()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
