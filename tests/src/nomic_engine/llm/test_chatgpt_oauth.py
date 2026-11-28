"""Offline tests for Sign in with ChatGPT, against a fake auth server."""

from __future__ import annotations

import contextlib
import json
import os
import socket
import stat
import threading
import urllib.parse
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest

from src.nomic_engine.llm import chatgpt_oauth as oauth
from tests.fake_chatgpt_auth import FakeAuthServer


@pytest.fixture
def fake() -> Iterator[FakeAuthServer]:
    yield FakeAuthServer()


@pytest.fixture
def store(tmp_path: Path) -> oauth.CredentialStore:
    return oauth.CredentialStore(tmp_path / "cfg")


def _silent(_message: str) -> None:
    return None


def _sign_in(
    store: oauth.CredentialStore,
    fake: FakeAuthServer,
    *,
    sub: str | None = None,
    scope_override: str | None = None,
    deny: bool = False,
    omit_client_id: bool = False,
    notify: Callable[[str], None] | None = None,
) -> oauth.ChatGptCredential:
    def _open(url: str) -> None:
        fake.authorize(
            url,
            sub=sub,
            scope_override=scope_override,
            deny=deny,
            omit_client_id=omit_client_id,
        )

    with fake.client() as http:
        return oauth.sign_in(
            store,
            endpoints=fake.endpoints,
            http=http,
            open_browser=_open,
            port=0,
            timeout_seconds=10,
            notify=notify or _silent,
            listener_factory=fake.listener_factory,
        )


def test_first_sign_in_registers_and_saves_private_file(
    fake: FakeAuthServer, store: oauth.CredentialStore
) -> None:
    cred = _sign_in(store, fake)
    params = fake.authorize_params[0]
    assert params["client_id"] == oauth.DYNAMIC_CLIENT_ID
    assert params["agent_name_hint"] == "llm-nomic"
    assert params["ext_agent_host_id"].startswith("urn:uuid:")
    assert params["redirect_uri"].startswith("http://127.0.0.1:")
    assert params["redirect_uri"].endswith("/auth/callback")
    assert params["scope"].split() == list(oauth.REQUESTED_SCOPES)
    assert params["resource"] == "https://api.openai.com/v1"
    assert params["code_challenge_method"] == "S256"
    assert "id_token_hint" not in params
    exchange = fake.token_requests[0]
    assert exchange["grant_type"] == "authorization_code"
    assert exchange["client_id"] == fake.issued_client_id
    assert "client_secret" not in exchange
    assert cred.client_id == fake.issued_client_id
    assert cred.subject == fake.subject and cred.has_plan_usage()
    mode = stat.S_IMODE(store.credential_path.stat().st_mode)
    assert mode == 0o600
    assert stat.S_IMODE(store.directory.stat().st_mode) == 0o700
    saved = json.loads(store.credential_path.read_text())
    assert saved["client_id"] != oauth.DYNAMIC_CLIENT_ID
    assert cred.access_token is not None
    assert cred.access_token not in repr(cred)


def test_reauth_reuses_issued_client_host_and_hint(
    fake: FakeAuthServer, store: oauth.CredentialStore
) -> None:
    first = _sign_in(store, fake)
    _sign_in(store, fake)
    params = fake.authorize_params[1]
    assert params["client_id"] == fake.issued_client_id
    assert "agent_name_hint" not in params
    assert params["ext_agent_host_id"] == first.ext_agent_host_id
    assert params["id_token_hint"] == first.id_token
    assert params["login_hint"] == fake.email
    assert params["state"] != fake.authorize_params[0]["state"]
    assert params["nonce"] != fake.authorize_params[0]["nonce"]


def test_reauth_as_other_account_is_refused(
    fake: FakeAuthServer, store: oauth.CredentialStore
) -> None:
    first = _sign_in(store, fake)
    with pytest.raises(oauth.ChatGptAuthError, match="different ChatGPT"):
        _sign_in(store, fake, sub="someone-else")
    saved = store.load()
    assert saved is not None
    assert saved.access_token == first.access_token


def test_missing_plan_scope_is_refused(
    fake: FakeAuthServer, store: oauth.CredentialStore
) -> None:
    with pytest.raises(oauth.ChatGptAuthError, match="plan usage"):
        _sign_in(store, fake, scope_override="openid email profile")
    assert store.load() is None


