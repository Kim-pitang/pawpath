"""대표 계정과 프로필: 프로필 관리, 프로필 전환, 프로필별 데이터 구분, 가족 기록, 다른 계정 차단, 마이그레이션."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, select, text

from app.config import get_settings
from app.database import Base, SessionLocal
from app.main import app
from app.migrations import ADDED_COLUMNS, ensure_schema, row_counts
from app.models import AuthSession, Profile, SavedWalk, WalkFeedback, WalkHistory
from app.services import auth_service, backup_service, profile_service
from tests.test_api_e2e import FIVE_STARS, PET_BODY, dubu_id
from tests.test_account import start_reauth
from tests.test_auth import sign_in as sign_in_as
from tests.test_google_auth import FIRST_LOGIN, callback, google, start  # noqa: F401  google은 픽스처다

POINTS = [{"latitude": 37.55 + i * 0.0003, "longitude": 126.91, "recorded_at": f"2026-10-30T07:00:{i * 10:02d}", "segment": 0} for i in range(4)]


def browser() -> TestClient:
    return TestClient(app)


def sign_in(client, key="mom", name="엄마") -> dict:
    return sign_in_as(client, key=key, name=name).json()


def add_profile(client, name="아빠", avatar="sun") -> dict:
    response = client.post("/api/profiles", json={"name": name, "avatar_key": avatar})
    assert response.status_code == 201, response.text
    return response.json()


def use_profile(client, profile_id: int) -> dict:
    response = client.post(f"/api/profiles/{profile_id}/select")
    assert response.status_code == 200, response.text
    return response.json()


def walk(client, pet_id: int) -> dict:
    course_id = client.get("/api/courses").json()[0]["id"]
    response = client.post("/api/walks", json={"pet_id": pet_id, "course_id": course_id, "duration_min": 25})
    assert response.status_code == 201, response.text
    return response.json()


def saved_walk(client, title="아침 길") -> dict:
    response = client.post("/api/my-walks", json={"title": title, "points": POINTS})
    assert response.status_code == 201, response.text
    return response.json()


def family(client) -> tuple[dict, dict, int]:
    """대표 프로필(엄마)과 하위 프로필(아빠), 가족 반려동물 한 마리."""
    account = sign_in(client)
    default = account["current_profile"]
    second = add_profile(client)
    pet = client.post("/api/pets", json=PET_BODY).json()
    return default, second, pet["id"]


# ---------- 첫 로그인과 대표 프로필
def test_first_login_creates_the_account_and_a_default_profile_in_use(client):
    account = sign_in(client)
    assert account["authenticated"] is True
    assert account["profile_required"] is False
    [profile] = account["profiles"]
    assert profile["is_default"] is True
    assert profile["name"] == "엄마"
    assert account["current_profile"]["id"] == profile["id"]
    assert account["max_profiles"] == profile_service.MAX_PROFILES == 5


def test_google_first_login_creates_a_default_profile_and_asks_to_set_it_up(client, google):  # noqa: F811
    response = callback(client, start(client), google)
    assert response.headers["location"] == FIRST_LOGIN
    me = client.get("/api/auth/me").json()
    [profile] = me["profiles"]
    assert (profile["name"], profile["is_default"]) == ("두부 보호자", True)
    assert me["current_profile"]["id"] == profile["id"]
    client.post("/api/auth/logout")
    # 같은 Google 계정은 같은 대표 계정으로 돌아오고 프로필을 새로 만들지 않는다.
    assert callback(client, start(client), google).headers["location"] == "/my-walks"
    assert [item["id"] for item in client.get("/api/auth/me").json()["profiles"]] == [profile["id"]]


def test_account_name_can_be_changed_separately_from_profiles(client):
    sign_in(client)
    account = client.patch("/api/auth/account", json={"name": "우리 가족"}).json()
    assert account["user"]["name"] == "우리 가족"
    assert account["current_profile"]["name"] == "엄마"
    assert client.patch("/api/auth/account", json={"name": "  "}).status_code == 422


# ---------- 프로필 관리
def test_profiles_are_limited_to_five_including_the_default(client):
    sign_in(client)
    for index in range(4):
        add_profile(client, name=f"가족{index}")
    response = client.post("/api/profiles", json={"name": "여섯째"})
    assert response.status_code == 409
    assert "5개" in response.json()["detail"]
    assert len(client.get("/api/profiles").json()) == 5


def test_creating_profiles_at_the_same_time_cannot_pass_the_limit(client):
    sign_in(client)
    token = client.cookies.get(auth_service.SESSION_COOKIE)

    def create(index: int) -> int:
        tab = browser()
        tab.cookies.set(auth_service.SESSION_COOKIE, token)
        return tab.post("/api/profiles", json={"name": f"가족{index}"}).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = sorted(pool.map(create, range(8)))
    assert codes == [201] * 4 + [409] * 4
    assert len(client.get("/api/profiles").json()) == 5


def test_profile_names_must_differ_and_avatars_are_checked(client):
    sign_in(client)
    assert client.post("/api/profiles", json={"name": "엄마"}).status_code == 409
    assert client.post("/api/profiles", json={"name": "아빠", "avatar_key": "dragon"}).status_code == 422
    assert client.post("/api/profiles", json={"name": ""}).status_code == 422


def test_profile_can_be_renamed_and_its_avatar_changed(client):
    _, second, _ = family(client)
    updated = client.patch(f"/api/profiles/{second['id']}", json={"name": "아버지", "avatar_key": "moon"}).json()
    assert (updated["name"], updated["avatar_key"]) == ("아버지", "moon")
    assert client.patch(f"/api/profiles/{second['id']}", json={"name": None}).status_code == 422
    assert client.patch(f"/api/profiles/{second['id']}", json={"name": "엄마"}).status_code == 409


def test_default_profile_cannot_be_deleted(client):
    default, _, _ = family(client)
    response = client.delete(f"/api/profiles/{default['id']}")
    assert response.status_code == 409
    assert "대표 프로필" in response.json()["detail"]
    assert len(client.get("/api/profiles").json()) == 2


def test_deleting_a_profile_keeps_its_walks_and_the_family_pets(client):
    _, second, pet_id = family(client)
    use_profile(client, second["id"])
    record = walk(client, pet_id)
    path = saved_walk(client, "아빠 길")
    use_profile(client, client.get("/api/auth/me").json()["profiles"][0]["id"])
    assert client.delete(f"/api/profiles/{second['id']}").status_code == 204

    assert [profile["id"] for profile in client.get("/api/profiles").json()] != [second["id"]]
    assert client.get(f"/api/profiles/{second['id']}").status_code == 404
    assert client.post(f"/api/profiles/{second['id']}/select").status_code == 404
    assert [pet["id"] for pet in client.get("/api/pets").json()] == [pet_id]
    walks = client.get("/api/walks", params={"scope": "family"}).json()
    assert [item["id"] for item in walks] == [record["id"]]
    assert walks[0]["profile"] == {"id": second["id"], "name": "아빠", "avatar_key": "sun", "is_default": False, "deleted": True}
    assert client.get(f"/api/my-walks/{path['id']}").json()["profile"]["deleted"] is True
    # 대표 프로필이 남은 기록을 맡는다.
    assert client.get(f"/api/my-walks/{path['id']}").json()["can_manage"] is True
    # 지운 프로필의 기록도 구성원별로 볼 수 있다.
    assert len(client.get("/api/walks", params={"profile_id": second["id"]}).json()) == 1


def test_deleting_the_profile_in_use_on_another_device_asks_that_device_to_choose_again(client):
    _, second, _ = family(client)
    add_profile(client, "할머니")
    phone = browser()
    sign_in(phone)
    use_profile(phone, second["id"])
    assert client.delete(f"/api/profiles/{second['id']}").status_code == 204
    me = phone.get("/api/auth/me").json()
    assert me["current_profile"] is None and me["profile_required"] is True
    assert phone.get("/api/walks").status_code == 428


# ---------- 로그인과 프로필 선택
def test_login_with_several_profiles_asks_which_profile_until_one_is_chosen(client):
    _, second, pet_id = family(client)
    client.post("/api/auth/logout")
    account = sign_in(client)
    assert account["profile_required"] is True
    assert account["current_profile"] is None
    assert [profile["name"] for profile in account["profiles"]] == ["엄마", "아빠"]
    # 프로필이 필요 없는 API는 그대로 쓴다.
    assert client.get("/api/pets").status_code == 200
    blocked = client.post("/api/walks", json={"pet_id": pet_id, "course_id": 1, "duration_min": 10})
    assert blocked.status_code == 428
    assert "프로필" in blocked.json()["detail"]
    chosen = use_profile(client, second["id"])
    assert chosen["current_profile"]["id"] == second["id"] and chosen["profile_required"] is False
    assert walk(client, pet_id)["profile"]["id"] == second["id"]


def test_login_with_one_profile_goes_straight_in(client):
    sign_in(client)
    client.post("/api/auth/logout")
    account = sign_in(client)
    assert account["profile_required"] is False
    assert account["current_profile"]["name"] == "엄마"


def test_adding_a_profile_keeps_the_profile_in_use(client):
    account = sign_in(client)
    # 프로필이 하나일 때 고르지 않은 세션(예전 세션)이어도 둘째를 만든 뒤 쓰던 프로필이 이어진다.
    with SessionLocal() as db:
        db.execute(text("UPDATE auth_sessions SET profile_id = NULL"))
        db.commit()
    add_profile(client)
    assert client.get("/api/auth/me").json()["current_profile"]["id"] == account["current_profile"]["id"]


def test_switching_profiles_keeps_the_session_and_records_last_use(client):
    _, second, _ = family(client)
    with SessionLocal() as db:
        before = db.scalars(select(AuthSession).order_by(AuthSession.id)).all()
    use_profile(client, second["id"])
    with SessionLocal() as db:
        after = db.scalars(select(AuthSession).order_by(AuthSession.id)).all()
        profile = db.get(Profile, second["id"])
        assert profile.last_active_at is not None
    # 다시 로그인하지 않는다. 같은 세션 행에 고른 프로필만 바뀐다.
    assert [session.id for session in after] == [session.id for session in before]
    assert after[0].profile_id == second["id"]
    assert after[0].token_hash == before[0].token_hash


def test_reauthentication_keeps_the_profile_in_use(client, google):  # noqa: F811
    callback(client, start(client), google)
    second = add_profile(client)
    use_profile(client, second["id"])
    assert callback(client, start_reauth(client), google).headers["location"] == "/account"
    assert client.get("/api/auth/me").json()["current_profile"]["id"] == second["id"]


def test_guests_cannot_manage_profiles(client):
    assert client.get("/api/profiles").status_code == 401
    assert client.post("/api/profiles", json={"name": "몰래"}).status_code == 401
    assert client.post("/api/profiles/1/select").status_code == 401
    # 시연 보호자는 대표 프로필 하나로 계속 쓴다.
    assert client.get("/api/schedule").status_code == 200
    assert walk(client, dubu_id(client))["profile"]["is_default"] is True


# ---------- 프로필별 데이터와 가족 공용 데이터
def test_pets_are_shared_by_every_profile(client):
    _, second, pet_id = family(client)
    use_profile(client, second["id"])
    assert [pet["id"] for pet in client.get("/api/pets").json()] == [pet_id]
    assert client.get(f"/api/pets/{pet_id}").status_code == 200
    assert client.post("/api/recommendations", json={"pet_id": pet_id}).status_code == 201


def test_walks_belong_to_the_profile_that_walked(client):
    default, second, pet_id = family(client)
    mine = walk(client, pet_id)
    use_profile(client, second["id"])
    theirs = walk(client, pet_id)
    assert theirs["profile"]["id"] == second["id"]
    assert [item["id"] for item in client.get("/api/walks").json()] == [theirs["id"]]
    assert {item["id"] for item in client.get("/api/walks", params={"scope": "family"}).json()} == {mine["id"], theirs["id"]}
    assert [item["id"] for item in client.get("/api/walks", params={"profile_id": default["id"]}).json()] == [mine["id"]]
    use_profile(client, default["id"])
    assert [item["id"] for item in client.get("/api/walks", params={"pet_id": pet_id}).json()] == [mine["id"]]


def test_feedback_keeps_the_walking_profile_and_learning_is_shared(client):
    _, second, pet_id = family(client)
    use_profile(client, second["id"])
    record = walk(client, pet_id)
    assert client.post("/api/feedback", json={"walk_id": record["id"], **FIVE_STARS}).status_code == 201
    with SessionLocal() as db:
        assert db.scalar(select(WalkFeedback.profile_id)) == second["id"]
    mine = client.get(f"/api/pets/{pet_id}/insights").json()
    assert mine["stats"]["walk_count"] == 1 and mine["stats"]["feedback_count"] == 1
    use_profile(client, client.get("/api/profiles").json()[0]["id"])
    other = client.get(f"/api/pets/{pet_id}/insights").json()
    assert other["stats"]["walk_count"] == 0 and other["stats"]["feedback_count"] == 0
    # 반려동물이 배운 취향은 가족이 함께 쓴다.
    assert other["attributes"] == mine["attributes"]
    assert client.get(f"/api/pets/{pet_id}/insights", params={"scope": "family"}).json()["stats"]["walk_count"] == 1


def test_weekly_report_is_per_profile_or_family(client):
    _, second, pet_id = family(client)
    walk(client, pet_id)
    use_profile(client, second["id"])
    walk(client, pet_id)
    walk(client, pet_id)
    assert client.get("/api/walks/report", params={"pet_id": pet_id}).json()["summary"]["walk_count"] == 2
    assert client.get("/api/walks/report", params={"pet_id": pet_id, "scope": "family"}).json()["summary"]["walk_count"] == 3


def test_saved_walks_are_listed_per_profile(client):
    _, second, _ = family(client)
    mine = saved_walk(client, "엄마 길")
    use_profile(client, second["id"])
    theirs = saved_walk(client, "아빠 길")
    assert [item["title"] for item in client.get("/api/my-walks").json()] == ["아빠 길"]
    assert {item["title"] for item in client.get("/api/my-walks", params={"scope": "family"}).json()} == {"엄마 길", "아빠 길"}
    assert client.get("/api/my-walks", params={"scope": "family"}).json()[0]["profile"]["name"] in {"엄마", "아빠"}
    # 가족의 산책길은 볼 수 있지만 고치고 지우는 것은 만든 프로필이나 대표 프로필만 한다.
    detail = client.get(f"/api/my-walks/{mine['id']}").json()
    assert detail["can_manage"] is False
    assert client.get(f"/api/my-walks/{mine['id']}/gpx").status_code == 200
    for method, path, body in (
        ("PATCH", f"/api/my-walks/{mine['id']}", {"title": "바꿈"}),
        ("POST", f"/api/my-walks/{mine['id']}/share", {}),
        ("POST", f"/api/my-walks/{mine['id']}/course", None),
        ("DELETE", f"/api/my-walks/{mine['id']}", None),
    ):
        response = client.request(method, path, json=body)
        assert response.status_code == 403, (method, path)
        assert response.json()["detail"] == "만든 프로필이나 대표 프로필만 고칠 수 있어요."
    assert client.get(f"/api/my-walks/{theirs['id']}").json()["can_manage"] is True
    # 대표 프로필은 가족의 산책길을 모두 관리한다.
    use_profile(client, client.get("/api/profiles").json()[0]["id"])
    assert client.patch(f"/api/my-walks/{theirs['id']}", json={"title": "아빠 길 정리"}).status_code == 200


def test_walk_records_of_another_profile_cannot_be_deleted_or_rated(client):
    _, second, pet_id = family(client)
    record = walk(client, pet_id)
    use_profile(client, second["id"])
    assert client.delete(f"/api/walks/{record['id']}").status_code == 403
    assert client.post("/api/feedback", json={"walk_id": record["id"], **FIVE_STARS}).status_code == 403


def test_schedules_and_recommendations_are_per_profile(client):
    default, second, pet_id = family(client)
    early = {"available_windows": [{"start_hour": 6, "end_hour": 8}], "preferred_duration_min": 30, "walks_per_day": 1}
    assert client.put("/api/schedule", json=early).status_code == 200
    mine = client.post("/api/recommendations", json={"pet_id": pet_id}).json()
    use_profile(client, second["id"])
    # 새 프로필은 대표 프로필의 일정으로 시작했지만 각자 고친다.
    assert client.get("/api/schedule").json()["available_windows"] == [{"start_hour": 16, "end_hour": 20}]
    assert client.get("/api/recommendations", params={"pet_id": pet_id}).json() == []
    theirs = client.post("/api/recommendations", json={"pet_id": pet_id}).json()
    assert [item["id"] for item in client.get("/api/recommendations", params={"pet_id": pet_id}).json()] == [theirs["id"]]
    use_profile(client, default["id"])
    assert client.get("/api/schedule").json()["available_windows"] == early["available_windows"]
    assert [item["id"] for item in client.get("/api/recommendations", params={"pet_id": pet_id}).json()] == [mine["id"]]


def test_profile_detail_and_family_overview_count_each_member(client):
    default, second, pet_id = family(client)
    walk(client, pet_id)
    saved_walk(client)
    use_profile(client, second["id"])
    walk(client, pet_id)
    walk(client, pet_id)
    detail = client.get(f"/api/profiles/{second['id']}").json()
    assert detail["activity"]["walk_count"] == 2 and detail["activity"]["saved_walk_count"] == 0
    overview = client.get("/api/family/overview").json()
    assert overview["profile_count"] == 2 and overview["max_profiles"] == 5
    assert overview["totals"]["walk_count"] == 3 and overview["totals"]["saved_walk_count"] == 1
    counts = {member["profile"]["name"]: member["activity"]["walk_count"] for member in overview["members"]}
    assert counts == {"엄마": 1, "아빠": 2}
    assert overview["pets"] == [{"id": pet_id, "name": PET_BODY["name"], "breed": PET_BODY["breed"], "walk_count": 3}]
    assert [item["profile"]["name"] for item in overview["recent_walks"]].count("아빠") == 2


# ---------- 다른 가족 계정 차단
def test_another_family_cannot_use_our_profile_ids(client):
    default, second, pet_id = family(client)
    use_profile(client, second["id"])
    record = walk(client, pet_id)
    path = saved_walk(client)
    other = browser()
    sign_in(other, key="neighbor", name="이웃")
    for method, path_ in (
        ("GET", f"/api/profiles/{second['id']}"),
        ("PATCH", f"/api/profiles/{second['id']}"),
        ("DELETE", f"/api/profiles/{second['id']}"),
        ("POST", f"/api/profiles/{second['id']}/select"),
        ("POST", f"/api/profiles/{default['id']}/select"),
    ):
        assert other.request(method, path_, json={"name": "가로채기"} if method == "PATCH" else None).status_code == 404, (method, path_)
    assert other.get("/api/walks", params={"profile_id": second["id"]}).status_code == 404
    assert other.get("/api/my-walks", params={"profile_id": second["id"]}).status_code == 404
    assert other.get("/api/walks", params={"scope": "family"}).json() == []
    assert other.get(f"/api/my-walks/{path['id']}").status_code == 404
    assert other.delete(f"/api/walks/{record['id']}").status_code == 404
    overview = other.get("/api/family/overview").json()
    assert overview["totals"]["walk_count"] == 0 and [member["profile"]["name"] for member in overview["members"]] == ["이웃"]
    # 고른 프로필은 바뀌지 않았다.
    assert client.get("/api/auth/me").json()["current_profile"]["id"] == second["id"]


def test_public_pages_do_not_reveal_profile_names(client):
    _, second, _ = family(client)
    use_profile(client, second["id"])
    path = saved_walk(client, "아빠 길")
    token = client.post(f"/api/my-walks/{path['id']}/share", json={}).json()["share_token"]
    client.patch(f"/api/my-walks/{path['id']}", json={"visibility": "public"})
    for address in (f"/api/shared/{token}", "/api/public-walks"):
        response = browser().get(address)
        assert response.status_code == 200, address
        assert "profile" not in response.text and "아빠\"" not in response.text, address


def test_a_session_pointing_at_another_familys_profile_is_not_trusted(client):
    _, second, _ = family(client)
    other = browser()
    sign_in(other, key="neighbor", name="이웃")
    # DB가 잘못 가리켜도 서버는 요청마다 계정 소속을 다시 확인한다.
    with SessionLocal() as db:
        session = db.scalar(select(AuthSession).order_by(AuthSession.id.desc()).limit(1))
        session.profile_id = second["id"]
        db.commit()
    me = other.get("/api/auth/me").json()
    assert me["current_profile"]["name"] == "이웃"
    assert other.get("/api/my-walks").status_code == 200
    assert other.post("/api/my-walks", json={"title": "이웃 길", "points": POINTS}).json()["profile"]["name"] == "이웃"


def test_account_deletion_removes_every_profile(client):
    family(client)
    add_profile(client, "할머니")
    assert client.get("/api/auth/account").json()["data"]["profiles"] == 2
    assert client.delete("/api/auth/account").status_code == 204
    # 시연 보호자의 대표 프로필만 남는다.
    with SessionLocal() as db:
        assert set(db.scalars(select(Profile.user_id))) == {1}


# ---------- 마이그레이션
def _pre_profile_engine(tmp_path):
    """프로필이 없던 시절의 DB: 보호자 둘, 반려동물, 산책 기록과 피드백, 추천, 산책길, 세션."""
    engine = create_engine(f"sqlite:///{tmp_path}/legacy.db")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        for table, columns in ADDED_COLUMNS.items():
            added = {name for name, _ in columns}
            kept = [row[1] for row in connection.execute(text(f"PRAGMA table_info({table})")) if row[1] not in added]
            connection.execute(text(f"CREATE TABLE {table}_old AS SELECT {', '.join(kept)} FROM {table}"))
            connection.execute(text(f"DROP TABLE {table}"))
            connection.execute(text(f"ALTER TABLE {table}_old RENAME TO {table}"))
        connection.execute(text("DROP TABLE profiles"))
        for user_id, name in ((1, "보호자"), (2, "앨리스")):
            connection.execute(text(f"INSERT INTO users (id, name, available_windows, preferred_duration_min, walks_per_day, created_at, updated_at) VALUES ({user_id}, '{name}', '[{{\"start_hour\": 7, \"end_hour\": 9}}]', 30, 2, '2026-10-01', '2026-10-01')"))
            connection.execute(text(f"INSERT INTO pets (id, user_id, name, breed, age_years, weight_kg, size, activity_level, personality, path_preference, heat_sensitivity, novelty_reaction, learned_attribute_weights, learned_time_buckets, feedback_total, created_at, updated_at) VALUES ({user_id}, {user_id}, '반려{user_id}', '말티즈', 5, 4, 'small', 'medium', 'timid', 'familiar', 'medium', 'anxious', '{{}}', '{{}}', 1, '2026-10-01', '2026-10-01')"))
            connection.execute(text(f"INSERT INTO walking_courses (id, code, name, description, area, start_lat, start_lng, distance_km, duration_min, route, has_park, park_names, lighting, is_paved, surface_note, crowd_level, pet_allowed, pet_rule_note, facilities, is_familiar, shade_level, difficulty, traffic_exposure, scenery_tags, data_sources) VALUES ({user_id}, 'c{user_id}', '코스', '', '망원', 37.5, 126.9, 1, 20, '[]', 1, '[]', 'good', 1, '', 'low', 1, '', '[]', 1, 0.5, 'easy', 'low', '[]', '{{}}')"))
            connection.execute(text(f"INSERT INTO recommendations (id, pet_id, weather_source, weather_scenario, walkable, payload, created_at) VALUES ({user_id}, {user_id}, 'mock', 'live', 1, '{{}}', '2026-10-02')"))
            connection.execute(text(f"INSERT INTO walk_histories (id, pet_id, course_id, started_at, ended_at, duration_min, created_at) VALUES ({user_id}, {user_id}, {user_id}, '2026-10-02 07:00', '2026-10-02 07:20', 20, '2026-10-02')"))
            connection.execute(text(f"INSERT INTO walk_feedbacks (id, walk_id, pet_id, course_id, walk_rating, pet_rating, difficulty, weather_rating, would_revisit, memo, signal, affinity_before, affinity_after, created_at) VALUES ({user_id}, {user_id}, {user_id}, {user_id}, 5, 5, 'easy', 5, 1, '', 1, 50, 55, '2026-10-02')"))
            connection.execute(text(f"INSERT INTO saved_walks (id, user_id, title, memo, source_type, started_at, distance_m, has_timestamps, point_count, visibility, share_memo, route_hash, preview, created_at, updated_at) VALUES ({user_id}, {user_id}, '길', '', 'recorded', '2026-10-02', 100, 1, 2, 'private', 0, 'h{user_id}', '[]', '2026-10-02', '2026-10-03 08:00:00.000000')"))
        connection.execute(text("INSERT INTO auth_sessions (id, user_id, token_hash, created_at, expires_at) VALUES (1, 2, 'hash', '2026-10-30', '2026-11-29')"))
    return engine


def test_migration_gives_every_account_a_default_profile_and_links_its_records(tmp_path):
    engine = _pre_profile_engine(tmp_path)
    assert "profiles" not in inspect(engine).get_table_names()
    before = row_counts(engine)
    added = ensure_schema(engine)
    assert {"walk_histories.profile_id", "saved_walks.profile_id", "recommendations.profile_id", "walk_feedbacks.profile_id", "auth_sessions.profile_id", "users.email"} <= set(added)
    after = row_counts(engine)
    assert {name: count for name, count in after.items() if name != "profiles"} == before
    with engine.connect() as connection:
        profiles = connection.execute(text("SELECT id, user_id, name, is_default, available_windows, preferred_duration_min, walks_per_day FROM profiles ORDER BY user_id")).all()
        assert [(row.user_id, row.name, row.is_default) for row in profiles] == [(1, "보호자", 1), (2, "앨리스", 1)]
        # 일정도 계정 값으로 옮긴다.
        assert (profiles[1].preferred_duration_min, profiles[1].walks_per_day) == (30, 2)
        default_of = {row.user_id: row.id for row in profiles}
        for table in ("walk_histories", "walk_feedbacks", "recommendations"):
            rows = connection.execute(text(f"SELECT {table}.profile_id, pets.user_id FROM {table} JOIN pets ON pets.id = {table}.pet_id")).all()
            assert all(profile_id == default_of[user_id] for profile_id, user_id in rows), table
        saved = connection.execute(text("SELECT profile_id, user_id, updated_at FROM saved_walks ORDER BY id")).all()
        assert [(row.profile_id, row.user_id) for row in saved] == [(default_of[1], 1), (default_of[2], 2)]
        # 고친 시각을 마이그레이션 시각으로 바꾸지 않는다.
        assert str(saved[0].updated_at).startswith("2026-10-03 08:00")
        # 예전 세션은 끊기지 않는다. 프로필이 하나라 고르지 않아도 그 프로필로 쓴다.
        assert connection.execute(text("SELECT count(*) FROM auth_sessions")).scalar_one() == 1


def test_migration_can_run_again_without_duplicating_profiles(tmp_path):
    engine = _pre_profile_engine(tmp_path)
    ensure_schema(engine)
    first = row_counts(engine)
    assert ensure_schema(engine) == []
    assert row_counts(engine) == first
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM profiles")).scalar_one() == 2


def test_failed_migration_rolls_back_profiles_and_can_run_again(tmp_path):
    engine = _pre_profile_engine(tmp_path)
    # 프로필 잇기의 마지막 단계에서 실패하게 만든다.
    with engine.begin() as connection:
        connection.execute(text("CREATE TRIGGER fail_migration BEFORE UPDATE ON saved_walks BEGIN SELECT RAISE(ABORT, 'boom'); END"))
    before = row_counts(engine)
    with pytest.raises(Exception, match="boom"):
        ensure_schema(engine)
    with engine.connect() as connection:
        # 앞서 만든 프로필과 산책 기록 연결이 모두 되돌아가고, 다른 데이터는 그대로다.
        assert connection.execute(text("SELECT count(*) FROM profiles")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM walk_histories WHERE profile_id IS NOT NULL")).scalar_one() == 0
    assert {name: count for name, count in row_counts(engine).items() if name != "profiles"} == before
    with engine.begin() as connection:
        connection.execute(text("DROP TRIGGER fail_migration"))
    assert ensure_schema(engine) == []
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM profiles")).scalar_one() == 2
        assert connection.execute(text("SELECT count(*) FROM saved_walks WHERE profile_id IS NULL")).scalar_one() == 0


def test_migrate_stops_and_names_the_backup_when_rows_are_lost(tmp_path, monkeypatch):
    engine = _pre_profile_engine(tmp_path)
    settings = get_settings()
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/legacy.db")
    monkeypatch.setattr(settings, "backup_dir", str(tmp_path / "backups"))
    counts = iter([{"walk_histories": 2}, {"walk_histories": 1}])
    monkeypatch.setattr(backup_service.migrations, "row_counts", lambda _: next(counts))
    with pytest.raises(backup_service.BackupError, match=r"walk_histories 2→1.*restore pre-migration-20261031-200000\.db"):
        backup_service.migrate(engine, settings, now=datetime(2026, 10, 31, 20, 0), force_backup=True)


def test_only_one_default_profile_per_account(tmp_path):
    engine = _pre_profile_engine(tmp_path)
    ensure_schema(engine)
    with engine.begin() as connection:
        with pytest.raises(Exception):
            connection.execute(text("INSERT INTO profiles (user_id, name, avatar_key, is_default, available_windows, preferred_duration_min, walks_per_day, created_at, updated_at) VALUES (2, '둘째 대표', 'paw', 1, '[]', 40, 1, '2026-10-31', '2026-10-31')"))


def test_migrate_backs_up_first_and_compares_row_counts(tmp_path, monkeypatch):
    engine = _pre_profile_engine(tmp_path)
    settings = get_settings()
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/legacy.db")
    monkeypatch.setattr(settings, "backup_dir", str(tmp_path / "backups"))
    report = backup_service.migrate(engine, settings, now=datetime(2026, 10, 31, 20, 0), force_backup=True)
    assert report.backup is not None and report.backup.name == "pre-migration-20261031-200000.db"
    assert report.before["walk_histories"] == report.after["walk_histories"] == 2
    assert report.after["profiles"] == 2 and "profiles" not in report.before
    # 백업은 프로필이 없던 그대로이고 복구할 수 있는 상태다.
    verified = backup_service.verify_backup(report.backup)
    assert verified.rows["users"] == 2 and "profiles" not in verified.rows
    # 바꿀 것이 없으면 다시 백업하지 않는다.
    assert backup_service.migrate(engine, settings, force_backup=True).backup is None


def test_restoring_a_pre_profile_backup_links_profiles_again(tmp_path, monkeypatch):
    engine = _pre_profile_engine(tmp_path)
    settings = get_settings()
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/legacy.db")
    monkeypatch.setattr(settings, "backup_dir", str(tmp_path / "backups"))
    report = backup_service.migrate(engine, settings, now=datetime(2026, 10, 31, 20, 0), force_backup=True)
    engine.dispose()
    target = tmp_path / "restored.db"
    backup_service.restore_backup(report.backup, target, tmp_path / "backups", datetime(2026, 10, 31, 21, 0))
    restored = create_engine(f"sqlite:///{target}")
    with restored.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM profiles WHERE is_default")).scalar_one() == 2
        assert connection.execute(text("SELECT count(*) FROM walk_histories WHERE profile_id IS NULL")).scalar_one() == 0


def test_new_records_always_have_a_profile(client):
    pet_id = dubu_id(client)
    walk(client, pet_id)
    saved_walk(client)
    client.post("/api/recommendations", json={"pet_id": pet_id})
    with SessionLocal() as db:
        for model in (WalkHistory, SavedWalk):
            assert db.scalar(select(func.count()).select_from(model).where(model.profile_id.is_(None))) == 0
