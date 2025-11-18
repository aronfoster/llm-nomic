"""
Tests for the configuration loaders.

This test suite validates that the loader functions can correctly read
configuration files and convert them into appropriate data models.
"""

import pytest
import yaml

from src.nomic_engine.data_models import ModelLibrary
from src.nomic_engine.utils.loaders import load_model_library


def test_load_model_library_success():
    """Test that load_model_library successfully loads the models.yml file."""
    # Load the actual models.yml file
    model_library = load_model_library()

    # Validate we got a ModelLibrary object
    assert isinstance(model_library, ModelLibrary)

    # Validate we have some models
    assert len(model_library.models) > 0

    # Validate the structure of the first model
    first_model = model_library.models[0]
    assert hasattr(first_model, "id")
    assert hasattr(first_model, "provider")
    assert hasattr(first_model, "api_model_id")
    assert hasattr(first_model, "env_key_name")

    # Check that all models have required fields
    for model in model_library.models:
        assert model.id is not None
        assert model.provider is not None
        assert model.api_model_id is not None


def test_load_model_library_file_not_found(tmp_path, monkeypatch, caplog):
    """Test that load_model_library exits gracefully when file is not found."""
    # Create a non-existent path
    non_existent_file = tmp_path / "nonexistent.yml"

    # Patch the MODEL_LIBRARY_FILE constant to point to non-existent file
    import src.nomic_engine.utils.loaders

    monkeypatch.setattr(
        src.nomic_engine.utils.loaders,
        "MODEL_LIBRARY_FILE",
        str(non_existent_file),
    )

    # Expect SystemExit to be raised
    with pytest.raises(SystemExit) as exc_info:
        load_model_library()

    # Verify exit code is 1
    assert exc_info.value.code == 1


def test_load_model_library_invalid_yaml(tmp_path, monkeypatch, caplog):
    """Test that load_model_library exits gracefully with invalid YAML."""
    # Create a temporary file with invalid YAML
    invalid_yaml_file = tmp_path / "invalid.yml"
    invalid_text = "models:\n  - id: 'test'\n    invalid: [unclosed"
    invalid_yaml_file.write_text(invalid_text)

    # Patch the MODEL_LIBRARY_FILE constant
    import src.nomic_engine.utils.loaders

    monkeypatch.setattr(
        src.nomic_engine.utils.loaders,
        "MODEL_LIBRARY_FILE",
        str(invalid_yaml_file),
    )

    # Expect SystemExit to be raised
    with pytest.raises(SystemExit) as exc_info:
        load_model_library()

    # Verify exit code is 1
    assert exc_info.value.code == 1


def test_load_model_library_invalid_structure(tmp_path, monkeypatch):
    """Test load_model_library exits gracefully with invalid structure."""
    # Create a temporary file with valid YAML but invalid model structure
    invalid_structure_file = tmp_path / "invalid_structure.yml"
    invalid_data = {
        "models": [
            {
                "id": "test-model",
                # Missing required fields: provider, api_model_id
            }
        ]
    }
    with invalid_structure_file.open("w") as f:
        yaml.safe_dump(invalid_data, f)

    # Patch the MODEL_LIBRARY_FILE constant
    import src.nomic_engine.utils.loaders

    monkeypatch.setattr(
        src.nomic_engine.utils.loaders,
        "MODEL_LIBRARY_FILE",
        str(invalid_structure_file),
    )

    # Expect SystemExit to be raised
    with pytest.raises(SystemExit) as exc_info:
        load_model_library()

    # Verify exit code is 1
    assert exc_info.value.code == 1


def test_load_model_library_validates_all_models():
    """Test that all models in the actual models.yml file are valid."""
    model_library = load_model_library()

    # Validate each model has all required fields and they're not empty
    for model in model_library.models:
        assert isinstance(model.id, str) and len(model.id) > 0
        assert isinstance(model.provider, str)
        assert len(model.provider) > 0
        assert isinstance(model.api_model_id, str)
        assert len(model.api_model_id) > 0
        # env_key_name can be None for local models
        if model.env_key_name is not None:
            assert isinstance(model.env_key_name, str)
            assert len(model.env_key_name) > 0
