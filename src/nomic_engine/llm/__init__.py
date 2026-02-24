"""LLM-specific components for Nomic game."""

from . import prompts
from .api_clients import (
    AnthropicApiClient,
    ApiClientProtocol,
    GoogleApiClient,
    OpenAICompatibleApiClient,
    create_api_client,
)
from .parsers import (
    parse_discussion_response,
    parse_proposal_response,
    parse_revision_response,
    parse_vote_response,
)
from .personality_loader import load_personality, parse_section_fields
from .prompt_builder import PromptBuilder

# Backward-compatible alias
ApiClient = create_api_client

__all__ = [
    "ApiClient",
    "ApiClientProtocol",
    "AnthropicApiClient",
    "GoogleApiClient",
    "OpenAICompatibleApiClient",
    "PromptBuilder",
    "create_api_client",
    "load_personality",
    "parse_section_fields",
    "parse_discussion_response",
    "parse_proposal_response",
    "parse_revision_response",
    "parse_vote_response",
    "prompts",
]
