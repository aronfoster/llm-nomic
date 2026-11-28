"""Sign in with ChatGPT for open-source apps (OpenAI's SIWC preview).

This module implements the documented OAuth flow that lets llm-nomic use
a signed-in ChatGPT plan instead of an API key:

* PKCE (S256), a fresh ``state`` and OIDC ``nonce`` per attempt.
* A loopback callback listener on ``127.0.0.1`` (never ``localhost``).
* First sign-in registers a per-user client with
  ``client_id=dynamic_agent_client``. The callback returns the issued
  ``client_id``, which is saved and reused for every later sign-in and
  refresh. ``dynamic_agent_client`` is never saved or used for tokens.
* Authorization-code exchange and ``refresh_token`` grants against the
  documented token endpoint. Refresh tokens rotate; the access token,
  expiry, scopes and replacement refresh token are saved together.
* ID-token validation against the issuer's published JWKS.
* One owner-only (0600) credential file outside the repository, written
  atomically. The directory defaults to ``~/.config/llm-nomic/`` and can
  be moved with ``LLM_NOMIC_CONFIG_DIR`` or an explicit path.

Docs: https://developers.openai.com/siwc/token-sharing-open-source

Only the documented endpoints and scopes are used. Nothing here calls a
model. Tokens are never logged; error messages never include them.
"""

from __future__ import annotations

import base64
import contextlib
import dataclasses
import datetime
import hashlib
import hmac
import http.server
import json
import logging
import os
import secrets
import tempfile
import threading
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

import httpx
import jwt

logger = logging.getLogger(__name__)

APP_NAME = "llm-nomic"
DYNAMIC_CLIENT_ID = "dynamic_agent_client"
RESOURCE = "https://api.openai.com/v1"
IDENTITY_SCOPES = ("openid", "profile", "email")
PLAN_SCOPES = (
    "offline_access",
    "resource.invoke",
    "chatgpt.tokens.use.direct",
)
REQUESTED_SCOPES = IDENTITY_SCOPES + PLAN_SCOPES
PLAN_USAGE_SCOPE = "chatgpt.tokens.use.direct"
CALLBACK_PATH = "/auth/callback"
DEFAULT_CALLBACK_PORT = 1455
CONFIG_DIR_ENV = "LLM_NOMIC_CONFIG_DIR"
CREDENTIAL_FILENAME = "chatgpt_credentials.json"
HOST_ID_FILENAME = "chatgpt_host_id"
LOCK_FILENAME = "chatgpt_credentials.lock"

# Refresh this long before the access token expires.
REFRESH_MARGIN_SECONDS = 300

# PyJWT rejects an ID token whose ``iat`` is even a second in the
# future. A laptop clock a few seconds behind the issuer would fail
# every sign-in after the authorization code was already spent.
ID_TOKEN_LEEWAY_SECONDS = 60

# Shown in place of ``id_token_hint`` when a URL is printed. The browser
# still receives the real hint.
_REDACTED_QUERY_VALUE = "redacted"

# Refresh errors after which the refresh token can never work again.
TERMINAL_REFRESH_ERRORS = frozenset(
    {
        "invalid_grant",
        "invalid_refresh_token",
        "token_expired",
        "refresh_token_expired",
        "refresh_token_invalidated",
        "refresh_token_reused",
    }
)


class ChatGptAuthError(RuntimeError):
    """Sign-in or token handling failed. Messages never contain tokens."""


class ReauthRequired(ChatGptAuthError):
    """The saved session cannot be renewed; run the login command again."""


class TransientAuthError(ChatGptAuthError):
    """A network failure or 5xx; the saved tokens are kept for a retry."""


@dataclasses.dataclass(frozen=True)
class OAuthEndpoints:
    """Where the flow talks to. Production defaults; tests pass a fake."""

    issuer: str = "https://auth.openai.com"
    authorize_url: str = "https://auth.openai.com/api/accounts/authorize"
    token_url: str = "https://auth.openai.com/api/accounts/oauth/token"
    discovery_url: str = (
        "https://auth.openai.com/.well-known/openid-configuration"
    )


PRODUCTION_ENDPOINTS = OAuthEndpoints()


# --------------------------------------------------------------------------
# Credential storage
# --------------------------------------------------------------------------


