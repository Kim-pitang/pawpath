"""Google OAuth 2.0 로그인. 실제 Google 대신 가짜 토큰 서버로 흐름 전체를 확인한다."""
import base64
import hashlib
import json
import logging
import time
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import get_settings
from app.database import SessionLocal
from app.main import app
from app.models import OAuthState, User
from app.services import google_auth_service
from tests.test_api_e2e import PET_BODY

CLIENT_ID = "test-client.apps.googleusercontent.com"
REDIRECT_URI = "http://testserver/api/auth/google/callback"
# 처음 로그인한 계정은 대표 프로필을 정한 뒤 원래 가려던 곳으로 간다.
FIRST_LOGIN = "/profiles/setup?next=%2Fmy-walks"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def id_token(**claims) -> str:
    """Google 형식의 ID 토큰. 서버가 직접 받은 토큰은 서명을 확인하지 않으므로 서명 자리는 아무 값이다."""
    header = b64(json.dumps({"alg": "RS256", "kid": "test", "typ": "JWT"}).encode())
    return f"{header}.{b64(json.dumps(claims).encode())}.signature"


class FakeGoogle:
    """토큰 엔드포인트를 흉내 낸다. 받은 요청을 기록하고, 정해 둔 사용자로 ID 토큰을 준다."""

    def __init__(self):
        self.requests: list[dict] = []
        self.user = {"sub": "google-user-1", "email": "dubu@example.com", "email_verified": True, "name": "두부 보호자"}
        self.overrides: dict = {}
        self.status = 200
        self.fail_network = False
        self.malformed = False
        self.nonce: str | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.fail_network:
            raise httpx.ConnectTimeout("timeout", request=request)
        form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        self.requests.append({"url": str(request.url), **form})
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "invalid_grant", "error_description": "Bad Request"})
        if self.malformed:
            return httpx.Response(200, json={"id_token": "not-a-jwt"})
        claims = {
            "iss": "https://accounts.google.com",
            "aud": CLIENT_ID,
            "azp": CLIENT_ID,
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
            "nonce": self.nonce,
            **self.user,
            **self.overrides,
        }
        return httpx.Response(200, json={"access_token": "ya29.secret-access", "id_token": id_token(**claims), "token_type": "Bearer", "expires_in": 3599})


@pytest.fixture
def google(monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setattr(google_auth_service, "TRANSPORT", httpx.MockTransport(fake.handler))
    return fake


def start(client, next_path="/my-walks") -> dict:
    response = client.get("/api/auth/google/start", params={"next": next_path}, follow_redirects=False)
    assert response.status_code == 302, response.text
    location = urlparse(response.headers["location"])
    assert (location.scheme, location.netloc, location.path) == ("https", "accounts.google.com", "/o/oauth2/v2/auth")
    params = {key: values[0] for key, values in parse_qs(location.query).items()}
    params["set_cookie"] = response.headers["set-cookie"]
    return params


def callback(client, params: dict, google: FakeGoogle, code="good-code", **override):
    google.nonce = params["nonce"]
    query = {"state": params["state"], "code": code, **override}
    return client.get("/api/auth/google/callback", params=query, follow_redirects=False)


def login(client, google) -> httpx.Response:
    response = callback(client, start(client), google)
    assert response.headers["location"] in {FIRST_LOGIN, "/my-walks"}
    return response


def user_count() -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(User).where(User.google_sub.is_not(None)))


# ---------- 시작
def test_start_sends_the_browser_to_google_with_pkce_state_and_nonce(client):
    params = start(client)
    assert params["response_type"] == "code"
    assert params["client_id"] == CLIENT_ID
    assert params["redirect_uri"] == REDIRECT_URI
    assert params["scope"] == "openid email profile"
    assert params["code_challenge_method"] == "S256"
    assert len(params["state"]) >= 40 and len(params["nonce"]) >= 40
    cookie = params["set_cookie"]
    for part in (f"pawpath_google_state={params['state']}", "HttpOnly", "SameSite=lax", "Path=/api/auth/google", "Max-Age=600"):
        assert part in cookie
    with SessionLocal() as db:
        saved = db.scalar(select(OAuthState))
    # DB에는 state 원문을 두지 않고, PKCE 검증값은 서버에만 남는다.
    assert saved.state_hash == hashlib.sha256(params["state"].encode()).hexdigest()
    assert params["code_challenge"] == b64(hashlib.sha256(saved.code_verifier.encode()).digest())
    assert saved.code_verifier not in str(params)
    assert saved.next_path == "/my-walks"