def test_denied_and_incomplete_registration(
    fake: FakeAuthServer, store: oauth.CredentialStore
) -> None:
    with pytest.raises(oauth.ChatGptAuthError, match="access_denied"):
        _sign_in(store, fake, deny=True)
    with pytest.raises(oauth.ChatGptAuthError, match="issued client_id"):
        _sign_in(store, fake, omit_client_id=True)
    assert store.load() is None


def test_state_mismatch_is_refused() -> None:
    attempt = oauth.new_attempt("http://127.0.0.1:1/auth/callback")
    with pytest.raises(oauth.ChatGptAuthError, match="state"):
        oauth.parse_callback(
            {"state": "wrong", "code": "c", "client_id": "oaiapp_x"},
            attempt,
            issued_client_id=None,
        )


def test_id_token_with_wrong_nonce_is_refused(fake: FakeAuthServer) -> None:
    token = fake.id_token("nonce-a", client_id=fake.issued_client_id)
    with fake.client() as http:
        validator = oauth.IdTokenValidator(http, fake.endpoints)
        with pytest.raises(oauth.ChatGptAuthError, match="nonce"):
            validator.validate(
                token, client_id=fake.issued_client_id, nonce="b"
            )
        with pytest.raises(oauth.ChatGptAuthError, match="InvalidAudience"):
            validator.validate(token, client_id="other", nonce="nonce-a")


def test_refresh_rotates_and_saves_together(
    fake: FakeAuthServer, store: oauth.CredentialStore
) -> None:
    cred = _sign_in(store, fake)
    with fake.client() as http:
        updated = oauth.refresh_credential(
            store, cred.access_token, endpoints=fake.endpoints, http=http
        )
    form = fake.token_requests[-1]
    assert form["grant_type"] == "refresh_token"
    assert form["client_id"] == fake.issued_client_id
    assert form["resource"] == "https://api.openai.com/v1"
    assert "scope" not in form
    assert updated.refresh_token != cred.refresh_token
    assert updated.access_token != cred.access_token
    saved = store.load()
    assert saved is not None and saved.refresh_token == updated.refresh_token


def test_second_refresh_with_stale_token_reuses_saved(
    fake: FakeAuthServer, store: oauth.CredentialStore
) -> None:
    cred = _sign_in(store, fake)
    with fake.client() as http:
        a = oauth.refresh_credential(
            store, cred.access_token, endpoints=fake.endpoints, http=http
        )
        b = oauth.refresh_credential(
            store, cred.access_token, endpoints=fake.endpoints, http=http
        )
    assert a.access_token == b.access_token
    assert len(fake.token_requests) == 2  # code exchange + one refresh


def test_terminal_refresh_error_clears_tokens(
    fake: FakeAuthServer, store: oauth.CredentialStore
) -> None:
    cred = _sign_in(store, fake)
    fake.refresh_error = "refresh_token_reused"
    with fake.client() as http, pytest.raises(oauth.ReauthRequired):
        oauth.refresh_credential(
            store, cred.access_token, endpoints=fake.endpoints, http=http
        )
    saved = store.load()
    assert saved is not None
    assert saved.access_token is None and saved.refresh_token is None
    assert saved.client_id == fake.issued_client_id


def test_server_error_keeps_tokens(
    fake: FakeAuthServer, store: oauth.CredentialStore
) -> None:
    cred = _sign_in(store, fake)
    fake.refresh_error, fake.refresh_status = "server_error", 503
    with fake.client() as http, pytest.raises(oauth.TransientAuthError):
        oauth.refresh_credential(
            store, cred.access_token, endpoints=fake.endpoints, http=http
        )
    saved = store.load()
    assert saved is not None
    assert saved.refresh_token == cred.refresh_token


def test_token_provider_refreshes_near_expiry_and_on_force(
    fake: FakeAuthServer, store: oauth.CredentialStore
) -> None:
    fake.expires_in = 60  # inside the refresh margin
    cred = _sign_in(store, fake)
    with fake.client() as http:
        provider = oauth.ChatGptTokenProvider(
            store, endpoints=fake.endpoints, http=http
        )
        fresh = provider.access_token()
        assert fresh != cred.access_token
        forced = provider.force_refresh(fresh)
        assert forced != fresh