def _utc_now() -> float:
    return time.time()


def _iso(ts: float) -> str:
    return (
        datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


@dataclasses.dataclass
class ChatGptCredential:
    """One registration: issued client ID, verified identity and tokens.

    Field names follow the record in OpenAI's sign-in docs, plus
    ``expires_at`` and ``earliest_refresh_at`` as Unix seconds.

    ``subject`` is empty when the issued client ID was saved after a
    failed code exchange and no account has been verified yet.
    """

    client_id: str
    ext_agent_host_id: str
    issuer: str
    subject: str
    email: str | None
    id_token: str | None
    access_token: str | None
    refresh_token: str | None
    token_type: str
    expires_in: int
    expires_at: float
    scopes: list[str]
    saved_at: str
    earliest_refresh_at: float | None = None

    def has_plan_usage(self) -> bool:
        return PLAN_USAGE_SCOPE in self.scopes

    def to_json(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "ChatGptCredential":
        names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})

    def __repr__(self) -> str:  # never print tokens
        return (
            f"ChatGptCredential(client_id={self.client_id!r}, "
            f"email={self.email!r}, scopes={self.scopes!r}, "
            f"expires_at={_iso(self.expires_at)!r})"
        )


def default_config_dir() -> Path:
    """``$LLM_NOMIC_CONFIG_DIR`` or ``$XDG_CONFIG_HOME/llm-nomic``."""
    override = os.environ.get(CONFIG_DIR_ENV)
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / APP_NAME


def _repo_root() -> Path | None:
    """The source checkout this module runs from, if any."""
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists():
            return parent
    return None


class CredentialStore:
    """Owner-only credential file plus this host's stable host ID."""

    def __init__(self, directory: Path | str | None = None) -> None:
        self.directory = (
            Path(directory).expanduser()
            if directory is not None
            else default_config_dir()
        )
        root = _repo_root()
        resolved = self.directory.resolve()
        if root is not None and (resolved == root or root in resolved.parents):
            raise ChatGptAuthError(
                f"Refusing to keep ChatGPT credentials inside the repository "
                f"({resolved}). Choose a directory outside {root}."
            )

    @property
    def credential_path(self) -> Path:
        return self.directory / CREDENTIAL_FILENAME

    @property
    def host_id_path(self) -> Path:
        return self.directory / HOST_ID_FILENAME

    def _ensure_dir(self) -> None:
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(self.directory, 0o700)

    def _write_private(self, path: Path, text: str) -> None:
        """Atomic write with mode 0600 from the moment the file exists."""
        self._ensure_dir()
        fd, tmp = tempfile.mkstemp(dir=self.directory, prefix=".tmp-")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def _read_private(self, path: Path) -> str | None:
        try:
            mode = path.stat().st_mode
        except FileNotFoundError:
            return None
        if mode & 0o077:
            raise ChatGptAuthError(
                f"{path} is readable by other users (mode "
                f"{oct(mode & 0o777)}). Run: chmod 600 {path}"
            )
        return path.read_text(encoding="utf-8")

    def host_id(self) -> str:
        """Stable ``ext_agent_host_id`` for this machine, created once."""
        text = self._read_private(self.host_id_path)
        if text and text.strip():
            return text.strip()
        value = f"urn:uuid:{uuid.uuid4()}"
        self._write_private(self.host_id_path, value + "\n")
        return value

    def load(self) -> ChatGptCredential | None:
        text = self._read_private(self.credential_path)
        if text is None:
            return None
        try:
            return ChatGptCredential.from_json(json.loads(text))
        except (ValueError, TypeError) as exc:
            raise ChatGptAuthError(
                f"Credential file {self.credential_path} is unreadable: "
                f"{type(exc).__name__}"
            ) from None

    def save(self, credential: ChatGptCredential) -> None:
        self._write_private(
            self.credential_path,
            json.dumps(credential.to_json(), indent=2, sort_keys=True) + "\n",
        )

    @contextlib.contextmanager
    def refresh_lock(self) -> Iterator[None]:
        """Serialize refreshes across processes (rotating refresh tokens)."""
        import fcntl

        self._ensure_dir()
        fd = os.open(
            self.directory / LOCK_FILENAME, os.O_RDWR | os.O_CREAT, 0o600
        )
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


