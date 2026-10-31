"""세션 만료, 본인 재확인, 계정 탈퇴와 데이터 삭제."""
import json
import warnings
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import create_engine, delete, event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.clock import now_local
from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.models import AuthSession, OAuthState, User, WalkingCourse
from app.services import account_service, auth_service, user_course_service
from tests.test_api_e2e import FIVE_STARS, PET_BODY, dubu_id
from tests.test_auth import JPEG, PASSWORD, POINTS, other_client, signup
from tests.test_google_auth import callback, google, start  # noqa: F401  google은 픽스처다
from tests.test_user_courses import make_walk, register

SECRET_MEMO = "secret-memo-to-be-erased"
# 공유 캐시라 보호자의 것이 아니고 계정을 지워도 남는 테이블.
SHARED_TABLES = {"weather_records", "walking_courses"}
# 커뮤니티 행은 test_community.py의 탈퇴 테스트가 확인한다. oauth_states는 곧 사라지는 로그인 중간 상태라 계정 데이터가 아니다.
TESTED_ELSEWHERE = {"community_trails", "trail_likes", "trail_bookmarks", "trail_reviews", "trail_review_photos", "oauth_states"}


@pytest.fixture(autouse=True)
def reset_throttle():
    auth_service.throttle.clear()
    yield
    auth_service.throttle.clear()


def edit_sessions(**values) -> None:
    with SessionLocal() as db:
        for session in db.scalars(select(AuthSession)):
            for key, value in values.items():
                setattr(session, key, value)
        db.commit()


def age_reauth() -> None:
    """로그인하고 시간이 지나 본인 확인이 필요한 상태로 만든다."""
    edit_sessions(created_at=now_local() - timedelta(hours=1), reauthenticated_at=None)


def row_counts() -> dict[str, int]:
    with engine.connect() as connection:
        return {table.name: connection.scalar(select(func.count()).select_from(table)) for table in Base.metadata.sorted_tables}


def make_full_account(owner) -> dict:
    """모든 사용자 테이블에 행이 들어가도록 쓴다."""
    pet = owner.post("/api/pets", json=PET_BODY).json()
    recommendation = owner.post("/api/recommendations", json={"pet_id": pet["id"]}).json()
    course_id = recommendation["courses"][0]["course_id"]
    walk = owner.post("/api/walks", json={"pet_id": pet["id"], "course_id": course_id, "duration_min": 20}).json()
    assert owner.post("/api/feedback", json={"walk_id": walk["id"], **FIVE_STARS, "memo": SECRET_MEMO}).status_code == 201
    saved = make_walk(owner, title="두부의 비밀 경로")
    assert owner.patch(f"/api/my-walks/{saved['id']}", json={"memo": SECRET_MEMO, "pet_id": pet["id"]}).status_code == 200
    photo = owner.post(f"/api/my-walks/{saved['id']}/photos", content=JPEG).json()
    course = register(owner, saved["id"]).json()["course"]["id"]
    owner.post("/api/walks", json={"pet_id": pet["id"], "course_id": course, "duration_min": 15})
    token = owner.post(f"/api/my-walks/{saved['id']}/share", json={}).json()["share_token"]
    public = owner.post("/api/my-walks", json={"title": "공개 길", "points": POINTS, "visibility": "public"}).json()
    return {"pet": pet["id"], "saved": saved["id"], "photo": photo["id"], "course": course, "token": token, "public": public["share_token"]}


# ---------- 세션 만료
def test_idle_session_ends_even_though_the_30_days_are_not_over(client):
    signup(client)
    edit_sessions(last_seen_at=now_local() - timedelta(days=auth_service.SESSION_IDLE_DAYS))
    response = client.get("/api/pets")
    assert response.status_code == 401
    assert "만료" in response.json()["detail"]
    assert "Max-Age=0" in response.headers["set-cookie"]
    # 끝난 세션은 서버에 남기지 않는다.
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 0


