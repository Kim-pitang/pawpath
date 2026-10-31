"""API 전체 흐름 검증. 기획서의 최종 검증 시나리오를 그대로 수행한다."""
from datetime import timedelta

from app.clock import now_local

EXPECTED_SENTENCE = "낯선 길을 싫어하는 두부를 위해 익숙한 공원 코스를 골랐어요. 비가 오기 전 짧게 다녀올 수 있어요."

PET_BODY = {
    "name": "콩",
    "breed": "시바견",
    "age_years": 3,
    "weight_kg": 9.5,
    "size": "medium",
    "activity_level": "high",
    "personality": "active",
    "path_preference": "new",
    "heat_sensitivity": "high",
    "novelty_reaction": "calm",
}
FIVE_STARS = {
    "walk_rating": 5,
    "pet_rating": 5,
    "difficulty": "just_right",
    "weather_rating": 5,
    "would_revisit": True,
    "memo": "꼬리를 흔들며 잘 걸었어요",
}


def dubu_id(client) -> int:
    return next(pet["id"] for pet in client.get("/api/pets").json() if pet["name"] == "두부")


def test_final_verification_scenario(client):
    # 테스트 사용자: 두부와 보호자 일정 16~20시
    pet_id = dubu_id(client)
    pet = client.get(f"/api/pets/{pet_id}").json()
    assert (pet["age_years"], pet["size"], pet["activity_level"], pet["personality"], pet["path_preference"]) == (5, "small", "medium", "timid", "familiar")
    schedule = client.get("/api/schedule").json()
    assert schedule["available_windows"] == [{"start_hour": 16, "end_hour": 20}]

    # 1. 현재 날씨와 시간대별 예보
    current = client.get("/api/weather/current", params={"scenario": "rain_later"})
    assert current.status_code == 200
    assert "temperature" in current.json()["current"]
    forecast = client.get("/api/weather/forecast", params={"scenario": "rain_later"})
    assert len(forecast.json()["hours"]) == 24

    # 2. 5개 이상의 코스
    courses = client.get("/api/courses").json()
    assert len(courses) >= 5
    assert all(course["route"] and course["id"] for course in courses)

    # 3~5. 점수 계산, 상위 3개, 추천 이유
    created = client.post("/api/recommendations", json={"pet_id": pet_id, "weather_scenario": "rain_later"})
    assert created.status_code == 201
    first = created.json()
    assert first["walkable"] is True
    assert len(first["courses"]) == 3
    top = first["courses"][0]
    assert top["reason"]["summary"] == EXPECTED_SENTENCE
    # 기획서의 6개 평가 묶음과 세부 항목을 함께 돌려준다.
    assert [group["key"] for group in top["score_breakdown"]] == ["pet_fit", "user_preference", "weather", "safety", "time", "past_satisfaction"]
    assert len(top["factors"]) == 7
    assert first["weights"] == {"weather": 0.25, "personality": 0.25, "activity": 0.15, "schedule": 0.15, "safety": 0.1, "preference": 0.1, "user_preference": 0.1}
    assert next(f for f in top["factors"] if f["key"] == "preference")["score"] == 50
    assert top["learning_delta"] == 0

    # 저장된 추천을 다시 조회할 수 있다.
    stored = client.get(f"/api/recommendations/{first['id']}").json()
    assert stored["courses"][0]["reason"]["summary"] == EXPECTED_SENTENCE

    # 6. 산책 완료
    target = first["courses"][1]
    walk = client.post(
        "/api/walks",
        json={"pet_id": pet_id, "course_id": target["course_id"], "recommendation_id": first["id"], "duration_min": target["duration_min"]},
    )
    assert walk.status_code == 201
    walk_id = walk.json()["id"]

    # 7. 만족도 5점 피드백
    feedback = client.post("/api/feedback", json={"walk_id": walk_id, **FIVE_STARS})
    assert feedback.status_code == 201
    body = feedback.json()
    assert body["affinity_after"] > body["affinity_before"] == 50

    # 8. 다음 추천에 반영
    second = client.post("/api/recommendations", json={"pet_id": pet_id, "weather_scenario": "rain_later"}).json()
    updated = next(course for course in second["courses"] if course["course_id"] == target["course_id"])
    assert updated["total_score"] > target["total_score"]
    assert updated["learning_delta"] > 0
    assert updated["preference_score"] > 50
    assert second["learning"]["feedback_total"] == 1
    # 시연 시나리오: 2위 코스에 5점을 주면 다음 추천에서 1위로 오른다.
    assert second["courses"][0]["course_id"] == target["course_id"]
    assert second["courses"][0]["rank_change"] == 1
    assert second["weights"]["preference"] > 0.1
    assert second["weights"]["weather"] == first["weights"]["weather"]