# --------------------------------------------------------------------------
# Authorization request
# --------------------------------------------------------------------------


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


@dataclasses.dataclass(frozen=True)
class AuthAttempt:
    """Per-attempt secrets. Never reused across attempts."""

    state: str
    nonce: str
    code_verifier: str
    redirect_uri: str

    @property
    def code_challenge(self) -> str:
        digest = hashlib.sha256(self.code_verifier.encode("ascii")).digest()
        return _b64url(digest)


def new_attempt(redirect_uri: str) -> AuthAttempt:
    return AuthAttempt(
        state=secrets.token_urlsafe(32),
        nonce=secrets.token_urlsafe(32),
        code_verifier=_b64url(secrets.token_bytes(48)),
        redirect_uri=redirect_uri,
    )


def build_authorize_url(
    endpoints: OAuthEndpoints,
    attempt: AuthAttempt,
    *,
    ext_agent_host_id: str,
    issued_client_id: str | None = None,
    id_token_hint: str | None = None,
    login_hint: str | None = None,
) -> str:
    """Authorization URL for first registration or reauthorization."""
    params: dict[str, str] = {
        "client_id": issued_client_id or DYNAMIC_CLIENT_ID,
        "ext_agent_host_id": ext_agent_host_id,
        "response_type": "code",
        "redirect_uri": attempt.redirect_uri,
        "scope": " ".join(REQUESTED_SCOPES),
        "resource": RESOURCE,
        "state": attempt.state,
        "nonce": attempt.nonce,
        "code_challenge_method": "S256",
        "code_challenge": attempt.code_challenge,
    }
    if issued_client_id is None:
        params["agent_name_hint"] = APP_NAME
    else:
        if id_token_hint:
            params["id_token_hint"] = id_token_hint
        if login_hint:
            params["login_hint"] = login_hint
    return (
        endpoints.authorize_url
        + "?"
        + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    )


def redact_authorize_url(url: str) -> str:
    """Return ``url`` with any ``id_token_hint`` value replaced.

    The hint is the user's ID token. The browser must receive it, but
    the copy printed in the terminal must not.
    """
    parts = urllib.parse.urlsplit(url)
    pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    if not any(key == "id_token_hint" and value for key, value in pairs):
        return url
    redacted = [
        (key, _REDACTED_QUERY_VALUE if key == "id_token_hint" else value)
        for key, value in pairs
    ]
    query = urllib.parse.urlencode(redacted, quote_via=urllib.parse.quote)
    return urllib.parse.urlunsplit(parts._replace(query=query))


@dataclasses.dataclass(frozen=True)
class CallbackResult:
    code: str
    client_id: str


def parse_callback(
    query: dict[str, str],
    attempt: AuthAttempt,
    *,
    issued_client_id: str | None,
) -> CallbackResult:
    """Validate the loopback callback and return the code and client ID."""
    state = query.get("state", "")
    if not hmac.compare_digest(state.encode(), attempt.state.encode()):
        raise ChatGptAuthError("Sign-in callback state did not match.")
    if "error" in query:
        detail = query.get("error_description") or ""
        raise ChatGptAuthError(
            f"Sign-in was not completed: {query['error']} {detail}".strip()
        )
    code = query.get("code")
    if not code:
        raise ChatGptAuthError("Sign-in callback had no authorization code.")
    returned = query.get("client_id")
    if issued_client_id is None:
        if not returned or returned == DYNAMIC_CLIENT_ID:
            raise ChatGptAuthError(
                "Registration incomplete: the callback did not include an "
                "issued client_id."
            )
        client_id = returned
    else:
        if returned and returned != issued_client_id:
            raise ChatGptAuthError(
                "Callback client_id differs from the saved registration."
            )
        client_id = issued_client_id
    return CallbackResult(code=code, client_id=client_id)


# --------------------------------------------------------------------------
# Loopback listener
# --------------------------------------------------------------------------


_ACCEPTED_PAGE = (
    b"<html><body><p>llm-nomic sign-in finished. "
    b"You can close this window.</p></body></html>"
)
_IGNORED_PAGE = (
    b"<html><body><p>This page does not match the current "
    b"llm-nomic sign-in. You can close this window.</p></body></html>"
)


