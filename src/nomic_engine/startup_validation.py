"""Startup validation for the Nomic game engine.

Validates API keys and personality files for all configured LLM players and
the LLM judge before the first game turn. Human players and human judges are
skipped entirely.

Validation is fail-fast: the first failure prints a human-readable error to
stderr and exits with code 1.
"""

import sys
from typing import TYPE_CHECKING

import openai
from google import genai
from openai import OpenAI

from .config import get_api_key_from_env
from .data_models import ModelDefinition
from .judge.llm_judge import LLMJudge
from .llm.personality_loader import _PERSONALITIES_DIR
from .players.llm_player import LLMPlayer

if TYPE_CHECKING:
    from .core.game_manager import GameManager
    from .judge.base_judge import BaseJudge
    from .players.base_player import BasePlayer


def validate_startup(
    players: list["BasePlayer"],
    judge: "BaseJudge",
    game_manager: "GameManager",
) -> None:
    """Validate API keys and personality files before the first turn.

    For each LLM player:
      - Validates the API key (provider-specific logic)
      - Validates that personalities/{personality}.md exists

    For the LLM judge:
      - Validates the API key (provider-specific logic)

    Human players and human judges are skipped entirely.

    Exits with code 1 on the first failure, printing a message to stderr.

    Args:
        players: List of instantiated player objects.
        judge: The instantiated judge object.
        game_manager: The loaded GameManager (reserved for future use).
    """
    for player in players:
        if not isinstance(player, LLMPlayer):
            continue

        entity_label = f'Player "{player.player_name}"'

        # Validate API key
        error = _validate_api_key(player.model_config, entity_label)
        if error:
            print(f"ERROR: {error}", file=sys.stderr)
            sys.exit(1)

        # Validate personality file
        personality_path = _PERSONALITIES_DIR / f"{player.personality}.md"
        if not personality_path.exists():
            print(
                f"ERROR: {entity_label}: personality file not found: "
                f"personalities/{player.personality}.md",
                file=sys.stderr,
            )
            sys.exit(1)

    if isinstance(judge, LLMJudge):
        error = _validate_api_key(judge.model_config, "Judge")
        if error:
            print(f"ERROR: {error}", file=sys.stderr)
            sys.exit(1)


def _validate_api_key(
    model_config: ModelDefinition,
    entity_label: str,
) -> str | None:
    """Dispatch to the appropriate per-provider validation.

    Returns an error message string on failure, or None on success.
    """
    provider = model_config.provider
    env_key_name = model_config.env_key_name

    if provider == "anthropic":
        return _validate_anthropic(env_key_name, entity_label)
    elif provider == "openai":
        return _validate_openai(env_key_name, entity_label)
    elif provider == "xai":
        return _validate_xai(env_key_name, entity_label)
    elif provider == "google":
        return _validate_google(env_key_name, entity_label)
    elif provider == "local":
        return _validate_local(model_config, entity_label)
    else:
        return f"{entity_label}: Unknown provider '{provider}'."


def _validate_anthropic(
    env_key_name: str | None,
    entity_label: str,
) -> str | None:
    """Format-check only: key must start with 'sk-ant-'."""
    if env_key_name is None:
        return f"{entity_label} (anthropic): env_key_name not configured."

    try:
        key = get_api_key_from_env(env_key_name)
    except ValueError:
        return (
            f"{entity_label} (anthropic): API key not found or missing. "
            f"Check {env_key_name}."
        )

    if not key.startswith("sk-ant-"):
        return (
            f"{entity_label} (anthropic): API key invalid format. "
            f"Expected key starting with 'sk-ant-'."
        )

    return None


def _validate_openai(
    env_key_name: str | None,
    entity_label: str,
) -> str | None:
    """Live check: GET /v1/models via openai.OpenAI client."""
    if env_key_name is None:
        return f"{entity_label} (openai): env_key_name not configured."

    try:
        key = get_api_key_from_env(env_key_name)
    except ValueError:
        return (
            f"{entity_label} (openai): API key not found or missing. "
            f"Check {env_key_name}."
        )

    client = OpenAI(api_key=key)
    try:
        client.models.list()
    except openai.AuthenticationError:
        return (
            f"{entity_label} (openai): API key rejected (401 Unauthorized). "
            f"Check {env_key_name}."
        )
    except openai.APIError as e:
        return f"{entity_label} (openai): Could not verify API key: {e}"

    return None


def _validate_xai(
    env_key_name: str | None,
    entity_label: str,
) -> str | None:
    """Live check: GET /v1/models via openai.OpenAI against https://api.x.ai/v1."""
    if env_key_name is None:
        return f"{entity_label} (xai): env_key_name not configured."

    try:
        key = get_api_key_from_env(env_key_name)
    except ValueError:
        return (
            f"{entity_label} (xai): API key not found or missing. "
            f"Check {env_key_name}."
        )

    client = OpenAI(base_url="https://api.x.ai/v1", api_key=key)
    try:
        client.models.list()
    except openai.AuthenticationError:
        return (
            f"{entity_label} (xai): API key rejected (401 Unauthorized). "
            f"Check {env_key_name}."
        )
    except openai.APIError as e:
        return f"{entity_label} (xai): Could not verify API key: {e}"

    return None


def _validate_google(
    env_key_name: str | None,
    entity_label: str,
) -> str | None:
    """Live check: client.models.list() via google.genai.Client."""
    if env_key_name is None:
        return f"{entity_label} (google): env_key_name not configured."

    try:
        key = get_api_key_from_env(env_key_name)
    except ValueError:
        return (
            f"{entity_label} (google): API key not found or missing. "
            f"Check {env_key_name}."
        )

    client = genai.Client(api_key=key)
    try:
        # Trigger the actual HTTP request by advancing the pager one step.
        _ = next(iter(client.models.list()), None)
    except Exception:
        return (
            f"{entity_label} (google): API key rejected. Check {env_key_name}."
        )

    return None


def _validate_local(
    model_config: ModelDefinition,
    entity_label: str,
) -> str | None:
    """Live check: send a minimal generation request to the Ollama endpoint."""
    base_url = model_config.api_model_id
    model_id = model_config.id

    client = OpenAI(base_url=base_url, api_key="local")
    try:
        client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
        )
    except Exception:
        return (
            f"{entity_label} (local): Ollama unreachable at {base_url} "
            f"or model '{model_id}' not loaded."
        )

    return None