def test_using_the_app_keeps_the_session_but_never_past_the_30_days(client):
    signup(client)
    almost_idle = now_local() - timedelta(days=auth_service.SESSION_IDLE_DAYS - 1)
    edit_sessions(last_seen_at=almost_idle)
    assert client.get("/api/pets").status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(AuthSession)).last_seen_at > almost_idle
    # 어제까지 썼어도 로그인한 지 30일이 지나면 끝난다.
    edit_sessions(expires_at=now_local(), last_seen_at=now_local())
    assert client.get("/api/pets").status_code == 401


def test_last_seen_is_not_written_on_every_request(client):
    signup(client)
    recent = now_local() - timedelta(minutes=auth_service.TOUCH_MINUTES - 1)
    edit_sessions(last_seen_at=recent)
    client.get("/api/pets")
    with SessionLocal() as db:
        assert db.scalar(select(AuthSession)).last_seen_at == recent


def test_session_from_before_this_column_existed_still_works_then_goes_idle(client):
    signup(client)
    edit_sessions(last_seen_at=None, created_at=now_local() - timedelta(days=1))
    assert client.get("/api/pets").status_code == 200
    edit_sessions(last_seen_at=None, created_at=now_local() - timedelta(days=auth_service.SESSION_IDLE_DAYS))
    assert client.get("/api/pets").status_code == 401


def test_idle_expiry_does_not_fall_back_to_the_demo_account(client):
    demo_pet = dubu_id(client)
    signup(client)
    edit_sessions(last_seen_at=now_local() - timedelta(days=30))
    assert client.get(f"/api/pets/{demo_pet}").status_code == 401


def test_next_login_cleans_up_idle_sessions_of_everyone(client):
    signup(client)
    edit_sessions(last_seen_at=now_local() - timedelta(days=30))
    bob = other_client()
    signup(bob, login_id="bob", name="밥")
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 1


@pytest.mark.parametrize(
    "state",
    [
        pytest.param({"last_seen_at": timedelta(minutes=-auth_service.TOUCH_MINUTES)}, id="시각 갱신"),
        pytest.param({"last_seen_at": timedelta(days=-auth_service.SESSION_IDLE_DAYS)}, id="만료 삭제"),
    ],
)
def test_session_removed_by_a_concurrent_request_does_not_break_this_one(client, state):
    """화면은 같은 쿠키로 요청을 동시에 보낸다. 읽은 직후 다른 요청이 세션을 지워도 오류나 경고가 없어야 한다."""
    signup(client)
    token = client.cookies.get("pawpath_session")
    edit_sessions(**{key: now_local() + value for key, value in state.items()})
    with SessionLocal() as db, warnings.catch_warnings():
        warnings.simplefilter("error")
        read_session = db.scalar

        def read_then_lose_the_race(*args, **kwargs):
            found = read_session(*args, **kwargs)
            with SessionLocal() as other:
                other.execute(delete(AuthSession))
                other.commit()
            return found

        db.scalar = read_then_lose_the_race
        auth_service.find_session(db, token, now_local())


def test_me_ends_an_idle_session_and_reports_a_guest(client):
    signup(client)
    edit_sessions(last_seen_at=now_local() - timedelta(days=30))
    response = client.get("/api/auth/me")
    assert response.json()["authenticated"] is False
    assert "pawpath_session=" in response.headers["set-cookie"]


# ---------- 본인 재확인
def test_fresh_login_needs_no_reauth_but_an_old_one_does(client):
    signup(client)
    assert client.get("/api/auth/account").json()["reauth_required"] is False
    age_reauth()
    assert client.get("/api/auth/account").json()["reauth_required"] is True


def test_reauth_opens_the_window_and_replaces_the_token(client):
    signup(client)
    age_reauth()
    stolen = client.cookies.get("pawpath_session")
    response = client.post("/api/auth/reauth", json={"password": PASSWORD})
    assert response.status_code == 200
    assert response.json() == {"reauth_required": False}
    assert client.get("/api/auth/account").json()["reauth_required"] is False
    renewed = client.cookies.get("pawpath_session")
    assert renewed != stolen
    # 예전 토큰을 훔쳐 둔 사람은 함께 권한을 얻지 못하고 세션에서도 밀려난다.
    thief = other_client()
    thief.cookies.set("pawpath_session", stolen)
    assert thief.delete("/api/auth/account").status_code == 401


