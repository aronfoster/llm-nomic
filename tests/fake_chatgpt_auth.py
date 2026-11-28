"""In-process fake of OpenAI's SIWC auth server, for offline tests only.

Serves the OpenID configuration, a JWKS, the token endpoint and the
revocation endpoint through ``httpx.MockTransport``, so no socket is
opened (the suite's offline guard blocks every TCP connect, loopback
included). ``authorize`` plays the user's browser: it checks the
authorization URL and delivers the redirect to a fake loopback listener
the way auth.openai.com would. No real OpenAI endpoint is contacted.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.parse
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from src.nomic_engine.llm.chatgpt_oauth import OAuthEndpoints


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class FakeAuthServer:
    """Records every request so tests can assert on exact parameters."""

    def __init__(self) -> None:
        self.key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        )
        self.kid = "fake-key-1"
        self.issued_client_id = "oaiapp_fake_" + secrets.token_hex(4)
        self.subject = "user-fake-subject"
        self.email = "aron@example.invalid"
        self.granted_scope = (
            "chatgpt.tokens.use.direct email offline_access openid profile "
            "resource.invoke"
        )
        self.token_requests: list[dict[str, str]] = []
        self.revocations: list[dict[str, str]] = []
        self.authorize_params: list[dict[str, str]] = []
        self.codes: dict[str, dict[str, str]] = {}
        self.refresh_tokens: set[str] = set()
        self.refresh_error: str | None = None
        self.refresh_status = 400
        self.code_exchange_error: str | None = None
        self.discovery_status = 200
        self.discovery_raw: bytes | None = None
        self.discovery_disconnect = False
        self.jwks_status = 200
        self.token_raw: bytes | None = None
        self.token_counter = 0
        self.expires_in = 3600
        self.base = "https://auth.fake.invalid"
        self.transport = httpx.MockTransport(self._handle)
        self.last_listener: FakeListener | None = None
        self.endpoints = OAuthEndpoints(
            issuer=self.base,
            authorize_url=self.base + "/api/accounts/authorize",
            token_url=self.base + "/api/accounts/oauth/token",
            discovery_url=self.base + "/.well-known/openid-configuration",
        )

    def client(self) -> httpx.Client:
        """An httpx client wired to this fake; no socket is opened."""
        return httpx.Client(transport=self.transport)

    def listener_factory(self, port: int) -> "FakeListener":
        self.last_listener = FakeListener()
        return self.last_listener

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET":
            if path == "/.well-known/openid-configuration":
                if self.discovery_disconnect:
                    raise httpx.ConnectError("discovery down", request=request)
                if self.discovery_raw is not None:
                    return httpx.Response(
                        self.discovery_status,
                        content=self.discovery_raw,
                        headers={"Content-Type": "application/json"},
                    )
                return httpx.Response(
                    self.discovery_status, json=self.discovery()
                )
            if path == "/jwks":
                return httpx.Response(self.jwks_status, json=self.jwks())
            return httpx.Response(404, json={"error": "not_found"})
        form = dict(urllib.parse.parse_qsl(request.content.decode()))
        if path == "/api/accounts/oauth/token":
            if self.token_raw is not None:
                self.token_requests.append(form)
                return httpx.Response(
                    200,
                    content=self.token_raw,
                    headers={"Content-Type": "application/json"},
                )
            status, payload = self.token(form)
            return httpx.Response(status, json=payload)
        if path == "/revoke":
            self.revocations.append(form)
            self.refresh_tokens.discard(form.get("token", ""))
            return httpx.Response(200)
        return httpx.Response(404, json={"error": "not_found"})

    def discovery(self) -> dict[str, Any]:
        return {
            "issuer": self.base,
            "jwks_uri": self.base + "/jwks",
            "revocation_endpoint": self.base + "/revoke",
        }

    def jwks(self) -> dict[str, Any]:
        jwk = json.loads(
            jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key())
        )
        jwk.update({"kid": self.kid, "use": "sig", "alg": "RS256"})
        return {"keys": [jwk]}

    def id_token(
        self,
        nonce: str,
        *,
        client_id: str,
        sub: str | None = None,
        iat_offset: int = 0,
    ) -> str:
        now = int(time.time())
        claims = {
            "iss": self.base,
            "aud": client_id,
            "sub": sub or self.subject,
            "email": self.email,
            "nonce": nonce,
            "iat": now + iat_offset,
            "exp": now + 3600,
        }
        return jwt.encode(
            claims, self.key, algorithm="RS256", headers={"kid": self.kid}
        )

    def _new_tokens(self) -> tuple[str, str]:
        self.token_counter += 1
        access = f"fake-access-{self.token_counter}-{secrets.token_hex(4)}"
        refresh = f"fake-refresh-{self.token_counter}-{secrets.token_hex(4)}"
        self.refresh_tokens.add(refresh)
        return access, refresh

    def token(self, form: dict[str, str]) -> tuple[int, dict[str, Any]]:
        self.token_requests.append(form)
        if form.get("client_id") != self.issued_client_id:
            return 401, {"error": "invalid_client"}
        if form.get("resource") != "https://api.openai.com/v1":
            return 400, {"error": "invalid_target"}
        grant = form.get("grant_type")
        if grant == "authorization_code":
            if self.code_exchange_error:
                self.codes.pop(form.get("code", ""), None)
                return 400, {"error": self.code_exchange_error}
            pending = self.codes.pop(form.get("code", ""), None)
            if pending is None:
                return 400, {"error": "invalid_grant"}
            if form.get("redirect_uri") != pending["redirect_uri"]:
                return 400, {"error": "invalid_grant"}
            digest = hashlib.sha256(
                form.get("code_verifier", "").encode()
            ).digest()
            if _b64url(digest) != pending["code_challenge"]:
                return 400, {"error": "invalid_grant"}
            access, refresh = self._new_tokens()
            return 200, {
                "access_token": access,
                "refresh_token": refresh,
                "id_token": self.id_token(
                    pending["nonce"],
                    client_id=self.issued_client_id,
                    sub=pending.get("sub"),
                ),
                "token_type": "Bearer",
                "expires_in": self.expires_in,
                "scope": pending.get("scope_override", self.granted_scope),
            }
        if grant == "refresh_token":
            if "scope" in form:
                return 400, {"error": "invalid_request"}
            if self.refresh_error:
                return self.refresh_status, {"error": self.refresh_error}
            old = form.get("refresh_token", "")
            if old not in self.refresh_tokens:
                return 400, {"error": "refresh_token_reused"}
            self.refresh_tokens.discard(old)  # rotation: old one is dead
            access, refresh = self._new_tokens()
            return 200, {
                "access_token": access,
                "refresh_token": refresh,
                "token_type": "Bearer",
                "expires_in": self.expires_in,
                "scope": self.granted_scope,
            }
        return 400, {"error": "unsupported_grant_type"}

    def authorize(
        self,
        url: str,
        *,
        sub: str | None = None,
        scope_override: str | None = None,
        deny: bool = False,
        omit_client_id: bool = False,
    ) -> None:
        """Act as the browser plus auth server: redirect to the loopback."""
        parsed = urllib.parse.urlsplit(url)
        assert parsed.scheme + "://" + parsed.netloc + parsed.path == (
            self.endpoints.authorize_url
        )
        params = dict(urllib.parse.parse_qsl(parsed.query))
        self.authorize_params.append(params)
        redirect = params["redirect_uri"]
        if deny:
            query = {"error": "access_denied", "state": params["state"]}
        else:
            code = "code-" + secrets.token_hex(8)
            pending = {
                "redirect_uri": redirect,
                "code_challenge": params["code_challenge"],
                "nonce": params["nonce"],
            }
            if sub:
                pending["sub"] = sub
            if scope_override is not None:
                pending["scope_override"] = scope_override
            self.codes[code] = pending
            query = {"code": code, "state": params["state"]}
            if not omit_client_id:
                query["client_id"] = self.issued_client_id
            query["scope"] = self.granted_scope
        assert self.last_listener is not None
        assert redirect == self.last_listener.redirect_uri
        self.last_listener.deliver(query)


class FakeListener:
    """Stands in for the loopback listener; the browser redirect is a call."""

    redirect_uri = "http://127.0.0.1:1455/auth/callback"

    def __init__(self) -> None:
        self._query: dict[str, str] | None = None
        self.closed = False

    def deliver(self, query: dict[str, str]) -> None:
        self._query = query

    def wait(self, timeout: float) -> dict[str, str]:
        assert self._query is not None, "authorize() was not called"
        return self._query

    def close(self) -> None:
        self.closed = True
