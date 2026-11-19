"""Install offline guards before any test module imports the app.

The Makefile runs pytest with ``PYTHONPATH=.:src`` and does not load a
sitecustomize audit hook. This file is the hook pytest itself loads
before collection. It hides provider credentials and ``.env`` files,
and it blocks the synchronous TCP connect path unless a test opts in.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.offline_guard import blocked_destinations, install_offline_guards

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