def test_reauth_does_not_extend_the_login(client):
    signup(client)
    with SessionLocal() as db:
        before = db.scalar(select(AuthSession)).expires_at
    age_reauth()
    response = client.post("/api/auth/reauth", json={"password": PASSWORD})
    assert f"Max-Age={int((before - now_local()).total_seconds())}" in response.headers["set-cookie"]
    with SessionLocal() as db:
        assert db.scalar(select(AuthSession)).expires_at == before


def test_reauth_window_closes(client):
    signup(client)
    client.post("/api/auth/reauth", json={"password": PASSWORD})
    edit_sessions(reauthenticated_at=now_local() - timedelta(minutes=auth_service.REAUTH_MINUTES))
    assert client.get("/api/auth/account").json()["reauth_required"] is True
    assert client.delete("/api/auth/account").status_code == 403


def test_wrong_password_is_refused_without_ending_the_session(client):
    signup(client)
    age_reauth()
    response = client.post("/api/auth/reauth", json={"password": "wrong-password"})
    assert response.status_code == 403
    assert "비밀번호" in response.json()["detail"]
    assert client.get("/api/auth/me").json()["authenticated"] is True
    assert client.get("/api/auth/account").json()["reauth_required"] is True


def test_reauth_guessing_is_locked_without_locking_the_owner_out_of_login(client):
    signup(client)
    for _ in range(auth_service.MAX_FAILURES):
        assert client.post("/api/auth/reauth", json={"password": "wrong-password"}).status_code == 403
    locked = client.post("/api/auth/reauth", json={"password": PASSWORD})
    assert locked.status_code == 429
    assert "분 뒤" in locked.json()["detail"]
    # 세션을 훔친 사람이 일부러 틀려도 주인은 로그인할 수 있다.
    assert other_client().post("/api/auth/login", json={"login_id": "alice", "password": PASSWORD}).status_code == 200


def test_reauth_requires_a_real_session(client):
    assert client.post("/api/auth/reauth", json={"password": PASSWORD}).status_code == 401
    client.cookies.set("pawpath_session", "not-a-real-token")
    response = client.post("/api/auth/reauth", json={"password": PASSWORD})
    assert response.status_code == 401
    assert "Max-Age=0" in response.headers["set-cookie"]


# ---------- Google 본인 재확인
def google_login(client, google):
    start_params = start(client)
    assert callback(client, start_params, google).status_code == 302
    return client.get("/api/auth/me").json()["user"]


def start_reauth(client) -> dict:
    response = client.get("/api/auth/google/start", params={"reauth": "true"}, follow_redirects=False)
    assert response.status_code == 302, response.text
    return {key: values[0] for key, values in parse_qs(urlparse(response.headers["location"]).query).items()}


def test_google_reauth_with_the_same_account_opens_the_window(client, google):
    user = google_login(client, google)
    age_reauth()
    before = client.cookies.get("pawpath_session")
    params = start_reauth(client)
    assert params["prompt"] == "select_account"
    response = callback(client, params, google)
    assert response.headers["location"] == "/account"
    assert client.cookies.get("pawpath_session") != before
    assert client.get("/api/auth/me").json()["user"]["id"] == user["id"]
    assert client.get("/api/auth/account").json()["reauth_required"] is False
    with SessionLocal() as db:
        # 새 세션을 만들지 않고 지금 세션에 기록한다.
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 1


def test_google_reauth_with_another_account_is_refused_and_creates_nobody(client, google):
    google_login(client, google)
    age_reauth()
    with SessionLocal() as db:
        users = db.scalar(select(func.count()).select_from(User))
    params = start_reauth(client)
    google.user = {**google.user, "sub": "someone-else"}
    response = callback(client, params, google)
    assert response.headers["location"] == "/account?error=google_mismatch"
    assert client.get("/api/auth/account").json()["reauth_required"] is True
    assert client.delete("/api/auth/account").status_code == 403
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(User)) == users