def _callback_matches(
    query: dict[str, str], expected_state: str | None
) -> bool:
    """True when ``query`` carries the state for the current attempt."""
    if expected_state is None:
        return False
    return hmac.compare_digest(
        query.get("state", "").encode(), expected_state.encode()
    )


class LoopbackListener:
    """One-shot HTTP listener on 127.0.0.1 for the OAuth redirect.

    A request whose ``state`` does not match the current attempt is
    answered and ignored, so a stale tab or another local client cannot
    end the sign-in.
    """

    def __init__(self, port: int = DEFAULT_CALLBACK_PORT) -> None:
        self._result: dict[str, str] | None = None
        self._expected_state: str | None = None
        self._event = threading.Event()
        listener = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 (stdlib name)
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path != CALLBACK_PATH:
                    self.send_error(404)
                    return
                query = dict(urllib.parse.parse_qsl(parsed.query))
                accepted = listener._take_callback(query)
                body = _ACCEPTED_PAGE if accepted else _IGNORED_PAGE
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: Any) -> None:  # no code in logs
                return

        self.handler_class = Handler
        try:
            self._server = http.server.HTTPServer(
                ("127.0.0.1", port), self.handler_class
            )
        except OSError:
            # Only the port may vary between sign-ins.
            self._server = http.server.HTTPServer(
                ("127.0.0.1", 0), self.handler_class
            )
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._thread.start()

    def expect_state(self, state: str) -> None:
        """Accept only a callback that echoes ``state``."""
        self._expected_state = state

    def _take_callback(self, query: dict[str, str]) -> bool:
        """Record ``query`` when it belongs to this attempt."""
        if self._result is not None:
            return False
        if not _callback_matches(query, self._expected_state):
            return False
        self._result = query
        self._event.set()
        return True

    @property
    def redirect_uri(self) -> str:
        port = self._server.server_address[1]
        return f"http://127.0.0.1:{port}{CALLBACK_PATH}"

    def wait(self, timeout: float) -> dict[str, str]:
        if not self._event.wait(timeout):
            raise ChatGptAuthError(
                f"No sign-in callback within {int(timeout)} seconds."
            )
        assert self._result is not None
        return self._result

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


# --------------------------------------------------------------------------
# Token endpoint and ID-token validation
# --------------------------------------------------------------------------


def _token_error(response: httpx.Response) -> tuple[str, str]:
    try:
        data = response.json()
    except ValueError:
        return "", ""
    if not isinstance(data, dict):
        return "", ""
    err = data.get("error")
    if isinstance(err, dict):
        return str(err.get("code") or ""), str(err.get("message") or "")
    return str(err or ""), str(data.get("error_description") or "")


def _post_token(
    http: httpx.Client, endpoints: OAuthEndpoints, form: dict[str, str]
) -> dict[str, Any]:
    try:
        response = http.post(
            endpoints.token_url,
            data=form,
            headers={"Accept": "application/json"},
        )
    except httpx.HTTPError as exc:
        raise TransientAuthError(
            f"Token endpoint unreachable: {type(exc).__name__}"
        ) from None
    if response.status_code >= 500:
        raise TransientAuthError(
            f"Token endpoint returned HTTP {response.status_code}."
        )
    if response.status_code != 200:
        code, message = _token_error(response)
        # These codes mean the refresh token is dead. An authorization
        # code that is rejected is not a refresh failure: the caller
        # still has the issued client ID from the callback and must
        # keep it for the next attempt.
        if (
            form.get("grant_type") == "refresh_token"
            and code in TERMINAL_REFRESH_ERRORS
        ):
            raise ReauthRequired(
                f"Token endpoint refused the grant ({code}). "
                "Run the login command again."
            )
        raise ChatGptAuthError(
            f"Token endpoint returned HTTP {response.status_code} "
            f"{code} {message}".strip()
        )
    try:
        data = response.json()
    except ValueError:
        raise ChatGptAuthError("Token response was not valid JSON.") from None
    if not isinstance(data, dict) or not data.get("access_token"):
        raise ChatGptAuthError("Token response had no access_token.")
    return data


