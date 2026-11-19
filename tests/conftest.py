"""Install offline guards before any test module imports the app.

The Makefile runs pytest with ``PYTHONPATH=.:src`` and does not load a
sitecustomize audit hook. This file is the hook pytest itself loads
before collection. It hides provider credentials and ``.env`` files.
Inside this process it blocks synchronous TCP connects, non-loopback
DNS lookups, and non-loopback UDP sends unless a test opts in.
A subprocess is not covered.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from tests.offline_guard import (
    PROVIDER_CREDENTIAL_ENV_VARS,
    blocked_destinations,
    install_offline_guards,
    scrub_provider_credentials,
)

# Before collection, so an import cannot see inherited provider keys.
install_offline_guards()


def pytest_collection_finish() -> None:
    """Fail if importing the suite already tried to open a connection."""
    if not blocked_destinations:
        return
    destinations = ", ".join(repr(item) for item in blocked_destinations)
    raise pytest.UsageError(
        "importing the test suite tried to open a network connection "
        f"to {destinations}"
    )


@pytest.fixture(autouse=True)
def _scrub_provider_credentials_each_test(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Drop provider credentials before and after every test.

    The session scrub covers collection. This fixture covers a test that
    assigns ``os.environ[name]`` directly: ``monkeypatch`` restores the
    pre-test value, and the final scrub removes a value that restore
    would otherwise put back.
    """
    for name in PROVIDER_CREDENTIAL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    yield
    scrub_provider_credentials(os.environ)


@pytest.fixture(autouse=True)
def _offline_network_stays_blocked(
    request: pytest.FixtureRequest,
) -> Iterator[None]:
    """Fail tests that try to connect, except the deliberate proof.

    The guard raises before the OS connect. This fixture turns that into
    a test failure so a future test cannot reach a live provider or the
    Ollama ping in ``startup_validation`` by forgetting a mock.
    ``attempts_network`` marks the test that proves the block happens
    before any bytes are sent.
    """
    start = len(blocked_destinations)
    yield
    if request.node.get_closest_marker("attempts_network") is not None:
        return
    attempted = blocked_destinations[start:]
    if not attempted:
        return
    destinations = ", ".join(repr(item) for item in attempted)
    pytest.fail(
        "offline tests blocked an unexpected network connection to "
        f"{destinations}",
        pytrace=False,
    )