def test_cancelled_google_reauth_comes_back_to_the_account_page(client, google):
    google_login(client, google)
    age_reauth()
    params = start_reauth(client)
    response = client.get("/api/auth/google/callback", params={"state": params["state"], "error": "access_denied"}, follow_redirects=False)
    assert response.headers["location"] == "/account?error=google_cancelled"
    assert client.get("/api/auth/account").json()["reauth_required"] is True


def test_reused_google_reauth_state_is_refused(client, google):
    google_login(client, google)
    params = start_reauth(client)
    assert callback(client, params, google).headers["location"] == "/account"
    client.cookies.set("pawpath_google_state", params["state"], path="/api/auth/google")
    assert callback(client, params, google).headers["location"] == "/account?error=google_state"


def test_google_reauth_cannot_be_finished_from_another_session(client, google):
    """state를 들고 다른 계정의 세션으로 돌아와도 그 세션에 권한이 생기지 않는다."""
    google_login(client, google)
    params = start_reauth(client)
    state_cookie = client.cookies.get("pawpath_google_state", path="/api/auth/google")
    bob = other_client()
    signup(bob, login_id="bob", name="밥")
    age_reauth()
    bob.cookies.set("pawpath_google_state", state_cookie, path="/api/auth/google")
    response = callback(bob, params, google)
    assert response.headers["location"] == "/login?error=google_state"
    assert bob.get("/api/auth/account").json()["reauth_required"] is True


def test_google_reauth_needs_a_session_and_a_google_account(client, google):
    response = client.get("/api/auth/google/start", params={"reauth": "true"}, follow_redirects=False)
    assert response.headers["location"] == "/login"
    signup(client)
    response = client.get("/api/auth/google/start", params={"reauth": "true"}, follow_redirects=False)
    assert response.headers["location"] == "/account?error=google_mismatch"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(OAuthState)) == 0


def test_google_accounts_have_no_password_to_confirm(client, google):
    google_login(client, google)
    response = client.post("/api/auth/reauth", json={"password": PASSWORD})
    assert response.status_code == 409
    assert "Google" in response.json()["detail"]


def test_google_account_can_be_deleted_after_reauth(client, google):
    google_login(client, google)
    age_reauth()
    assert client.delete("/api/auth/account").status_code == 403
    assert callback(client, start_reauth(client), google).headers["location"] == "/account"
    assert client.delete("/api/auth/account").status_code == 204
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.google_sub == google.user["sub"])) is None
    # 같은 Google 계정으로 다시 오면 새 빈 계정이다.
    assert callback(client, start(client), google).status_code == 302
    assert client.get("/api/pets").json() == []


# ---------- 요약
def test_summary_counts_what_will_be_deleted(client, monkeypatch):
    signup(client)
    make_full_account(client)
    body = client.get("/api/auth/account").json()
    assert body["provider"] == "password"
    assert body["session_idle_days"] == auth_service.SESSION_IDLE_DAYS
    assert body["data"] == {"pets": 1, "walks": 2, "feedback": 1, "recommendations": 1, "saved_walks": 2, "photos": 1, "personal_courses": 1, "shared_walks": 2, "community_trails": 0, "trail_reviews": 0}
    # 백업을 끈 서버는 백업 보존 기간을 말하지 않는다.
    assert body["backup_retention_days"] is None
    monkeypatch.setenv("BACKUP_ENABLED", "true")
    get_settings.cache_clear()
    try:
        assert client.get("/api/auth/account").json()["backup_retention_days"] == 14
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_summary_counts_only_my_data(client):
    signup(client)
    make_full_account(client)
    bob = other_client()
    signup(bob, login_id="bob", name="밥")
    assert set(bob.get("/api/auth/account").json()["data"].values()) == {0}