def test_token_provider_without_sign_in(store: oauth.CredentialStore) -> None:
    with pytest.raises(oauth.ReauthRequired, match="login"):
        oauth.ChatGptTokenProvider(
            store, http=httpx.Client(transport=httpx.MockTransport(_unused))
        ).access_token()


def _unused(request: httpx.Request) -> httpx.Response:
    raise AssertionError("no request expected")


def test_sign_out_revokes_and_keeps_registration(
    fake: FakeAuthServer, store: oauth.CredentialStore
) -> None:
    cred = _sign_in(store, fake)
    with fake.client() as http:
        assert oauth.sign_out(store, endpoints=fake.endpoints, http=http)
    assert fake.revocations[0]["token"] == cred.refresh_token
    assert fake.revocations[0]["token_type_hint"] == "refresh_token"
    saved = store.load()
    assert saved is not None and saved.access_token is None
    assert saved.refresh_token is None
    assert saved.id_token is None
    assert saved.client_id == fake.issued_client_id
    assert saved.email == fake.email
    assert saved.subject == cred.subject
    _sign_in(store, fake)
    params = fake.authorize_params[-1]
    assert "id_token_hint" not in params
    assert params["login_hint"] == fake.email
    assert params["client_id"] == fake.issued_client_id


def test_world_readable_file_is_refused(store: oauth.CredentialStore) -> None:
    store.host_id()
    os.chmod(store.host_id_path, 0o644)
    with pytest.raises(oauth.ChatGptAuthError, match="chmod 600"):
        store.host_id()


def test_store_inside_repo_is_refused() -> None:
    root = Path(oauth.__file__).resolve().parents[3]
    if not (root / ".git").exists():
        pytest.skip("not running from a git checkout")
    with pytest.raises(oauth.ChatGptAuthError, match="inside the repository"):
        oauth.CredentialStore(root / "secrets")


def test_default_dir_honours_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(oauth.CONFIG_DIR_ENV, str(tmp_path / "x"))
    assert oauth.default_config_dir() == tmp_path / "x"
    monkeypatch.delenv(oauth.CONFIG_DIR_ENV)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert oauth.default_config_dir() == tmp_path / "xdg" / "llm-nomic"


def test_production_endpoints_are_the_documented_ones() -> None:
    ep = oauth.PRODUCTION_ENDPOINTS
    assert ep.authorize_url == "https://auth.openai.com/api/accounts/authorize"
    assert ep.token_url == "https://auth.openai.com/api/accounts/oauth/token"
    assert ep.issuer == "https://auth.openai.com"


def test_loopback_listener_binds_127_0_0_1_only() -> None:
    listener = oauth.LoopbackListener(0)
    try:
        assert listener.redirect_uri.startswith("http://127.0.0.1:")
        assert listener.redirect_uri.endswith(oauth.CALLBACK_PATH)
        with pytest.raises(oauth.ChatGptAuthError, match="No sign-in"):
            listener.wait(0.01)
    finally:
        listener.close()


def test_reauth_url_shown_to_the_user_redacts_the_id_token(
    fake: FakeAuthServer, store: oauth.CredentialStore
) -> None:
    first = _sign_in(store, fake)
    shown: list[str] = []
    _sign_in(store, fake, notify=shown.append)
    assert first.id_token is not None
    visible = "\n".join(shown)
    assert first.id_token not in visible
    assert "id_token_hint=redacted" in visible
    assert fake.authorize_params[-1]["id_token_hint"] == first.id_token