def _get_json(http: httpx.Client, url: str, what: str) -> Any:
    """GET JSON. Network errors, HTTP 5xx, and bad bodies are transient."""
    try:
        response = http.get(url, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise TransientAuthError(
            f"{what} unreachable: {type(exc).__name__}"
        ) from None
    if response.status_code >= 500:
        raise TransientAuthError(
            f"{what} returned HTTP {response.status_code}."
        )
    if response.status_code != 200:
        raise ChatGptAuthError(f"{what} returned HTTP {response.status_code}.")
    try:
        return response.json()
    except ValueError:
        raise TransientAuthError(f"{what} was not valid JSON.") from None


class IdTokenValidator:
    """Checks signature (published JWKS), issuer, audience, expiry, nonce."""

    def __init__(self, http: httpx.Client, endpoints: OAuthEndpoints) -> None:
        self._http = http
        self._endpoints = endpoints
        self._jwks: jwt.PyJWKSet | None = None

    def _discovery(self) -> dict[str, Any]:
        data = _get_json(
            self._http,
            self._endpoints.discovery_url,
            "OpenID configuration",
        )
        if not isinstance(data, dict):
            raise ChatGptAuthError("OpenID configuration is not an object.")
        return data

    def _key_set(self) -> jwt.PyJWKSet:
        if self._jwks is None:
            jwks_uri = self._discovery().get("jwks_uri")
            if not isinstance(jwks_uri, str):
                raise ChatGptAuthError("OpenID configuration has no jwks_uri.")
            self._jwks = jwt.PyJWKSet.from_dict(
                _get_json(self._http, jwks_uri, "JWKS")
            )
        return self._jwks

    def revocation_endpoint(self) -> str | None:
        value = self._discovery().get("revocation_endpoint")
        return value if isinstance(value, str) else None

    def validate(
        self, id_token: str, *, client_id: str, nonce: str
    ) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(id_token)
            kid = header.get("kid")
            keys = [
                k
                for k in self._key_set().keys
                if kid is None or k.key_id == kid
            ]
            if not keys:
                raise ChatGptAuthError("ID token key is not in the JWKS.")
            claims = jwt.decode(
                id_token,
                key=keys[0].key,
                algorithms=["RS256"],
                audience=client_id,
                issuer=self._endpoints.issuer,
                leeway=ID_TOKEN_LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise ChatGptAuthError(
                f"ID token failed validation: {type(exc).__name__}"
            ) from None
        if not hmac.compare_digest(
            str(claims.get("nonce", "")).encode(), nonce.encode()
        ):
            raise ChatGptAuthError("ID token nonce did not match.")
        return dict(claims)


def _scopes(token_data: dict[str, Any], fallback: list[str]) -> list[str]:
    scope = token_data.get("scope")
    if isinstance(scope, str) and scope.strip():
        return sorted(scope.split())
    return list(fallback)


def _expiry(token_data: dict[str, Any], now: float) -> tuple[int, float]:
    try:
        expires_in = int(token_data.get("expires_in") or 3600)
    except (TypeError, ValueError):
        expires_in = 3600
    return expires_in, now + expires_in


def _earliest(token_data: dict[str, Any]) -> float | None:
    value = token_data.get("earliest_refresh_at")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


# --------------------------------------------------------------------------
# Sign-in, refresh, sign-out
# --------------------------------------------------------------------------


def sign_in(
    store: CredentialStore,
    *,
    endpoints: OAuthEndpoints = PRODUCTION_ENDPOINTS,
    http: httpx.Client | None = None,
    open_browser: Callable[[str], Any] | None = None,
    port: int = DEFAULT_CALLBACK_PORT,
    timeout_seconds: float = 300.0,
    notify: Callable[[str], None] = print,
    listener_factory: Callable[[int], Any] = LoopbackListener,
) -> ChatGptCredential:
    """Run the browser sign-in once and save the credential file.

    Registers a new client on the first run. Later runs reuse the saved
    issued client ID, host ID and ID-token hint, and refuse to replace
    the saved account with a different one.
    """
    owns_http = http is None
    client = http or httpx.Client(timeout=30.0)
    if open_browser is None:
        import webbrowser

        open_browser = webbrowser.open
    try:
        host_id = store.host_id()
        previous = store.load()
        issued = previous.client_id if previous else None
        listener = listener_factory(port)
        try:
            attempt = new_attempt(listener.redirect_uri)
            expect_state = getattr(listener, "expect_state", None)
            if expect_state is not None:
                expect_state(attempt.state)
            url = build_authorize_url(
                endpoints,
                attempt,
                ext_agent_host_id=host_id,
                issued_client_id=issued,
                id_token_hint=previous.id_token if previous else None,
                login_hint=previous.email if previous else None,
            )
            notify(
                "Opening your browser for Sign in with ChatGPT. If it does "
                "not open, paste this URL into a browser on this computer:"
            )
            notify(redact_authorize_url(url))
            open_browser(url)
            query = listener.wait(timeout_seconds)
        finally:
            listener.close()
        result = parse_callback(query, attempt, issued_client_id=issued)
        try:
            token_data = _post_token(
                client,
                endpoints,
                {
                    "grant_type": "authorization_code",
                    "client_id": result.client_id,
                    "code": result.code,
                    "code_verifier": attempt.code_verifier,
                    "redirect_uri": attempt.redirect_uri,
                    "resource": RESOURCE,
                },
            )
        except ChatGptAuthError:
            if previous is None:
                _remember_issued_client(
                    store,
                    client_id=result.client_id,
                    host_id=host_id,
                    issuer=endpoints.issuer,
                )
            raise
        id_token = token_data.get("id_token")
        if not isinstance(id_token, str):
            raise ChatGptAuthError("Token response had no id_token.")
        claims = IdTokenValidator(client, endpoints).validate(
            id_token, client_id=result.client_id, nonce=attempt.nonce
        )
        if (
            previous is not None
            and previous.subject
            and claims["sub"] != previous.subject
        ):
            raise ChatGptAuthError(
                "Signed in as a different ChatGPT account than the saved "
                "registration. Use a different config directory for it."
            )
        scopes = _scopes(token_data, [])
        if PLAN_USAGE_SCOPE not in scopes:
            raise ChatGptAuthError(
                "ChatGPT plan usage was not granted "
                f"({PLAN_USAGE_SCOPE} missing). Enable it and sign in again."
            )
        now = _utc_now()
        expires_in, expires_at = _expiry(token_data, now)
        email = claims.get("email")
        credential = ChatGptCredential(
            client_id=result.client_id,
            ext_agent_host_id=host_id,
            issuer=endpoints.issuer,
            subject=str(claims["sub"]),
            email=email if isinstance(email, str) else None,
            id_token=id_token,
            access_token=str(token_data["access_token"]),
            refresh_token=token_data.get("refresh_token"),
            token_type=str(token_data.get("token_type") or "Bearer"),
            expires_in=expires_in,
            expires_at=expires_at,
            scopes=scopes,
            saved_at=_iso(now),
            earliest_refresh_at=_earliest(token_data),
        )
        store.save(credential)
        return credential
    finally:
        if owns_http:
            client.close()


def refresh_credential(
    store: CredentialStore,
    stale_access_token: str | None,
    *,
    endpoints: OAuthEndpoints = PRODUCTION_ENDPOINTS,
    http: httpx.Client,
) -> ChatGptCredential:
    """Refresh under the cross-process lock and save the rotated tokens.

    If another process already refreshed (the saved access token differs
    from ``stale_access_token``), its result is used instead of spending
    the rotated refresh token twice.
    """
    with store.refresh_lock():
        current = store.load()
        if current is None:
            raise ReauthRequired("No saved ChatGPT sign-in. Run login first.")
        if (
            current.access_token
            and current.access_token != stale_access_token
            and current.expires_at - REFRESH_MARGIN_SECONDS > _utc_now()
        ):
            return current
        if not current.refresh_token:
            raise ReauthRequired("Saved sign-in has no refresh token.")
        try:
            token_data = _post_token(
                http,
                endpoints,
                {
                    "grant_type": "refresh_token",
                    "client_id": current.client_id,
                    "refresh_token": current.refresh_token,
                    "resource": RESOURCE,
                },
            )
        except ReauthRequired:
            current.access_token = None
            current.refresh_token = None
            store.save(current)
            raise
        now = _utc_now()
        expires_in, expires_at = _expiry(token_data, now)
        new_refresh = token_data.get("refresh_token")
        if not isinstance(new_refresh, str) or not new_refresh:
            logger.warning("Refresh response had no replacement refresh token")
            new_refresh = current.refresh_token
        updated = dataclasses.replace(
            current,
            access_token=str(token_data["access_token"]),
            refresh_token=new_refresh,
            expires_in=expires_in,
            expires_at=expires_at,
            scopes=_scopes(token_data, current.scopes),
            saved_at=_iso(now),
            earliest_refresh_at=_earliest(token_data),
        )
        store.save(updated)
        return updated


def _remember_issued_client(
    store: CredentialStore,
    *,
    client_id: str,
    host_id: str,
    issuer: str,
) -> None:
    """Save an issued client ID when the code exchange does not finish.

    The next sign-in must reuse this client instead of registering again
    with ``dynamic_agent_client``. No account is verified yet, so
    ``subject`` is empty and no tokens are stored.
    """
    now = _utc_now()
    store.save(
        ChatGptCredential(
            client_id=client_id,
            ext_agent_host_id=host_id,
            issuer=issuer,
            subject="",
            email=None,
            id_token=None,
            access_token=None,
            refresh_token=None,
            token_type="Bearer",
            expires_in=0,
            expires_at=0.0,
            scopes=[],
            saved_at=_iso(now),
        )
    )


def sign_out(
    store: CredentialStore,
    *,
    endpoints: OAuthEndpoints = PRODUCTION_ENDPOINTS,
    http: httpx.Client,
) -> bool:
    """Revoke the refresh token, then clear tokens. True if revoked.

    Load, revocation, and the local clear share the refresh lock so a
    refresh in another process cannot write a new session after sign-out
    returns. Access, refresh, and ID tokens are cleared. The issued
    client ID, host ID, and account mapping (subject and email) stay.
    """
    with store.refresh_lock():
        current = store.load()
        if current is None:
            return True
        revoked = current.refresh_token is None
        if current.refresh_token:
            try:
                endpoint = IdTokenValidator(
                    http, endpoints
                ).revocation_endpoint()
                if endpoint:
                    response = http.post(
                        endpoint,
                        data={
                            "token": current.refresh_token,
                            "token_type_hint": "refresh_token",
                            "client_id": current.client_id,
                        },
                    )
                    revoked = response.status_code == 200
            except (httpx.HTTPError, ChatGptAuthError):
                revoked = False
        current.access_token = None
        current.refresh_token = None
        current.id_token = None
        store.save(current)
        return revoked


class ChatGptTokenProvider:
    """Hands out a valid access token and refreshes it when needed.

    This is the object the ChatGPT-plan API client calls. ``access_token``
    refreshes near expiry; ``force_refresh`` is used after an HTTP 401.
    """

    def __init__(
        self,
        store: CredentialStore,
        *,
        endpoints: OAuthEndpoints = PRODUCTION_ENDPOINTS,
        http: httpx.Client | None = None,
    ) -> None:
        self._store = store
        self._endpoints = endpoints
        self._http = http or httpx.Client(timeout=30.0)
        self._lock = threading.Lock()
        self._credential: Optional[ChatGptCredential] = None

    def _current(self) -> ChatGptCredential:
        if self._credential is None:
            loaded = self._store.load()
            if loaded is None or not loaded.access_token:
                raise ReauthRequired(
                    "No usable ChatGPT sign-in. Run the login command first."
                )
            if not loaded.has_plan_usage():
                raise ReauthRequired(
                    f"Saved sign-in lacks {PLAN_USAGE_SCOPE}; sign in again."
                )
            self._credential = loaded
        return self._credential

    def access_token(self) -> str:
        with self._lock:
            credential = self._current()
            now = _utc_now()
            near_expiry = credential.expires_at - REFRESH_MARGIN_SECONDS <= now
            too_early = (
                credential.earliest_refresh_at is not None
                and now < credential.earliest_refresh_at
                and credential.expires_at > now
            )
            if near_expiry and not too_early:
                credential = self._refresh(credential.access_token)
            assert credential.access_token is not None
            return credential.access_token

    def force_refresh(self, rejected_token: str) -> str:
        with self._lock:
            credential = self._refresh(rejected_token)
            assert credential.access_token is not None
            return credential.access_token

    def _refresh(self, stale: str | None) -> ChatGptCredential:
        self._credential = refresh_credential(
            self._store, stale, endpoints=self._endpoints, http=self._http
        )
        return self._credential
