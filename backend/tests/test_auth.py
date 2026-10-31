"""보호자 계정과 소유자 권한 분리."""
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import Settings, get_settings
from app.database import SessionLocal
from app.main import app
from app.models import AuthSession, User
from tests.test_api_e2e import FIVE_STARS, PET_BODY, dubu_id

POINTS = [{"latitude": 37.5 + i * 0.0003, "longitude": 127.0, "recorded_at": f"2026-10-31T16:00:{i * 10:02d}", "segment": 0} for i in range(4)]
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\x12\x34\xff\xd9"


def sign_in(client, key="alice", name="앨리스"):
    """테스트 전용 로그인(conftest가 E2E_LOGIN을 켠다). 같은 key는 같은 계정이고, 처음이면 Google로 처음 로그인한 것처럼 만든다."""
    response = client.post("/api/e2e/login", json={"key": key, "name": name})
    assert response.status_code == 200, response.text
    return response


def other_client() -> TestClient:
    """같은 서버에 붙는 다른 브라우저. 쿠키를 따로 가진다."""
    return TestClient(app)


# ---------- 로그인
def test_login_gives_a_safe_cookie(client):
    response = sign_in(client)
    cookie = response.headers["set-cookie"]
    for part in ("pawpath_session=", "HttpOnly", "SameSite=lax", "Path=/", "Max-Age=2592000"):
        assert part in cookie
    assert "Secure" not in cookie
    me = client.get("/api/auth/me").json()
    assert me["authenticated"] is True
    assert me["user"] == {"id": me["user"]["id"], "name": "앨리스", "email": "alice@e2e.test"}
    token = client.cookies.get("pawpath_session")
    with SessionLocal() as db:
        stored = db.scalar(select(AuthSession.token_hash))
        # DB에는 토큰 원문을 두지 않는다.
        assert stored != token and len(stored) == 64


def test_cookie_is_secure_behind_https(client):
    response = client.post("/api/e2e/login", json={"key": "secure", "name": "보안"}, headers={"X-Forwarded-Proto": "https"})
    assert "Secure" in response.headers["set-cookie"]


def test_new_account_starts_empty_with_the_default_schedule(client):
    sign_in(client)
    assert client.get("/api/pets").json() == []
    assert client.get("/api/schedule").json()["available_windows"] == [{"start_hour": 16, "end_hour": 20}]
    assert client.get("/api/my-walks").json() == []


@pytest.mark.parametrize("path", ["/api/auth/signup", "/api/auth/login", "/api/auth/reauth"])
def test_password_login_is_gone(client, path):
    """로그인은 Google로만 한다. 예전 비밀번호 API로는 계정을 만들거나 들어갈 수 없다."""
    assert client.post(path, json={"login_id": "alice", "password": "walk-with-dubu-1", "name": "앨리스"}).status_code in (404, 405)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1


def test_e2e_login_is_off_unless_the_setting_turns_it_on():
    """운영 서버에서는 테스트 로그인 경로가 붙지 않는다. 설정을 끈 채로 앱을 새로 불러와 확인한다."""
    code = "from app.main import app; print(any(getattr(r, 'path', '').startswith('/api/e2e') for r in app.routes))"
    env = {**os.environ, "E2E_LOGIN": "false"}
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True, cwd=Path(__file__).parent.parent)
    assert result.stdout.strip() == "False"
    assert Settings.model_fields["e2e_login"].default is False


def test_logout_ends_the_session_on_the_server(client):
    sign_in(client)
    token = client.cookies.get("pawpath_session")
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").json()["authenticated"] is False
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 0
    # 쿠키를 훔쳐 둔 사람이 다시 써도 열리지 않는다.
    stolen = other_client()
    stolen.cookies.set("pawpath_session", token)
    response = stolen.get("/api/pets")
    assert response.status_code == 401
    assert "Max-Age=0" in response.headers["set-cookie"]


def test_expired_session_does_not_fall_back_to_the_demo_account(client):
    sign_in(client)
    with SessionLocal() as db:
        for session in db.scalars(select(AuthSession)):
            session.expires_at = datetime(2020, 1, 1)
        db.commit()
    response = client.get("/api/pets")
    assert response.status_code == 401
    assert "만료" in response.json()["detail"]
    assert "Max-Age=0" in response.headers["set-cookie"]


def test_me_clears_an_unknown_cookie_and_reports_a_guest(client):
    client.cookies.set("pawpath_session", "not-a-real-token")
    response = client.get("/api/auth/me")
    assert response.json() == {"authenticated": False, "auth_required": False, "google_enabled": True, "user": None, "profiles": [], "max_profiles": 5, "current_profile": None, "profile_required": False}
    assert "pawpath_session=" in response.headers["set-cookie"]


def test_expired_sessions_are_cleaned_up_on_the_next_login(client):
    sign_in(client)
    with SessionLocal() as db:
        db.scalar(select(AuthSession)).expires_at = datetime(2020, 1, 1)
        db.commit()
    sign_in(other_client())
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AuthSession).where(AuthSession.expires_at < datetime(2021, 1, 1))) == 0