def test_pet_create_read_update(client):
    created = client.post("/api/pets", json=PET_BODY)
    assert created.status_code == 201
    pet_id = created.json()["id"]
    assert client.get(f"/api/pets/{pet_id}").json()["name"] == "콩"
    assert len(client.get("/api/pets").json()) == 2

    updated = client.put(f"/api/pets/{pet_id}", json={**PET_BODY, "weight_kg": 10.5, "personality": "curious"})
    assert updated.status_code == 200
    assert updated.json()["weight_kg"] == 10.5
    assert client.get(f"/api/pets/{pet_id}").json()["personality"] == "curious"


def test_profile_change_changes_the_recommendation(client):
    pet_id = dubu_id(client)
    before = client.post("/api/recommendations", json={"pet_id": pet_id}).json()["courses"]
    body = client.get(f"/api/pets/{pet_id}").json()
    changed = {key: body[key] for key in PET_BODY} | {
        "size": "large", "weight_kg": 30, "activity_level": "high", "personality": "active", "path_preference": "new", "novelty_reaction": "calm",
    }
    assert client.put(f"/api/pets/{pet_id}", json=changed).status_code == 200
    after = client.post("/api/recommendations", json={"pet_id": pet_id}).json()["courses"]
    assert [c["course_id"] for c in before] != [c["course_id"] for c in after]


def test_invalid_pet_is_rejected(client):
    assert client.post("/api/pets", json={**PET_BODY, "size": "giant"}).status_code == 422
    assert client.post("/api/pets", json={**PET_BODY, "weight_kg": -1}).status_code == 422
    assert client.post("/api/pets", json={**PET_BODY, "name": ""}).status_code == 422
    assert client.get("/api/pets/9999").status_code == 404
    assert client.post("/api/recommendations", json={"pet_id": 9999}).status_code == 404


def test_schedule_updates_change_recommended_times(client):
    pet_id = dubu_id(client)
    body = {"available_windows": [{"start_hour": 7, "end_hour": 9}], "preferred_duration_min": 30, "walks_per_day": 1}
    assert client.put("/api/schedule", json=body).status_code == 200
    result = client.post("/api/recommendations", json={"pet_id": pet_id}).json()
    assert all(7 <= int(slot["start"][11:13]) < 9 for slot in result["time_recommendation"]["slots"])
    assert all(7 <= int(course["recommended_time"]["start"][11:13]) < 9 for course in result["courses"])


def test_overlapping_windows_are_merged(client):
    body = {
        "available_windows": [{"start_hour": 18, "end_hour": 22}, {"start_hour": 14, "end_hour": 18}, {"start_hour": 7, "end_hour": 9}],
        "preferred_duration_min": 30,
        "walks_per_day": 1,
    }
    saved = client.put("/api/schedule", json=body).json()
    assert saved["available_windows"] == [{"start_hour": 7, "end_hour": 9}, {"start_hour": 14, "end_hour": 22}]


def test_invalid_schedule_is_rejected(client):
    bad = {"available_windows": [{"start_hour": 20, "end_hour": 16}], "preferred_duration_min": 30, "walks_per_day": 1}
    assert client.put("/api/schedule", json=bad).status_code == 422
    empty = {"available_windows": [], "preferred_duration_min": 30, "walks_per_day": 1}
    assert client.put("/api/schedule", json=empty).status_code == 422


def test_weather_scenarios_change_the_outcome(client):
    pet_id = dubu_id(client)
    storm = client.post("/api/recommendations", json={"pet_id": pet_id, "weather_scenario": "heavy_rain"}).json()
    assert storm["walkable"] is False
    assert storm["courses"] == []
    assert storm["indoor_alternatives"]
    assert storm["weather"]["is_mock"] is True
    assert "시연용" in storm["weather"]["notice"]


def test_unknown_scenario_is_rejected(client):
    pet_id = dubu_id(client)
    assert client.post("/api/recommendations", json={"pet_id": pet_id, "weather_scenario": "meteor"}).status_code == 422
    assert client.get("/api/weather/current", params={"scenario": "meteor"}).status_code == 422