@pytest.mark.parametrize(
    "next_path, saved",
    [
        ("/my-walks?sort=distance", "/my-walks?sort=distance"),
        ("//evil.example/steal", "/"),
        ("https://evil.example", "/"),
        ("/\\evil.example", "/"),
        ("javascript:alert(1)", "/"),
        ("", "/"),
    ],
)
def test_only_paths_inside_the_app_are_kept_for_after_login(client, next_path, saved):
    start(client, next_path)
    with SessionLocal() as db:
        assert db.scalar(select(OAuthState.next_path)) == saved


# ---------- 성공
def test_callback_exchanges_the_code_on_the_server_and_logs_in(client, google):
    params = start(client)
    response = callback(client, params, google)
    assert response.status_code == 302
    assert response.headers["location"] == FIRST_LOGIN
    cookies = response.headers.get_list("set-cookie")
    assert any(c.startswith("pawpath_session=") and "HttpOnly" in c for c in cookies)
    assert any(c.startswith("pawpath_google_state=") and "Max-Age=0" in c for c in cookies)
    sent = google.requests[0]
    assert sent["url"] == google_auth_service.TOKEN_URL
    assert sent["grant_type"] == "authorization_code"
    assert sent["code"] == "good-code"
    assert sent["client_secret"] == "test-google-secret"
    assert sent["redirect_uri"] == REDIRECT_URI
    # 토큰 교환 때 보낸 검증값이 처음에 보낸 challenge와 맞는다.
    assert b64(hashlib.sha256(sent["code_verifier"].encode()).digest()) == params["code_challenge"]
    me = client.get("/api/auth/me").json()
    assert me["authenticated"] is True
    assert me["user"] == {"id": me["user"]["id"], "name": "두부 보호자", "email": "dubu@example.com"}
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(OAuthState)) == 0


def test_same_google_account_returns_to_the_same_guardian(client, google):
    login(client, google)
    first = client.get("/api/auth/me").json()["user"]["id"]
    client.post("/api/pets", json=PET_BODY)
    client.post("/api/auth/logout")
    google.user["email"] = "new-address@example.com"
    # 두 번째부터는 프로필 설정 없이 원래 가려던 곳으로 간다.
    assert login(client, google).headers["location"] == "/my-walks"
    me = client.get("/api/auth/me").json()["user"]
    assert me["id"] == first
    assert me["email"] == "new-address@example.com"
    assert [pet["name"] for pet in client.get("/api/pets").json()] == [PET_BODY["name"]]
    assert user_count() == 1


def test_other_google_accounts_and_guests_are_kept_apart(client, google):
    login(client, google)
    pet = client.post("/api/pets", json=PET_BODY).json()
    other = TestClient(app)
    google.user = {"sub": "google-user-2", "email": "other@example.com", "email_verified": True, "name": "다른 보호자"}
    login(other, google)
    assert other.get("/api/pets").json() == []
    assert other.get(f"/api/pets/{pet['id']}").status_code == 404
    assert TestClient(app).get(f"/api/pets/{pet['id']}").status_code == 404
    assert user_count() == 2


def test_unverified_email_is_not_stored_and_name_falls_back(client, google):
    google.user = {"sub": "google-user-3", "email": "maybe@example.com", "email_verified": False}
    login(client, google)
    me = client.get("/api/auth/me").json()["user"]
    assert me["email"] is None
    assert me["name"] == "maybe"


# ---------- 실패
def test_state_must_match_the_cookie_of_the_starting_browser(client, google):
    attacker = TestClient(app)
    params = start(attacker)
    # 공격자가 시작한 로그인 주소를 피해자 브라우저가 열어도 쿠키가 없어 로그인되지 않는다(login CSRF).
    response = callback(client, params, google)
    assert response.headers["location"] == "/login?error=google_state"
    assert "pawpath_session" not in response.headers.get("set-cookie", "")
    assert google.requests == []


def test_tampered_state_is_refused(client, google):
    params = start(client)
    response = callback(client, {**params, "state": params["state"] + "x"}, google)
    assert response.headers["location"] == "/login?error=google_state"