# ---------- 소유자 분리
def make_owner_data(owner) -> dict:
    pet = owner.post("/api/pets", json=PET_BODY).json()
    recommendation = owner.post("/api/recommendations", json={"pet_id": pet["id"]}).json()
    course_id = recommendation["courses"][0]["course_id"]
    walk = owner.post("/api/walks", json={"pet_id": pet["id"], "course_id": course_id, "duration_min": 20}).json()
    saved = owner.post("/api/my-walks", json={"title": "앨리스의 길", "memo": "비밀", "points": POINTS}).json()
    photo = owner.post(f"/api/my-walks/{saved['id']}/photos", content=JPEG).json()
    return {"pet": pet["id"], "recommendation": recommendation["id"], "walk": walk["id"], "saved": saved["id"], "photo": photo["id"]}


def assert_cannot_touch(intruder, data):
    pet, saved = data["pet"], data["saved"]
    checks = [
        intruder.get(f"/api/pets/{pet}"),
        intruder.put(f"/api/pets/{pet}", json=PET_BODY),
        intruder.get(f"/api/pets/{pet}/insights"),
        intruder.post("/api/recommendations", json={"pet_id": pet}),
        intruder.get(f"/api/recommendations/{data['recommendation']}"),
        intruder.get("/api/walks", params={"pet_id": pet}),
        intruder.get("/api/walks/report", params={"pet_id": pet}),
        intruder.post("/api/feedback", json={"walk_id": data["walk"], **FIVE_STARS}),
        intruder.delete(f"/api/walks/{data['walk']}"),
        intruder.get(f"/api/feedback/{pet}"),
        intruder.get(f"/api/my-walks/{saved}"),
        intruder.patch(f"/api/my-walks/{saved}", json={"title": "탈취"}),
        intruder.get(f"/api/my-walks/{saved}/gpx"),
        intruder.post(f"/api/my-walks/{saved}/share", json={}),
        intruder.post(f"/api/my-walks/{saved}/photos", content=JPEG),
        intruder.get(f"/api/my-walks/{saved}/photos/{data['photo']}"),
        intruder.delete(f"/api/my-walks/{saved}/photos/{data['photo']}"),
        intruder.delete(f"/api/my-walks/{saved}"),
    ]
    assert [response.status_code for response in checks] == [404] * len(checks)
    assert all(item["id"] != pet for item in intruder.get("/api/pets").json())
    assert all(item["id"] != saved for item in intruder.get("/api/my-walks").json())


def test_another_account_cannot_see_or_change_my_data(client):
    sign_in(client)
    data = make_owner_data(client)
    bob = other_client()
    sign_in(bob, key="bob", name="밥")
    assert_cannot_touch(bob, data)
    # 주인은 그대로 쓸 수 있다.
    assert client.get(f"/api/my-walks/{data['saved']}").json()["title"] == "앨리스의 길"
    assert client.get(f"/api/my-walks/{data['saved']}/photos/{data['photo']}").status_code == 200


def test_guest_and_accounts_are_kept_apart(client):
    demo_pet = dubu_id(client)
    demo_walk = client.post("/api/my-walks", json={"title": "시연 길", "points": POINTS}).json()
    alice = other_client()
    sign_in(alice)
    data = make_owner_data(alice)
    # 로그인하지 않은 사용자(시연 보호자)는 계정의 데이터를 볼 수 없다.
    assert_cannot_touch(client, data)
    # 계정도 시연 보호자의 데이터를 볼 수 없다.
    assert alice.get(f"/api/pets/{demo_pet}").status_code == 404
    assert alice.get(f"/api/my-walks/{demo_walk['id']}").status_code == 404


def test_shared_link_still_works_for_anyone(client):
    sign_in(client)
    saved = client.post("/api/my-walks", json={"title": "공유 길", "points": POINTS}).json()
    token = client.post(f"/api/my-walks/{saved['id']}/share", json={}).json()["share_token"]
    assert other_client().get(f"/api/shared/{token}").status_code == 200


# ---------- 로그인 필수 모드
@pytest.fixture
def auth_required(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_required_mode_blocks_guests_but_keeps_public_pages(auth_required, client):
    for path in ("/api/pets", "/api/schedule", "/api/my-walks", "/api/walks"):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.json()["detail"] == "로그인이 필요해요."
    assert client.post("/api/my-walks", json={"title": "x", "points": POINTS}).status_code == 401
    for path in ("/api/health", "/api/courses", "/api/public-walks"):
        assert client.get(path).status_code == 200, path
    assert client.get("/api/auth/me").json() == {"authenticated": False, "auth_required": True, "google_enabled": True, "user": None, "profiles": [], "max_profiles": 5, "current_profile": None, "profile_required": False}
    sign_in(client)
    assert client.get("/api/pets").status_code == 200
    assert client.get("/api/auth/me").json()["auth_required"] is True