def test_sign_out_waits_for_in_flight_refresh(
    fake: FakeAuthServer,
    store: oauth.CredentialStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cred = _sign_in(store, fake)
    in_token = threading.Event()
    release_token = threading.Event()
    about_to_lock = threading.Semaphore(0)
    real_post = oauth._post_token
    real_lock = oauth.CredentialStore.refresh_lock

    def blocking_post(
        http: httpx.Client,
        endpoints: oauth.OAuthEndpoints,
        form: dict[str, str],
    ) -> dict[str, object]:
        if form.get("grant_type") == "refresh_token":
            in_token.set()
            assert release_token.wait(5)
        return real_post(http, endpoints, form)

    @contextlib.contextmanager
    def tracking_lock(self: oauth.CredentialStore) -> Iterator[None]:
        about_to_lock.release()
        with real_lock(self):
            yield

    monkeypatch.setattr(oauth, "_post_token", blocking_post)
    monkeypatch.setattr(oauth.CredentialStore, "refresh_lock", tracking_lock)
    errors: list[BaseException] = []

    def do_refresh() -> None:
        try:
            with fake.client() as http:
                oauth.refresh_credential(
                    store,
                    cred.access_token,
                    endpoints=fake.endpoints,
                    http=http,
                )
        except Exception as exc:
            errors.append(exc)

    def do_sign_out() -> None:
        try:
            with fake.client() as http:
                oauth.sign_out(store, endpoints=fake.endpoints, http=http)
        except Exception as exc:
            errors.append(exc)

    refresher = threading.Thread(target=do_refresh)
    signing_out = threading.Thread(target=do_sign_out)
    refresher.start()
    try:
        assert in_token.wait(5)
        assert about_to_lock.acquire(timeout=2)
        signing_out.start()
        locked = about_to_lock.acquire(timeout=5)
        assert locked, "sign_out did not take the refresh lock"
        release_token.set()
        refresher.join(5)
        signing_out.join(5)
    finally:
        release_token.set()
        refresher.join(5)
        if signing_out.is_alive():
            signing_out.join(5)
    assert errors == []
    assert not refresher.is_alive()
    assert not signing_out.is_alive()
    saved = store.load()
    assert saved is not None
    assert saved.access_token is None
    assert saved.refresh_token is None
    assert saved.id_token is None
    assert saved.client_id == fake.issued_client_id
    assert fake.refresh_tokens == set()
    assert fake.revocations[-1]["token"] != cred.refresh_token


def test_code_exchange_invalid_grant_keeps_issued_client(
    fake: FakeAuthServer, store: oauth.CredentialStore
) -> None:
    fake.code_exchange_error = "invalid_grant"
    with pytest.raises(oauth.ChatGptAuthError, match="invalid_grant"):
        _sign_in(store, fake)
    saved = store.load()
    assert saved is not None
    assert saved.client_id == fake.issued_client_id
    assert saved.subject == ""
    assert saved.access_token is None
    assert saved.refresh_token is None
    fake.code_exchange_error = None
    cred = _sign_in(store, fake)
    params = fake.authorize_params[-1]
    assert params["client_id"] == fake.issued_client_id
    assert "agent_name_hint" not in params
    assert cred.subject == fake.subject
    assert cred.access_token


def test_reauth_code_exchange_invalid_grant_keeps_saved_session(
    fake: FakeAuthServer, store: oauth.CredentialStore
) -> None:
    cred = _sign_in(store, fake)
    fake.code_exchange_error = "invalid_grant"
    with pytest.raises(oauth.ChatGptAuthError, match="invalid_grant"):
        _sign_in(store, fake)
    saved = store.load()
    assert saved is not None
    assert saved.access_token == cred.access_token
    assert saved.refresh_token == cred.refresh_token
    assert saved.client_id == cred.client_id


def test_id_token_tolerates_a_few_seconds_of_future_iat(
    fake: FakeAuthServer,
) -> None:
    token = fake.id_token(
        "nonce-skew",
        client_id=fake.issued_client_id,
        iat_offset=5,
    )
    with fake.client() as http:
        claims = oauth.IdTokenValidator(http, fake.endpoints).validate(
            token, client_id=fake.issued_client_id, nonce="nonce-skew"
        )
    assert claims["sub"] == fake.subject


def test_id_token_rejects_iat_beyond_leeway(fake: FakeAuthServer) -> None:
    token = fake.id_token(
        "nonce-skew",
        client_id=fake.issued_client_id,
        iat_offset=oauth.ID_TOKEN_LEEWAY_SECONDS + 30,
    )
    with fake.client() as http:
        validator = oauth.IdTokenValidator(http, fake.endpoints)
        with pytest.raises(oauth.ChatGptAuthError, match="ImmatureSignature"):
            validator.validate(
                token, client_id=fake.issued_client_id, nonce="nonce-skew"
            )


def test_discovery_and_jwks_failures_are_transient(
    fake: FakeAuthServer,
) -> None:
    token = fake.id_token("nonce-net", client_id=fake.issued_client_id)
    fake.discovery_status = 503
    with fake.client() as http:
        validator = oauth.IdTokenValidator(http, fake.endpoints)
        with pytest.raises(oauth.TransientAuthError, match="OpenID"):
            validator.validate(
                token, client_id=fake.issued_client_id, nonce="nonce-net"
            )
    fake.discovery_status = 200
    fake.jwks_status = 503
    with fake.client() as http:
        validator = oauth.IdTokenValidator(http, fake.endpoints)
        with pytest.raises(oauth.TransientAuthError, match="JWKS"):
            validator.validate(
                token, client_id=fake.issued_client_id, nonce="nonce-net"
            )
    fake.jwks_status = 200
    fake.discovery_disconnect = True
    with fake.client() as http:
        validator = oauth.IdTokenValidator(http, fake.endpoints)
        with pytest.raises(oauth.TransientAuthError, match="unreachable"):
            validator.validate(
                token, client_id=fake.issued_client_id, nonce="nonce-net"
            )


def test_sign_out_clears_tokens_when_discovery_is_not_json(
    fake: FakeAuthServer, store: oauth.CredentialStore
) -> None:
    cred = _sign_in(store, fake)
    assert cred.id_token
    fake.discovery_raw = b"not-json"
    with fake.client() as http:
        assert (
            oauth.sign_out(store, endpoints=fake.endpoints, http=http) is False
        )
    saved = store.load()
    assert saved is not None
    assert saved.access_token is None
    assert saved.refresh_token is None
    assert saved.id_token is None
    assert saved.client_id == fake.issued_client_id
    assert fake.revocations == []


def test_non_json_token_response_is_an_auth_error(
    fake: FakeAuthServer, store: oauth.CredentialStore
) -> None:
    fake.token_raw = b"not-json"
    with pytest.raises(oauth.ChatGptAuthError, match="not valid JSON"):
        _sign_in(store, fake)
    saved = store.load()
    assert saved is None or saved.access_token is None


def _drive_callback(listener: oauth.LoopbackListener, query: str) -> bytes:
    """Feed one callback request to the listener without ``connect``.

    ``socketpair`` stays inside this process. The offline guard blocks
    ``connect``, including loopback, so the test cannot open a TCP client.
    """
    raw = (
        f"GET {oauth.CALLBACK_PATH}?{query} HTTP/1.1\r\n"
        "Host: 127.0.0.1\r\n"
        "\r\n"
    ).encode()
    client, server_sock = socket.socketpair()
    try:
        client.settimeout(2)
        client.sendall(raw)
        client.shutdown(socket.SHUT_WR)
        listener.handler_class(server_sock, ("127.0.0.1", 0), listener._server)
        return client.recv(65536)
    finally:
        client.close()
        server_sock.close()


def test_loopback_ignores_callback_with_the_wrong_state() -> None:
    listener = oauth.LoopbackListener(0)
    try:
        listener.expect_state("good-state")
        stale = _drive_callback(listener, "code=stale&state=old-state")
        assert b"HTTP/1.0 200" in stale
        assert b"does not match" in stale
        with pytest.raises(oauth.ChatGptAuthError, match="No sign-in"):
            listener.wait(0.05)
        matched = _drive_callback(
            listener, "code=real&state=good-state&client_id=abc"
        )
        assert b"sign-in finished" in matched
        query = listener.wait(1)
        assert query["code"] == "real"
        assert query["state"] == "good-state"
    finally:
        listener.close()


def test_sign_in_binds_callback_state_before_the_browser(
    fake: FakeAuthServer, store: oauth.CredentialStore
) -> None:
    seen: dict[str, str] = {}

    class RecordingListener:
        redirect_uri = "http://127.0.0.1:9/auth/callback"

        def expect_state(self, state: str) -> None:
            seen["state"] = state

        def wait(self, timeout: float) -> dict[str, str]:
            del timeout
            raise oauth.ChatGptAuthError("stopped after bind")

        def close(self) -> None:
            seen["closed"] = "yes"

    def factory(_port: int) -> RecordingListener:
        return RecordingListener()

    def browse(url: str) -> None:
        seen["url"] = url
        assert seen["state"] in url

    with (
        fake.client() as http,
        pytest.raises(oauth.ChatGptAuthError, match="stopped after bind"),
    ):
        oauth.sign_in(
            store,
            endpoints=fake.endpoints,
            http=http,
            open_browser=browse,
            port=0,
            timeout_seconds=1,
            notify=_silent,
            listener_factory=factory,
        )
    assert seen["closed"] == "yes"
    parsed = urllib.parse.parse_qs(urllib.parse.urlsplit(seen["url"]).query)
    assert parsed["state"] == [seen["state"]]