def test_walks_and_feedback_are_listed(client):
    pet_id = dubu_id(client)
    course_id = client.get("/api/courses").json()[0]["id"]
    walk = client.post("/api/walks", json={"pet_id": pet_id, "course_id": course_id, "duration_min": 25}).json()
    client.post("/api/feedback", json={"walk_id": walk["id"], **FIVE_STARS})

    walks = client.get("/api/walks", params={"pet_id": pet_id}).json()
    assert len(walks) == 1
    assert walks[0]["feedback"]["pet_rating"] == 5
    feedback = client.get(f"/api/feedback/{pet_id}").json()
    assert len(feedback) == 1
    assert feedback[0]["memo"] == FIVE_STARS["memo"]


def test_duplicate_feedback_is_rejected_and_does_not_inflate_learning(client):
    pet_id = dubu_id(client)
    course_id = client.get("/api/courses").json()[0]["id"]
    walk = client.post("/api/walks", json={"pet_id": pet_id, "course_id": course_id, "duration_min": 25}).json()
    assert client.post("/api/feedback", json={"walk_id": walk["id"], **FIVE_STARS}).status_code == 201
    assert client.post("/api/feedback", json={"walk_id": walk["id"], **FIVE_STARS}).status_code == 409
    assert client.get(f"/api/pets/{pet_id}").json()["feedback_total"] == 1


def test_feedback_validation(client):
    assert client.post("/api/feedback", json={"walk_id": 999, **FIVE_STARS}).status_code == 404
    pet_id = dubu_id(client)
    course_id = client.get("/api/courses").json()[0]["id"]
    walk = client.post("/api/walks", json={"pet_id": pet_id, "course_id": course_id, "duration_min": 25}).json()
    assert client.post("/api/feedback", json={"walk_id": walk["id"], **FIVE_STARS, "pet_rating": 6}).status_code == 422


def test_walk_validation(client):
    pet_id = dubu_id(client)
    assert client.post("/api/walks", json={"pet_id": pet_id, "course_id": 999, "duration_min": 25}).status_code == 404
    assert client.post("/api/walks", json={"pet_id": 999, "course_id": 1, "duration_min": 25}).status_code == 404
    assert client.post("/api/walks", json={"pet_id": pet_id, "course_id": 1, "duration_min": 0}).status_code == 422
    assert client.post("/api/walks", json={"pet_id": pet_id, "course_id": 1, "duration_min": 25, "recommendation_id": 999}).status_code == 404


def test_walk_can_be_logged_for_an_earlier_time_but_not_the_future(client):
    pet_id = dubu_id(client)
    course_id = client.get("/api/courses").json()[0]["id"]
    now = now_local()
    morning = (now - timedelta(days=1)).replace(hour=7, minute=30)
    walk = client.post(
        "/api/walks", json={"pet_id": pet_id, "course_id": course_id, "duration_min": 30, "started_at": morning.isoformat()}
    ).json()
    assert walk["started_at"] == morning.isoformat()
    assert walk["ended_at"] == (morning + timedelta(minutes=30)).isoformat()

    # 타임존이 붙은 시각은 서비스 현지 시각으로 바꿔 저장한다.
    utc = (morning - timedelta(hours=9)).isoformat() + "Z"
    aware = client.post("/api/walks", json={"pet_id": pet_id, "course_id": course_id, "duration_min": 30, "started_at": utc})
    assert aware.status_code == 201
    assert aware.json()["started_at"] == morning.isoformat()

    later = (now + timedelta(hours=2)).isoformat()
    future = client.post("/api/walks", json={"pet_id": pet_id, "course_id": course_id, "duration_min": 30, "started_at": later})
    assert future.status_code == 422
    assert "끝나지 않은" in future.json()["detail"]
    # 방금 시작해서 아직 걷는 중인 시각도 끝난 산책으로 받지 않는다.
    walking = client.post(
        "/api/walks", json={"pet_id": pet_id, "course_id": course_id, "duration_min": 120, "started_at": now.isoformat()}
    )
    assert walking.status_code == 422


