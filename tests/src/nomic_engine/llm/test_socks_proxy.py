"""SOCKS proxy setup must import socksio and must not open a connection."""

from __future__ import annotations

import os
import socket

import httpcore
import httpx
import pytest
from anthropic import Anthropic
from openai import OpenAI

# Port 9 is the discard port. Nothing in this test connects to it.
_SOCKS_PROXY = "socks5://127.0.0.1:9"

# Schemes httpx copies out of the environment in get_environment_proxies().
_PROXY_CASES = (
    ("ALL_PROXY", "all://"),
    ("HTTP_PROXY", "http://"),
    ("HTTPS_PROXY", "https://"),
)


def _clear_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove proxy settings inherited from the process environment.

    ``urllib.request.getproxies()`` reads every ``*_proxy`` variable, prefers
    the lowercase name when both cases are set, and drops every proxy when
    ``NO_PROXY`` is ``*``. Uppercase ``HTTP_PROXY`` is ignored when
    ``REQUEST_METHOD`` is set. Clearing those names makes the test depend
    only on the variable it sets, and ``monkeypatch`` restores them
    afterwards.
    """
    for name in list(os.environ):
        if name.lower().endswith("_proxy"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("REQUEST_METHOD", raising=False)


def _forbid_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test if client construction opens a socket."""

    def _fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError(
            "SOCKS proxy client construction tried to open a socket"
        )

    monkeypatch.setattr(socket, "socket", _fail)
    monkeypatch.setattr(socket, "create_connection", _fail)


def _proxy_text(value: str | bytes) -> str:
    if isinstance(value, bytes):
        return value.decode()
    return value


def _assert_socks_mount(client: httpx.Client, mount_key: str) -> None:
    """Require a SOCKS mount. httpx imports socksio only while building one.

    Env-derived mounts are not part of httpx's public client API, so this
    reads ``Client._mounts`` rather than sending a request.
    """
    transports = [
        transport
        for pattern, transport in client._mounts.items()
        if pattern.pattern == mount_key
    ]
    assert len(transports) == 1
    transport = transports[0]
    assert isinstance(transport, httpx.HTTPTransport)
    pool = transport._pool
    assert isinstance(pool, httpcore.SOCKSProxy)
    proxy_url = pool._proxy_url
    assert _proxy_text(proxy_url.scheme) == "socks5"
    assert _proxy_text(proxy_url.host) == "127.0.0.1"
    assert proxy_url.port == 9


@pytest.mark.parametrize(("env_name", "mount_key"), _PROXY_CASES)
def test_socks_proxy_env_builds_clients_without_connecting(
    monkeypatch: pytest.MonkeyPatch, env_name: str, mount_key: str
) -> None:
    """Provider clients built under a SOCKS proxy must load socksio.

    Construction raises ImportError when socksio is not installed. No
    request is sent.
    """
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv(env_name, _SOCKS_PROXY)
    _forbid_sockets(monkeypatch)

    with httpx.Client() as http_client:
        _assert_socks_mount(http_client, mount_key)

    with OpenAI(api_key="test-key") as openai_client:
        _assert_socks_mount(openai_client._client, mount_key)

    with Anthropic(api_key="test-key") as anthropic_client:
        _assert_socks_mount(anthropic_client._client, mount_key)