def test_state_can_be_used_only_once(client, google):
    params = start(client)
    assert callback(client, params, google).headers["location"] == FIRST_LOGIN
    client.cookies.set("pawpath_google_state", params["state"], path="/api/auth/google")
    assert callback(client, params, google).headers["location"] == "/login?error=google_state"
    assert len(google.requests) == 1


def test_expired_state_is_refused(client, google):
    params = start(client)
    with SessionLocal() as db:
        db.scalar(select(OAuthState)).expires_at = datetime(2020, 1, 1)
        db.commit()
    assert callback(client, params, google).headers["location"] == "/login?error=google_state"
    assert google.requests == []


@pytest.mark.parametrize(
    "error, reason",
    [("access_denied", "google_cancelled"), ("server_error", "google_failed")],
)
def test_errors_from_google_send_the_user_back_with_a_reason(client, google, error, reason):
    params = start(client)
    response = client.get("/api/auth/google/callback", params={"state": params["state"], "error": error}, follow_redirects=False)
    assert response.headers["location"] == f"/login?error={reason}"
    assert client.get("/api/auth/me").json()["authenticated"] is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "someone-else.apps.googleusercontent.com"},
        {"iss": "https://evil.example"},
        {"exp": int(time.time()) - 10},
        {"nonce": "replayed-nonce"},
        {"sub": ""},
    ],
)
def test_wrong_tokens_are_refused(client, google, overrides):
    google.overrides = overrides
    params = start(client)
    google.nonce = params["nonce"]
    if "nonce" in overrides:
        google.overrides = {}
        google.nonce = overrides["nonce"]
        response = client.get("/api/auth/google/callback", params={"state": params["state"], "code": "good-code"}, follow_redirects=False)
    else:
        response = callback(client, params, google)
    assert response.headers["location"] == "/login?error=google_failed"
    assert user_count() == 0


def test_list_audience_containing_this_app_is_accepted(client, google):
    google.overrides = {"aud": ["other-client", CLIENT_ID]}
    login(client, google)
    assert client.get("/api/auth/me").json()["authenticated"] is True


@pytest.mark.parametrize("problem", ["status", "network", "malformed"])
def test_token_endpoint_problems_are_handled(client, google, problem):
    if problem == "status":
        google.status = 400
    elif problem == "network":
        google.fail_network = True
    else:
        google.malformed = True
    response = callback(client, start(client), google)
    assert response.headers["location"] == "/login?error=google_failed"
    assert user_count() == 0


def test_missing_code_is_refused(client, google):
    params = start(client)
    response = client.get("/api/auth/google/callback", params={"state": params["state"]}, follow_redirects=False)
    assert response.headers["location"] == "/login?error=google_failed"


def test_logs_never_contain_codes_or_tokens(client, google, caplog):
    google.status = 400
    params = start(client)
    with caplog.at_level(logging.WARNING):
        callback(client, params, google, code="secret-authorization-code")
    assert "Google 로그인 실패" in caplog.text
    assert "secret-authorization-code" not in caplog.text
    assert "test-google-secret" not in caplog.text
    assert params["state"] not in caplog.text


# ---------- 꺼져 있을 때
def test_disabled_without_client_settings(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "google_client_secret", "")
    assert client.get("/api/auth/me").json()["google_enabled"] is False
    assert client.get("/api/auth/google/start", follow_redirects=False).status_code == 404
    response = client.get("/api/auth/google/callback", params={"state": "x", "code": "y"}, follow_redirects=False)
    assert response.headers["location"] == "/login?error=google_unavailable"


def test_me_reports_google_when_configured(client):
    assert client.get("/api/auth/me").json()["google_enabled"] is True


def test_google_login_works_in_required_mode(client, google, monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_required", True)
    assert client.get("/api/pets").status_code == 401
    login(client, google)
    assert client.get("/api/pets").status_code == 200


def test_access_log_hides_the_code_and_state_in_the_callback_address():
    from app.main import RedactOAuthCallback

    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 0, '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:5000", "GET", "/api/auth/google/callback?code=secret-code&state=secret-state", "1.1", 302), None)
    assert RedactOAuthCallback().filter(record) is True
    message = record.getMessage()
    assert "secret-code" not in message and "secret-state" not in message
    assert "/api/auth/google/callback?[생략]" in message
    other = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 0, '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:5000", "GET", "/api/courses?x=1", "1.1", 200), None)
    RedactOAuthCallback().filter(other)
    assert "/api/courses?x=1" in other.getMessage()

