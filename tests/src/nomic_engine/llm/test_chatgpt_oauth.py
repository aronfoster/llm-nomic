"""Offline tests for Sign in with ChatGPT, against a fake auth server."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Iterator

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


def _sign_in(
    store: oauth.CredentialStore, fake: FakeAuthServer, **kw: object
) -> oauth.ChatGptCredential:
    with fake.client() as http:
        return oauth.sign_in(
            store,
            endpoints=fake.endpoints,
            http=http,
            open_browser=lambda url: fake.authorize(url, **kw),  # type: ignore[arg-type]
            port=0,
            timeout_seconds=10,
            notify=lambda _msg: None,
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
    assert store.load().access_token == first.access_token  # type: ignore[union-attr]


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
    assert store.load().refresh_token == cred.refresh_token  # type: ignore[union-attr]


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
    assert saved.client_id == fake.issued_client_id


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
