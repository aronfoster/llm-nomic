"""
Handles secure loading of API keys and project configuration.
Loads keys from a .env file, which is NOT committed to git.
"""

import os
import logging
from dotenv import load_dotenv

# Set up a basic logger
logger = logging.getLogger(__name__)

def load_env_vars() -> None:
    """Load environment variables from a .env file."""
    # This will search for a .env file in the current dir or parent dirs
    load_dotenv()
    logger.info("Loaded environment variables from .env file (if found).")

def get_api_key(model_id: str) -> str:
    """
    Get the API key for a given model_id from environment variables.

    Raises:
        ValueError: If the required API key is not found.
    """
    # Simple mapping of model_id fragments to environment variable names
    if 'gpt-' in model_id:
        key_name = 'OPENAI_API_KEY'
    elif 'claude-' in model_id:
        key_name = 'ANTHROPIC_API_KEY'
    elif 'gemini-' in model_id:
        key_name = 'GOOGLE_API_KEY'
    elif 'grok-' in model_id:
        # Note: Grok/xAI API might have a different key name
        key_name = 'X_API_KEY' # Placeholder
    else:
        raise ValueError(f"No API key mapping found for model_id: {model_id}")

    api_key = os.getenv(key_name)
    if not api_key:
        raise ValueError(f"API key '{key_name}' not found in environment variables.")

    return api_key

# Load environment variables once on module import
load_env_vars()