def test_guests_have_no_account_to_see_or_delete(client):
    demo_pet = dubu_id(client)
    assert client.get("/api/auth/account").status_code == 401
    assert client.delete("/api/auth/account").status_code == 401
    assert client.get(f"/api/pets/{demo_pet}").status_code == 200
    with SessionLocal() as db:
        assert db.get(User, 1) is not None


# ---------- 탈퇴
def test_deletion_needs_a_recent_reauth(client):
    signup(client)
    data = make_full_account(client)
    age_reauth()
    response = client.delete("/api/auth/account")
    assert response.status_code == 403
    assert "본인" in response.json()["detail"]
    assert client.get(f"/api/my-walks/{data['saved']}").status_code == 200


def test_deletion_removes_every_row_and_only_this_account(client):
    bob = other_client()
    signup(bob, login_id="bob", name="밥")
    bob_data = make_full_account(bob)
    demo_walk = client.post("/api/my-walks", json={"title": "시연 길", "points": POINTS}).json()
    before = row_counts()

    alice = other_client()
    signup(alice)
    make_full_account(alice)
    filled = row_counts()
    # 행이 없는 테이블은 아래 검사를 그냥 통과한다. 새 테이블은 여기서 먼저 걸려 make_full_account에 더하게 된다.
    assert {table for table, count in filled.items() if count == before[table]} - SHARED_TABLES <= TESTED_ELSEWHERE
    assert alice.delete("/api/auth/account").status_code == 204

    after = row_counts()
    # 테이블을 새로 더해도 탈퇴에서 빠뜨리면 여기서 걸린다.
    for table, count in after.items():
        if table not in SHARED_TABLES:
            assert count == before[table], table
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(WalkingCourse).where(WalkingCourse.owner_user_id.is_not(None))) == 1
    # 다른 계정과 시연 보호자는 그대로다.
    assert bob.get(f"/api/my-walks/{bob_data['saved']}").json()["title"] == "두부의 비밀 경로"
    assert bob.get(f"/api/my-walks/{bob_data['saved']}/photos/{bob_data['photo']}").status_code == 200
    assert bob.get(f"/api/courses/{bob_data['course']}").status_code == 200
    assert client.get(f"/api/my-walks/{demo_walk['id']}").status_code == 200
    assert client.get(f"/api/pets/{dubu_id(client)}").status_code == 200


def test_deletion_ends_sessions_on_every_device(client):
    signup(client)
    phone = other_client()
    assert phone.post("/api/auth/login", json={"login_id": "alice", "password": PASSWORD}).status_code == 200
    response = client.delete("/api/auth/account")
    assert response.status_code == 204
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert response.headers["clear-site-data"] == '"cache"'
    assert client.get("/api/auth/me").json()["authenticated"] is False
    assert phone.get("/api/pets").status_code == 401


def test_deleted_account_cannot_log_in_and_the_id_can_be_used_again(client):
    signup(client)
    make_full_account(client)
    client.delete("/api/auth/account")
    assert client.post("/api/auth/login", json={"login_id": "alice", "password": PASSWORD}).status_code == 401
    assert client.post("/api/auth/signup", json={"login_id": "alice", "password": "another-password-2", "name": "새 앨리스"}).status_code == 201
    assert client.get("/api/pets").json() == []
    assert client.get("/api/my-walks").json() == []


def test_deletion_closes_shared_links_and_public_walks(client):
    signup(client)
    data = make_full_account(client)
    visitor = other_client()
    assert visitor.get(f"/api/shared/{data['token']}").status_code == 200
    assert any(walk["token"] == data["public"] for walk in visitor.get("/api/public-walks").json())
    client.delete("/api/auth/account")
    assert visitor.get(f"/api/shared/{data['token']}").status_code == 404
    assert visitor.get(f"/api/shared/{data['token']}/gpx").status_code == 404
    assert visitor.get(f"/api/shared/{data['public']}").status_code == 404
    assert all(walk["token"] != data["public"] for walk in visitor.get("/api/public-walks").json())