def test_walk_without_feedback_can_be_deleted_and_visits_roll_back(client):
    pet_id = dubu_id(client)
    course_id = client.get("/api/courses").json()[0]["id"]

    def visits() -> int:
        courses = client.get(f"/api/pets/{pet_id}/insights").json()["courses"]
        return next((course["visit_count"] for course in courses if course["course_id"] == course_id), 0)

    kept = client.post("/api/walks", json={"pet_id": pet_id, "course_id": course_id, "duration_min": 25}).json()
    mistake = client.post("/api/walks", json={"pet_id": pet_id, "course_id": course_id, "duration_min": 25}).json()
    assert visits() == 2

    assert client.delete(f"/api/walks/{mistake['id']}").status_code == 204
    assert [walk["id"] for walk in client.get("/api/walks", params={"pet_id": pet_id}).json()] == [kept["id"]]
    assert visits() == 1
    assert client.delete(f"/api/walks/{mistake['id']}").status_code == 404

    # 하나뿐인 기록을 지우면 그 코스는 다녀온 적 없는 코스로 돌아간다.
    assert client.delete(f"/api/walks/{kept['id']}").status_code == 204
    assert all(course["course_id"] != course_id for course in client.get(f"/api/pets/{pet_id}/insights").json()["courses"])


def test_walk_with_feedback_cannot_be_deleted(client):
    pet_id = dubu_id(client)
    course_id = client.get("/api/courses").json()[0]["id"]
    walk = client.post("/api/walks", json={"pet_id": pet_id, "course_id": course_id, "duration_min": 25}).json()
    client.post("/api/feedback", json={"walk_id": walk["id"], **FIVE_STARS})

    response = client.delete(f"/api/walks/{walk['id']}")
    assert response.status_code == 409
    assert "학습" in response.json()["detail"]
    assert len(client.get("/api/walks", params={"pet_id": pet_id}).json()) == 1
    assert client.get(f"/api/pets/{pet_id}").json()["feedback_total"] == 1


def test_learning_is_isolated_between_pets(client):
    dubu = dubu_id(client)
    other = client.post("/api/pets", json=PET_BODY).json()["id"]
    course_id = client.get("/api/courses").json()[0]["id"]
    walk = client.post("/api/walks", json={"pet_id": dubu, "course_id": course_id, "duration_min": 25}).json()
    client.post("/api/feedback", json={"walk_id": walk["id"], **FIVE_STARS})

    result = client.post("/api/recommendations", json={"pet_id": other}).json()
    assert result["learning"]["feedback_total"] == 0
    assert all(course["learning_delta"] == 0 for course in result["courses"])


def test_insights_reflect_walks_feedback_and_recommendation_history(client):
    pet_id = dubu_id(client)
    empty = client.get(f"/api/pets/{pet_id}/insights").json()
    assert empty["stats"]["walk_count"] == 0
    assert empty["attributes_learned"] is False

    client.post("/api/recommendations", json={"pet_id": pet_id, "weather_scenario": "rain_later"})
    course = client.get("/api/courses").json()[0]
    walk = client.post(
        "/api/walks",
        json={"pet_id": pet_id, "course_id": course["id"], "duration_min": 25, "started_at": "2026-10-30T16:00:00"},
    ).json()
    client.post("/api/feedback", json={"walk_id": walk["id"], **FIVE_STARS})
    client.post("/api/recommendations", json={"pet_id": pet_id, "weather_scenario": "rain_later"})

    insights = client.get(f"/api/pets/{pet_id}/insights").json()
    assert insights["stats"]["walk_count"] == 1
    assert insights["stats"]["total_distance_km"] == course["distance_km"]
    assert insights["stats"]["average_pet_rating"] == 5
    assert insights["courses"][0]["course_id"] == course["id"]
    assert insights["courses"][0]["affinity"] > 50
    assert insights["attributes_learned"] is True
    assert insights["affinity_history"][0]["after"] > insights["affinity_history"][0]["before"]
    assert [h["feedback_total"] for h in insights["recommendation_history"]] == [0, 1]
    afternoon = next(t for t in insights["time_preferences"] if t["key"] == "afternoon")
    assert afternoon["samples"] == 1
    assert afternoon["score"] > 50


def test_courses_expose_data_provenance(client):
    course = client.get("/api/courses").json()[0]
    assert "OpenStreetMap" in course["data_sources"]["route"]
    assert "lighting" in course["data_sources"]["team_estimates"]
    assert client.get("/api/courses/9999").status_code == 404
