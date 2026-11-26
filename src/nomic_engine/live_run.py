"""One-command bounded game on a signed-in ChatGPT plan (no API key).

    python -m src.nomic_engine.live_run openai-chatgpt-plan login
    python -m src.nomic_engine.live_run openai-chatgpt-plan status
    python -m src.nomic_engine.live_run openai-chatgpt-plan models
    python -m src.nomic_engine.live_run openai-chatgpt-plan --dry-run
    python -m src.nomic_engine.live_run openai-chatgpt-plan
    python -m src.nomic_engine.live_run openai-chatgpt-plan logout

``login`` opens the browser for Sign in with ChatGPT and saves an
owner-only credential file (default ``~/.config/llm-nomic/``). The run
is a two-player game with an LLM judge, capped by calls, tokens, wall
time and per-call timeout. A call whose usage is unknown stops the game
at the next call while a token cap is set. See docs/LIVE_RUN.md.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml

from .data_models import JudgeType, ModelDefinition, PlayerConfig, UsageBudget
from .game_creator import create_game_files, load_initial_rules
from .llm import chatgpt_oauth as oauth
from .llm.api_clients import (
    clear_chatgpt_plan_token_provider,
    register_chatgpt_plan_token_provider,
)
from .llm.chatgpt_plan_client import PROVIDER
from .utils.loaders import load_model_library

MODEL_ID = "chatgpt-plan"
PLAYER_NAMES = ("Ada", "Grace")
EXIT_REFUSED = 2
MODELS_URL = "https://api.openai.com/v1/models"
ACTIONS = ("run", "login", "logout", "status", "models")


@dataclass(frozen=True)
class LiveRunPlan:
    """Everything a live run will do, decided before anything starts."""

    config_dir: Path
    games_dir: Path
    model: ModelDefinition
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.nomic_engine.live_run",
        description="Bounded game on a ChatGPT plan via Sign in with ChatGPT.",
    )
    parser.add_argument("provider", choices=["openai-chatgpt-plan"])
    parser.add_argument("action", nargs="?", default="run", choices=ACTIONS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--config-dir",
        default=None,
        help=(
            "Credential directory (default $LLM_NOMIC_CONFIG_DIR or "
            "~/.config/llm-nomic). Must be outside the repository."
        ),
    )
    parser.add_argument(
        "--port", type=int, default=oauth.DEFAULT_CALLBACK_PORT
    )
    parser.add_argument("--games-dir", default="games")
    parser.add_argument("--turns", type=int, default=2)
    parser.add_argument("--max-calls", type=int, default=40)
    parser.add_argument("--max-tokens", type=int, default=200_000)
    parser.add_argument(
        "--allow-missing-usage",
        action="store_true",
        help="Drop the token cap; only call and time caps then apply.",
    )
    parser.add_argument("--max-wall-seconds", type=float, default=1200.0)
    parser.add_argument("--call-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--target-score", type=int, default=100)
    return parser


def _store(args: argparse.Namespace) -> oauth.CredentialStore:
    return oauth.CredentialStore(args.config_dir)


def _library_model() -> ModelDefinition | str:
    for model in load_model_library().models:
        if model.id == MODEL_ID:
            if model.provider != PROVIDER:
                return f"models.yml entry {MODEL_ID} must use {PROVIDER}"
            return model
    return f"config/models.yml has no '{MODEL_ID}' entry"


def resolve_plan(
    args: argparse.Namespace, store: oauth.CredentialStore
) -> LiveRunPlan | str:
    for name in ("turns", "max_calls", "max_tokens", "target_score"):
        if getattr(args, name) <= 0:
            return f"--{name.replace('_', '-')} must be positive"
    if args.max_wall_seconds <= 0 or args.call_timeout_seconds <= 0:
        return "time limits must be positive"
    model = _library_model()
    if isinstance(model, str):
        return model
    return LiveRunPlan(
        config_dir=store.directory,
        games_dir=Path(args.games_dir),
        model=model,
        turns=args.turns,
        max_calls=args.max_calls,
        max_tokens=None if args.allow_missing_usage else args.max_tokens,
        max_wall_seconds=args.max_wall_seconds,
        call_timeout_seconds=args.call_timeout_seconds,
        target_score=args.target_score,
    )


def _signed_in(store: oauth.CredentialStore) -> oauth.ChatGptCredential | None:
    cred = store.load()
    if cred is None or not cred.refresh_token or not cred.has_plan_usage():
        return None
    return cred


def describe(plan: LiveRunPlan, cred: oauth.ChatGptCredential | None) -> str:
    tokens = plan.max_tokens if plan.max_tokens is not None else "NONE"
    who = f"yes ({cred.email or cred.subject})" if cred else "NO"
    lines = [
        "Live run plan (ChatGPT plan via Sign in with ChatGPT, no API key)",
        f"  players        : {', '.join(PLAYER_NAMES)} + LLM judge, all "
        f"'{MODEL_ID}' -> model '{plan.model.api_model_id}'",
        "  endpoint       : POST https://api.openai.com/v1/responses "
        "(store=false, stream=true)",
        f"  turns          : {plan.turns}",
        f"  max calls      : {plan.max_calls} (retries count)",
        f"  max tokens     : {tokens} (unknown usage stops the next call)",
        f"  max wall time  : {plan.max_wall_seconds:.0f}s",
        f"  per-call limit : {plan.call_timeout_seconds:.0f}s",
        f"  credentials    : {plan.config_dir / oauth.CREDENTIAL_FILENAME}",
        f"  signed in      : {who}",
        f"  game directory : {plan.games_dir}/live-<timestamp>",
        "  billing        : your ChatGPT plan's usage limits; no API "
        "key, no pay-as-you-go charge",
    ]
    return "\n".join(lines)


def create_live_game(plan: LiveRunPlan) -> Path:
    """Create a bounded two-player game directory under games/."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    game_dir = plan.games_dir / f"live-{stamp}"
    create_game_files(
        game_dir=game_dir,
        players=[
            PlayerConfig(name=name, model_id=MODEL_ID, personality="none")
            for name in PLAYER_NAMES
        ],
        initial_rules=load_initial_rules(),
        judge_type=JudgeType.LLM,
        judge_model=plan.model,
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


def _login(args: argparse.Namespace, store: oauth.CredentialStore) -> int:
    cred = oauth.sign_in(store, port=args.port)
    print(
        f"Signed in as {cred.email or cred.subject}; plan usage granted. "
        f"Credentials saved to {store.credential_path} (mode 0600)."
    )
    return 0


def _logout(store: oauth.CredentialStore) -> int:
    with httpx.Client(timeout=30.0) as http:
        revoked = oauth.sign_out(store, http=http)
    print(
        "Signed out; tokens cleared."
        if revoked
        else "Tokens cleared locally; remote revocation was NOT confirmed. "
        "Disconnect llm-nomic in ChatGPT Settings to be sure."
    )
    return 0


def _status(store: oauth.CredentialStore) -> int:
    cred = _signed_in(store)
    if cred is None:
        print(f"Not signed in ({store.credential_path}).")
        return EXIT_REFUSED
    expires = time.strftime(
        "%Y-%m-%d %H:%M %Z", time.localtime(cred.expires_at)
    )
    print(
        f"Signed in as {cred.email or cred.subject}; access token expires "
        f"{expires} and refreshes automatically. Scopes: "
        f"{' '.join(cred.scopes)}"
    )
    return 0


def _models(store: oauth.CredentialStore) -> int:
    """List the account's model slugs (no inference, no plan usage)."""
    provider = oauth.ChatGptTokenProvider(store)
    token = provider.access_token()
    with httpx.Client(timeout=30.0) as http:
        response = http.get(
            MODELS_URL, headers={"Authorization": f"Bearer {token}"}
        )
    if response.status_code != 200:
        print(
            f"Model list failed: HTTP {response.status_code}", file=sys.stderr
        )
        return 1
    data = response.json()
    entries = data.get("models") or data.get("data") or []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("visibility", "list") != "list":
            continue
        slug = entry.get("slug") or entry.get("id")
        print(f"{slug}\t{entry.get('display_name', '')}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        store = _store(args)
        if args.action == "login":
            return _login(args, store)
        if args.action == "logout":
            return _logout(store)
        if args.action == "status":
            return _status(store)
        if args.action == "models":
            return _models(store)
        plan = resolve_plan(args, store)
        if isinstance(plan, str):
            print(f"refused: {plan}", file=sys.stderr)
            return EXIT_REFUSED
        cred = _signed_in(store)
        print(describe(plan, cred))
        if args.dry_run:
            print("\nDry run: nothing was created and nothing was started.")
            return 0
        if cred is None:
            print(
                "\nrefused: not signed in. Run:\n  python -m "
                "src.nomic_engine.live_run openai-chatgpt-plan login",
                file=sys.stderr,
            )
            return EXIT_REFUSED
    except oauth.ChatGptAuthError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    from .main import run_game

    game_dir = create_live_game(plan)
    print(f"\nStarting live game in {game_dir}")
    register_chatgpt_plan_token_provider(oauth.ChatGptTokenProvider(store))
    try:
        run_game(str(game_dir), max_turns=plan.turns)
    except SystemExit as exc:
        # run_game exits nonzero when a cap stops the game; state is saved.
        code = exc.code if isinstance(exc.code, int) else 1
        print(f"\nGame stopped (exit {code}); partial state in {game_dir}")
        return code
    finally:
        clear_chatgpt_plan_token_provider()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