def test_deleted_data_is_not_left_in_the_database_file(client):
    signup(client)
    make_full_account(client)
    path = Path(engine.url.database)
    engine.dispose()
    assert SECRET_MEMO.encode() in path.read_bytes()
    assert client.delete("/api/auth/account").status_code == 204
    engine.dispose()
    data = path.read_bytes()
    # 행만 지우면 내용이 파일의 빈 공간에 남는다.
    assert SECRET_MEMO.encode() not in data
    assert "두부의 비밀 경로".encode() not in data
    assert b"alice" not in data


def test_deletion_order_works_with_foreign_keys_enforced(client):
    """SQLite는 기본으로 외래 키를 검사하지 않는다. 검사하는 DB(PostgreSQL)에서도 순서가 맞는지 켜고 확인한다."""
    signup(client)
    make_full_account(client)
    with SessionLocal() as db:
        user_id = db.scalar(select(User.id).where(User.login_id == "alice"))
    checked = create_engine(engine.url)
    event.listen(checked, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys = ON").close())
    with Session(checked) as db:
        assert db.scalar(text("PRAGMA foreign_keys")) == 1
        # 검사가 정말 켜져 있으면 보호자를 먼저 지울 수 없다.
        with pytest.raises(IntegrityError):
            db.execute(delete(User).where(User.id == user_id))
        db.rollback()
        account_service.delete_user_data(db, user_id)
        db.commit()
    checked.dispose()
    with SessionLocal() as db:
        assert db.get(User, user_id) is None


def test_measurement_finishing_after_deletion_writes_nothing(client, monkeypatch):
    signup(client)
    saved = make_walk(client)
    course_id = register(client, saved["id"]).json()["course"]["id"]
    client.delete("/api/auth/account")
    user_course_service.measure(course_id, "token")
    with SessionLocal() as db:
        assert db.get(WalkingCourse, course_id) is None


def test_ledger_records_the_deletion_without_personal_data(client):
    signup(client)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login_id == "alice"))
        user_id, created_at = user.id, user.created_at
    ledger = Path(get_settings().backup_dir) / account_service.LEDGER_NAME
    ledger.unlink(missing_ok=True)
    client.delete("/api/auth/account")
    text = ledger.read_text(encoding="utf-8")
    entry = json.loads(text)
    assert entry["user_id"] == user_id
    assert entry["user_created_at"] == created_at.isoformat()
    assert set(entry) == {"user_id", "user_created_at", "deleted_at"}
    assert "alice" not in text and "앨리스" not in text
    assert ledger.stat().st_mode & 0o077 == 0


def test_deletion_is_cancelled_when_the_record_cannot_be_written(client, monkeypatch, tmp_path):
    """기록 없이 지우면 백업에서 복구할 때 탈퇴한 보호자가 되살아난다."""
    signup(client)
    data = make_full_account(client)
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("")
    monkeypatch.setenv("BACKUP_DIR", str(blocked))
    monkeypatch.setenv("BACKUP_ENABLED", "true")
    get_settings.cache_clear()
    try:
        response = client.delete("/api/auth/account")
        assert response.status_code == 503
        assert "지운 데이터는 없" in response.json()["detail"]
        assert client.get(f"/api/my-walks/{data['saved']}").status_code == 200
        assert client.get("/api/auth/me").json()["authenticated"] is True
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_deletion_goes_ahead_without_a_record_when_backups_are_off(client, monkeypatch, tmp_path):
    signup(client)
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("")
    monkeypatch.setenv("BACKUP_DIR", str(blocked))
    get_settings.cache_clear()
    try:
        assert client.delete("/api/auth/account").status_code == 204
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
    assert client.post("/api/auth/login", json={"login_id": "alice", "password": PASSWORD}).status_code == 401


def test_failed_reauth_counter_is_forgotten_with_the_account(client):
    signup(client)
    with SessionLocal() as db:
        user_id = db.scalar(select(User.id).where(User.login_id == "alice"))
    client.post("/api/auth/reauth", json={"password": "wrong-password"})
    assert auth_service.throttle._failures.get(f"reauth:{user_id}")
    client.delete("/api/auth/account")
    assert f"reauth:{user_id}" not in auth_service.throttle._failures
