"""
Handles secure loading of API keys from environment variables.
"""

import logging
import os

from dotenv import load_dotenv

# Set up a basic logger
logger = logging.getLogger(__name__)


def load_env_vars() -> None:
    """Load environment variables from a .env file.

    ``python-dotenv`` walks upward from this file until it finds ``.env``,
    so a checkout or parent-directory file is used when a game is started.
    Call this from the application entry point. Importing the module must
    not load that file: tests and other importers would otherwise pick up
    real provider credentials.
    """
    load_dotenv()
    logger.info("Loaded environment variables from .env file (if found).")


def get_api_key_from_env(env_key_name: str) -> str:
    """
    Get the API key for a given environment variable name.

    Raises:
        ValueError: If the required API key is not found.
    """
    api_key = os.getenv(env_key_name)
    if not api_key or api_key == "YOUR_KEY_HERE":
        raise ValueError(
            f"API key '{env_key_name}' not found in environment "
            f"variables. Please check your .env file."
        )

    return api_key
