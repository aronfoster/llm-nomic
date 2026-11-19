"""Guards that keep pytest from using live credentials or the network.

Imported by ``tests/conftest.py`` before test modules import the app.
The application does not use this module. Running the game still loads
``.env`` from ``load_env_vars()``.
"""

from __future__ import annotations

import os
import socket
import sys
from collections.abc import MutableMapping

# Names read by this project's providers and by the SDKs they construct.
# Scrubbing these at pytest startup means a credential inherited from the
# shell, a parent process, or an earlier ``.env`` load is not visible to
# tests. Tests that need a fake key set it themselves afterwards.
PROVIDER_CREDENTIAL_ENV_VARS: frozenset[str] = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_FOUNDRY_API_KEY",
        "AZURE_OPENAI_AD_TOKEN",
        "AZURE_OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GROK_API_KEY",
        "OPENAI_ADMIN_KEY",
        "OPENAI_API_KEY",
        "OPENAI_ORG_ID",
        "OPENAI_PROJECT_ID",
        "OPENAI_WEBHOOK_SECRET",
        "XAI_API_KEY",
    }
)

# python-dotenv treats these values as "do not read a .env file".
_DOTENV_DISABLED = "PYTHON_DOTENV_DISABLED"

# Destinations a test tried to connect to. ``create_connection`` and
# ``socket.connect`` append here and then raise, before the OS connects
# and before any bytes are written.
blocked_destinations: list[object] = []

_INSTALLED = False


class OfflineNetworkBlocked(OSError):
    """A test tried to open a real connection.

    Raised from the socket layer before ``connect`` runs, so no request
    bytes are transmitted.
    """


def scrub_provider_credentials(
    environ: MutableMapping[str, str],
) -> list[str]:
    """Remove provider credentials from ``environ``.

    Returns the names that were present. Values are not reported.
    """
    removed: list[str] = []
    for name in PROVIDER_CREDENTIAL_ENV_VARS:
        if name in environ:
            del environ[name]
            removed.append(name)
    return removed


def caused_by_offline_block(exc: BaseException) -> bool:
    """True when the offline guard blocked the socket behind ``exc``."""
    seen: set[int] = set()
    stack: list[BaseException | None] = [exc]
    while stack:
        current = stack.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, OfflineNetworkBlocked):
            return True
        stack.append(current.__cause__)
        stack.append(current.__context__)
    return False


def _refuse_dotenv(*_args: object, **_kwargs: object) -> bool:
    """Ignore ``.env`` files for the whole pytest process."""
    return False


def _block_dotenv_loader() -> None:
    """Stop ``load_dotenv`` from reading a checkout or parent ``.env``.

    ``PYTHON_DOTENV_DISABLED`` is python-dotenv's own switch, checked
    when ``load_dotenv`` runs. Replacing the function as well covers a
    test that unsets the variable and then calls ``load_env_vars()``.
    ``config.py`` binds ``load_dotenv`` at import, which happens after
    this runs, so it receives the replacement.
    """
    os.environ[_DOTENV_DISABLED] = "1"

    import dotenv

    dotenv.load_dotenv = _refuse_dotenv
    for module_name in ("src.nomic_engine.config", "nomic_engine.config"):
        module = sys.modules.get(module_name)
        if module is not None:
            module.load_dotenv = _refuse_dotenv


def _block_network() -> None:
    """Fail the synchronous TCP connect path before any bytes are sent.

    ``create_connection``, ``connect``, and ``connect_ex`` raise before
    the operating system connects. That is the path httpx and the
    provider SDKs use for a normal request. Subprocesses, UDP, and a
    raw ``getaddrinfo`` call are outside this guard. ``socket.socket``
    itself stays in place so client construction still works, including
    the SOCKS test that replaces ``socket.socket``.
    """

    def _blocked_create_connection(
        address: object,
        timeout: object = None,
        source_address: object = None,
        *,
        all_errors: bool = False,
    ) -> socket.socket:
        # timeout, source_address, and all_errors match the stdlib
        # signature. The guard rejects the call before using them.
        _ = (timeout, source_address, all_errors)
        blocked_destinations.append(address)
        raise OfflineNetworkBlocked(
            "offline tests blocked a connection to "
            f"{address!r} before any request was sent"
        )

    def _blocked_connect(self: socket.socket, address: object) -> None:
        _ = self
        blocked_destinations.append(address)
        raise OfflineNetworkBlocked(
            "offline tests blocked a connection to "
            f"{address!r} before any request was sent"
        )

    def _blocked_connect_ex(self: socket.socket, address: object) -> int:
        _ = self
        blocked_destinations.append(address)
        raise OfflineNetworkBlocked(
            "offline tests blocked a connection to "
            f"{address!r} before any request was sent"
        )

    socket.create_connection = _blocked_create_connection
    socket.socket.connect = _blocked_connect
    socket.socket.connect_ex = _blocked_connect_ex


def install_offline_guards() -> None:
    """Install credential, dotenv, and network guards once per process."""
    global _INSTALLED
    scrub_provider_credentials(os.environ)
    _block_dotenv_loader()
    if _INSTALLED:
        return
    _block_network()
    _INSTALLED = True
