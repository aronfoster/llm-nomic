"""
Utility functions for loading configuration and data files.

This module provides reusable loaders for model library and other
configuration files.
"""

import logging
import sys
from pathlib import Path

import yaml

from ..constants import MODEL_LIBRARY_FILE
from ..data_models import ModelLibrary

logger = logging.getLogger(__name__)


def load_model_library() -> ModelLibrary:
    """
    Load the model library from models.yml.

    Returns:
        ModelLibrary object

    Raises:
        SystemExit: If the file is not found or validation fails
    """
    models_file = Path(MODEL_LIBRARY_FILE)
    try:
        logger.info(f"Loading model library from {models_file}")
        with models_file.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        model_library = ModelLibrary(**data)
        logger.info(f"Successfully loaded {len(model_library.models)} models")
        return model_library
    except FileNotFoundError:
        logger.error(f"Model library file not found: {models_file}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to load or validate model library: {e}")
        sys.exit(1)
