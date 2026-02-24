"""
Root conftest.py — installs lightweight stubs for packages that are absent
in network-restricted environments (e.g. CI containers without PyPI access).

When the real packages ARE installed (normal dev / production environments)
this file is a no-op: every ``try: import X`` succeeds immediately and no
stub is injected.

Packages stubbed here
---------------------
* pydantic  — functional v2-compatible stub (BaseModel, Field,
              model_validator, ValidationError).  Tests that exercise
              pydantic model behaviour (construction, model_dump, round-trip
              JSON) still pass because the stub faithfully implements the
              parts of the API that the project uses.
* dotenv    — thin MagicMock (load_dotenv is never called from tests).
* anthropic / openai / google.genai
            — MagicMock stubs with real exception classes so that
              ``except OpenAIError`` / ``except anthropic.APIError`` work.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helper — only install a stub when the real package is missing
# ---------------------------------------------------------------------------

def _needs_stub(package: str) -> bool:
    try:
        __import__(package)
        return False
    except ImportError:
        return True


# ---------------------------------------------------------------------------
# Pydantic v2 functional stub
# ---------------------------------------------------------------------------

if _needs_stub("pydantic"):
    import inspect
    import json
    import typing

    _MISSING = object()  # sentinel for "no default"

    class _FieldInfo:
        """Minimal stand-in for pydantic.fields.FieldInfo."""

        def __init__(
            self,
            default: object = _MISSING,
            default_factory: object = None,
            **_kwargs: object,
        ) -> None:
            self.default = default
            self.default_factory = default_factory

    def _make_field(
        default: object = _MISSING,
        *,
        default_factory: object = None,
        **kwargs: object,
    ) -> _FieldInfo:
        """Replacement for pydantic.Field."""
        if default is ...:
            # Ellipsis means "required, no default"
            return _FieldInfo(default=_MISSING, default_factory=default_factory)
        if default is _MISSING:
            return _FieldInfo(default=_MISSING, default_factory=default_factory)
        return _FieldInfo(default=default, default_factory=default_factory)

    def _model_validator(mode: object = None) -> object:
        """Replacement for pydantic.model_validator."""

        def decorator(func: object) -> object:
            func._is_model_validator = True  # type: ignore[attr-defined]
            func._validator_mode = mode  # type: ignore[attr-defined]
            return func

        return decorator

    def _resolve_annotation(annotation: object, value: object) -> object:
        """
        If *annotation* is a BaseModel subclass (or List/Optional thereof)
        and *value* is a dict (or list of dicts), auto-construct the model(s).
        """
        origin = getattr(annotation, "__origin__", None)
        args = getattr(annotation, "__args__", ())

        # List[SomeModel]
        if origin is list and args and isinstance(value, list):
            item_type = args[0]
            if isinstance(item_type, type) and issubclass(item_type, _BaseModel):
                return [
                    item_type(**v) if isinstance(v, dict) else v
                    for v in value
                ]
            return value

        # Optional[SomeModel] = Union[SomeModel, None]
        if origin is typing.Union and value is not None:
            for arg in args:
                if isinstance(arg, type) and issubclass(arg, _BaseModel):
                    return arg(**value) if isinstance(value, dict) else value
            return value

        # SomeModel directly
        if (
            isinstance(annotation, type)
            and issubclass(annotation, _BaseModel)
            and isinstance(value, dict)
        ):
            return annotation(**value)

        return value

    class _BaseModel:
        """Minimal pydantic.BaseModel replacement."""

        def __init__(self, **kwargs: object) -> None:
            cls = type(self)

            # Resolve type hints (handles `from __future__ import annotations`)
            try:
                hints = typing.get_type_hints(cls)
            except Exception:
                hints = {}

            # Collect annotated field names + their FieldInfo from the MRO
            fields: dict[str, _FieldInfo] = {}
            for klass in reversed(cls.__mro__):
                for name in getattr(klass, "__annotations__", {}):
                    attr = klass.__dict__.get(name, _MISSING)
                    if isinstance(attr, _FieldInfo):
                        fields[name] = attr
                    elif attr is not _MISSING:
                        fields[name] = _FieldInfo(default=attr)
                    else:
                        if name not in fields:
                            fields[name] = _FieldInfo()  # required

            # Set values from kwargs or defaults
            for name, fi in fields.items():
                if name in kwargs:
                    raw = kwargs[name]
                else:
                    if fi.default_factory is not None:
                        raw = fi.default_factory()  # type: ignore[operator]
                    elif fi.default is not _MISSING:
                        raw = fi.default
                    else:
                        raise _ValidationError(
                            f"Field '{name}' is required"
                        )

                # Auto-construct nested models when value is a dict/list
                annotation = hints.get(name)
                if annotation is not None and raw is not None:
                    raw = _resolve_annotation(annotation, raw)

                setattr(self, name, raw)

            # Run @model_validator(mode="after") methods
            for attr_name in dir(cls):
                method = getattr(cls, attr_name, None)
                if (
                    callable(method)
                    and getattr(method, "_is_model_validator", False)
                    and getattr(method, "_validator_mode", None) == "after"
                ):
                    method(self)

        def _field_names(self) -> list[str]:
            names: list[str] = []
            for klass in reversed(type(self).__mro__):
                for name in getattr(klass, "__annotations__", {}):
                    if name not in names:
                        names.append(name)
            return names

        def model_dump(self) -> dict[str, object]:
            result: dict[str, object] = {}
            for name in self._field_names():
                if not hasattr(self, name):
                    continue
                value = getattr(self, name)
                if isinstance(value, _BaseModel):
                    result[name] = value.model_dump()
                elif isinstance(value, list):
                    result[name] = [
                        v.model_dump() if isinstance(v, _BaseModel) else v
                        for v in value
                    ]
                elif isinstance(value, dict):
                    result[name] = {
                        k: (
                            v.model_dump() if isinstance(v, _BaseModel) else v
                        )
                        for k, v in value.items()
                    }
                else:
                    result[name] = value
            return result

        def model_dump_json(self, *, indent: object = None) -> str:
            return json.dumps(
                self.model_dump(), default=str, indent=indent  # type: ignore[arg-type]
            )

        def model_copy(
            self, *, update: dict[str, object] | None = None, deep: bool = False
        ) -> "_BaseModel":
            """Shallow or deep copy with optional field overrides."""
            import copy

            new_obj = copy.deepcopy(self) if deep else copy.copy(self)
            if update:
                for k, v in update.items():
                    setattr(new_obj, k, v)
            return new_obj

        @classmethod
        def model_validate_json(cls, json_data: str) -> "_BaseModel":
            data = json.loads(json_data)
            return cls(**data)

    class _ValidationError(Exception):
        """Minimal stand-in for pydantic.ValidationError."""

    # Build the stub module
    _pydantic = types.ModuleType("pydantic")
    _pydantic.BaseModel = _BaseModel  # type: ignore[attr-defined]
    _pydantic.Field = _make_field  # type: ignore[attr-defined]
    _pydantic.model_validator = _model_validator  # type: ignore[attr-defined]
    _pydantic.ValidationError = _ValidationError  # type: ignore[attr-defined]

    sys.modules["pydantic"] = _pydantic
    sys.modules["pydantic.v1"] = types.ModuleType("pydantic.v1")


# ---------------------------------------------------------------------------
# LLM SDK stubs — MagicMock-backed modules with real exception classes
# so that ``except OpenAIError`` and ``except anthropic.APIError`` work.
# ---------------------------------------------------------------------------

def _make_mock_module(
    name: str,
    real_exceptions: dict[str, type] | None = None,
) -> types.ModuleType:
    """
    Return a module registered in sys.modules whose attributes resolve to
    MagicMock objects, except for *real_exceptions* which are real Exception
    subclasses (needed by ``except SomeError:`` clauses in production code).
    """
    mod = types.ModuleType(name)
    real_exceptions = real_exceptions or {}

    # Pre-populate any real exception classes
    for exc_name, exc_cls in real_exceptions.items():
        setattr(mod, exc_name, exc_cls)

    def __getattr__(attr: str) -> object:
        if attr in real_exceptions:
            return real_exceptions[attr]
        mock = MagicMock()
        setattr(mod, attr, mock)
        return mock

    mod.__getattr__ = __getattr__  # type: ignore[attr-defined]
    sys.modules[name] = mod
    return mod


if _needs_stub("openai"):

    class _OpenAIError(Exception):
        """Stub for openai.OpenAIError."""

    _make_mock_module("openai", {"OpenAIError": _OpenAIError})
    _make_mock_module("openai.types")
    _make_mock_module("openai.types.chat")

if _needs_stub("anthropic"):

    class _AnthropicAPIError(Exception):
        """Stub for anthropic.APIError."""

    _anthropic_mod = _make_mock_module(
        "anthropic", {"APIError": _AnthropicAPIError}
    )
    _make_mock_module("anthropic.types")

if _needs_stub("google"):
    _make_mock_module("google")
    _make_mock_module("google.genai")
    _make_mock_module("google.genai.types")

if _needs_stub("dotenv"):
    _make_mock_module("dotenv")

if _needs_stub("pythonjsonlogger"):
    _make_mock_module("pythonjsonlogger")
    _make_mock_module("pythonjsonlogger.json")
