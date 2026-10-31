"""REST API 라우터."""
import logging
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.clock import now_local, to_local
from app.database import get_db
from app.config import get_settings
from app.models import CommunityTrail, Pet, Recommendation, SavedWalk, SavedWalkPhoto, TrailBookmark, TrailLike, TrailReview, TrailReviewPhoto, User, WalkFeedback, WalkHistory, WalkingCourse
from app.recommender.features import build_features
from app.recommender.safety import DEMO, FORECAST, assess_conditions, assess_course, assessment_payload
from app.recommender.timeslots import evaluate_slot, hour_comfort, is_rainy
from app.recommender.types import FeedbackInput
from app.seed import DEFAULT_USER_ID
from app.services import auth_service, community_service, google_auth_service, saved_walk_service
from app.services.alternative_service import ALL_DAY, evaluate_alternative
from app.services.gpx_service import MAX_GPX_BYTES, GpxError, build_gpx, content_disposition, parse_gpx
from app.services.llm_service import enhance_recommendation
from app.services.photo_service import MAX_PHOTO_BYTES, MAX_PHOTOS_PER_WALK, PhotoError, clean_image
from app.services.places_service import PLACE_LABELS, nearby_places
from app.services import user_course_service
from app.services.recommendation_service import active_courses, create_recommendation, load_state, scoring_config, to_course_data, to_profile, to_schedule, windows_of
from app.services.report_service import build_report, is_simulated, walked_km
from app.services import route_fit_service, route_generator
from app.services.routing_service import Approach, build_router, plan_approach
from app.services.walk_service import build_insights, record_walk, remove_walk, submit_feedback
from app.services.weather_service import WeatherResult, get_weather

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """로그인한 보호자. 로그인이 필수가 아니면 로그인하지 않은 요청은 시연 보호자(id 1)로 처리한다.

    모든 사용자 데이터 API가 이 값으로 반려동물과 산책길의 주인을 확인한다.
    """
    token = request.cookies.get(auth_service.SESSION_COOKIE)
    if token:
        user = auth_service.user_for_token(db, token, now_local())
        if user is None:
            # 만료된 세션으로 시연 보호자의 데이터를 보여 주지 않도록 막고, 쿠키를 지운다.
            raise HTTPException(401, "로그인이 만료되었어요. 다시 로그인해 주세요.", headers={"Set-Cookie": auth_service.EXPIRED_COOKIE})
        return user
    if get_settings().auth_required:
        raise HTTPException(401, "로그인이 필요해요.")
    user = db.get(User, DEFAULT_USER_ID)
    if user is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "초기 데이터가 준비되지 않았습니다")
    return user


def viewer(request: Request, db: Session = Depends(get_db)) -> User | None:
    """로그인 없이도 열리는 코스 화면의 보는 사람. 내 산책길 코스를 주인에게만 보이려고 쓴다. 오류를 내지 않는다."""
    token = request.cookies.get(auth_service.SESSION_COOKIE)
    if token:
        return auth_service.user_for_token(db, token, now_local())
    if get_settings().auth_required:
        return None
    return db.get(User, DEFAULT_USER_ID)


def signed_in_user(request: Request, db: Session = Depends(get_db)) -> User:
    """실제로 로그인한 보호자. 커뮤니티에 글을 남기는 API는 시연 보호자를 인정하지 않는다."""
    token = request.cookies.get(auth_service.SESSION_COOKIE)
    if not token:
        raise HTTPException(401, "로그인이 필요해요.")
    user = auth_service.user_for_token(db, token, now_local())
    if user is None:
        raise HTTPException(401, "로그인이 만료되었어요. 다시 로그인해 주세요.", headers={"Set-Cookie": auth_service.EXPIRED_COOKIE})
    return user


def signed_in_viewer(request: Request, db: Session = Depends(get_db)) -> User | None:
    """커뮤니티를 보는 사람. 로그인하지 않았으면 비어 있다. 시연 보호자로 바꾸지 않아 서로의 좋아요가 섞이지 않는다."""
    token = request.cookies.get(auth_service.SESSION_COOKIE)
    return auth_service.user_for_token(db, token, now_local()) if token else None


def _visible_course(db: Session, course_id: int, user: User | None) -> WalkingCourse:
    """공용 코스이거나 내 코스일 때만 돌려준다. 다른 보호자의 코스는 없는 것과 같다."""
    course = db.get(WalkingCourse, course_id)
    if course is not None and course.community_trail_id is not None:
        if not community_service.course_open_to(db, course, user):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "코스를 찾을 수 없습니다")
        return course
    # 공유를 해제해 경로를 지운 커뮤니티 코스는 산책 기록을 위해 행만 남아 있다.
    if course is None or not course.route or (course.owner_user_id is not None and (user is None or course.owner_user_id != user.id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "코스를 찾을 수 없습니다")
    return course


def _get_pet(db: Session, pet_id: int, user: User) -> Pet:
    pet = db.get(Pet, pet_id)
    if pet is None or pet.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "반려동물을 찾을 수 없습니다")
    return pet


@router.get("/health", tags=["시스템"])
def health() -> dict:
    return {"status": "ok", "service": "PawPath"}


# 계정
def _account(user: User | None) -> schemas.AccountRead:
    settings = get_settings()
    return schemas.AccountRead(
        authenticated=user is not None,
        auth_required=settings.auth_required,
        google_enabled=settings.google_enabled,
        user=None
        if user is None
        else schemas.AccountUser(
            id=user.id,
            name=user.name,
            login_id=user.login_id,
            email=user.google_email,
            provider="google" if user.google_sub else "password",
        ),
    )


def _is_https(request: Request) -> bool:
    # HTTPS로 접속했을 때만 Secure를 붙인다. localhost 개발 서버는 HTTP다.
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def _start_session(request: Request, response: Response, db: Session, user: User) -> None:
    token = auth_service.create_session(db, user, now_local())
    response.set_cookie(
        auth_service.SESSION_COOKIE,
        token,
        max_age=auth_service.SESSION_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=_is_https(request),
        path="/",
    )


@router.post("/auth/signup", response_model=schemas.AccountRead, status_code=status.HTTP_201_CREATED, tags=["계정"])
def signup(body: schemas.SignupRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> schemas.AccountRead:
    try:
        user = auth_service.signup(db, body.login_id, body.password, body.name)
    except auth_service.AuthError as error:
        raise HTTPException(error.status_code, error.message) from error
    _start_session(request, response, db, user)
    return _account(user)


@router.post("/auth/login", response_model=schemas.AccountRead, tags=["계정"])
def login(body: schemas.LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> schemas.AccountRead:
    try:
        user = auth_service.login(db, body.login_id, body.password)
    except auth_service.AuthError as error:
        raise HTTPException(error.status_code, error.message) from error
    _start_session(request, response, db, user)
    return _account(user)


@router.post("/auth/logout", response_model=schemas.AccountRead, tags=["계정"])
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> schemas.AccountRead:
    token = request.cookies.get(auth_service.SESSION_COOKIE)
    if token:
        auth_service.end_session(db, token)
    response.delete_cookie(auth_service.SESSION_COOKIE, path="/", httponly=True, samesite="lax")
    return _account(None)


@router.get("/auth/google/start", tags=["계정"])
def google_start(request: Request, next_path: str = Query(default="/", alias="next"), db: Session = Depends(get_db)) -> RedirectResponse:
    """Google 로그인 화면으로 보낸다. 로그인 뒤에는 next 경로(앱 안의 경로만)로 돌아온다."""
    settings = get_settings()
    if not settings.google_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "이 서버에는 Google 로그인이 설정되어 있지 않아요.")
    state, url = google_auth_service.begin(db, settings, google_auth_service.safe_next(next_path), now_local())
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        google_auth_service.STATE_COOKIE,
        state,
        max_age=google_auth_service.STATE_MINUTES * 60,
        httponly=True,
        samesite="lax",
        secure=_is_https(request),
        path=google_auth_service.STATE_COOKIE_PATH,
    )
    return response


@router.get("/auth/google/callback", tags=["계정"])
def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Google이 돌려보내는 주소. 성공하면 세션 쿠키를 주고 앱으로, 실패하면 이유와 함께 로그인 화면으로 보낸다."""

    def finish(location: str) -> RedirectResponse:
        response = RedirectResponse(location, status_code=status.HTTP_302_FOUND)
        response.delete_cookie(google_auth_service.STATE_COOKIE, path=google_auth_service.STATE_COOKIE_PATH, httponly=True, samesite="lax")
        return response

    settings = get_settings()
    if not settings.google_enabled:
        return finish("/login?error=google_unavailable")
    if error:
        return finish("/login?error=google_cancelled" if error == "access_denied" else "/login?error=google_failed")
    try:
        user, next_path = google_auth_service.complete(db, settings, code, state, request.cookies.get(google_auth_service.STATE_COOKIE), now_local())
    except google_auth_service.GoogleAuthError as failure:
        logger.warning("Google 로그인 실패: %s", failure.detail)
        return finish(f"/login?error={failure.reason}")
    response = finish(next_path)
    _start_session(request, response, db, user)
    return response


@router.get("/auth/me", response_model=schemas.AccountRead, tags=["계정"])
def me(request: Request, response: Response, db: Session = Depends(get_db)) -> schemas.AccountRead:
    """로그인 상태. 만료된 쿠키는 지우고 로그인하지 않은 상태로 알려 준다."""
    token = request.cookies.get(auth_service.SESSION_COOKIE)
    user = auth_service.user_for_token(db, token, now_local()) if token else None
    if token and user is None:
        response.delete_cookie(auth_service.SESSION_COOKIE, path="/", httponly=True, samesite="lax")
    return _account(user)


# 반려동물
@router.post("/pets", response_model=schemas.PetRead, status_code=status.HTTP_201_CREATED, tags=["반려동물"])
def create_pet(body: schemas.PetCreate, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Pet:
    pet = Pet(user_id=user.id, **body.model_dump())
    db.add(pet)
    db.commit()
    return pet


@router.get("/pets", response_model=list[schemas.PetRead], tags=["반려동물"])
def list_pets(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[Pet]:
    return list(db.scalars(select(Pet).where(Pet.user_id == user.id).order_by(Pet.id)))


@router.get("/pets/{pet_id}", response_model=schemas.PetRead, tags=["반려동물"])
def get_pet(pet_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Pet:
    return _get_pet(db, pet_id, user)


@router.put("/pets/{pet_id}", response_model=schemas.PetRead, tags=["반려동물"])
def update_pet(
    pet_id: int,
    body: schemas.PetUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Pet:
    pet = _get_pet(db, pet_id, user)
    # 새 선택 항목을 모르는 예전 요청이 저장된 값을 지우지 않도록 보낸 값만 바꾼다.
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(pet, key, value)
    db.commit()
    return pet


@router.get("/pets/{pet_id}/insights", tags=["반려동물"])
def pet_insights(pet_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    return build_insights(db, _get_pet(db, pet_id, user))


# 보호자 일정
def _merge_windows(windows: list[schemas.TimeWindowSchema]) -> list[dict]:
    """겹치거나 이어지는 시간대를 합친다. 산책이 시간대 경계를 넘어도 가능 시간 안으로 판단한다."""
    merged: list[dict] = []
    for window in sorted(windows, key=lambda w: w.start_hour):
        if merged and window.start_hour <= merged[-1]["end_hour"]:
            merged[-1]["end_hour"] = max(merged[-1]["end_hour"], window.end_hour)
        else:
            merged.append(window.model_dump())
    return merged


@router.get("/schedule", response_model=schemas.ScheduleSchema, tags=["보호자 일정"])
def get_schedule(user: User = Depends(current_user)) -> User:
    return user


@router.put("/schedule", response_model=schemas.ScheduleSchema, tags=["보호자 일정"])
def update_schedule(
    body: schemas.ScheduleSchema,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> User:
    user.available_windows = _merge_windows(body.available_windows)
    user.preferred_duration_min = body.preferred_duration_min
    user.walks_per_day = body.walks_per_day
    db.commit()
    return user


# 날씨
def _load_weather(db: Session, user: User, scenario: str) -> WeatherResult:
    return get_weather(db, now_local(), windows_of(user), scenario)


def _condition(rainy: bool, temperature: float) -> str:
    """하늘 상태 데이터는 받지 않으므로 강수와 기온으로 알 수 있는 내용만 말한다."""
    if rainy:
        return "비 소식 있음"
    if temperature >= 28:
        return "더움"
    if temperature >= 20:
        return "따뜻함"
    if temperature >= 10:
        return "선선함"
    if temperature >= 0:
        return "쌀쌀함"
    return "추움"


@router.get("/weather/current", response_model=schemas.CurrentWeather, tags=["날씨"])
def weather_current(
    scenario: schemas.WeatherScenario = "live",
    pet_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    result = _load_weather(db, user, scenario)
    current = result.hours[0]

    hint = "오늘의 산책각을 확인해 보세요."
    if pet_id is not None:
        pet = _get_pet(db, pet_id, user)
        comfort = hour_comfort(current, build_features(to_profile(pet)))
        hint = f"지금 {pet.name} 기준 날씨 적합도 {comfort:.0f}점"

    return {
        "source": result.source,
        "scenario": result.scenario,
        "is_mock": result.is_mock,
        "notice": result.notice,
        "current": current,
        "condition": _condition(is_rainy(current), current.temperature),
        "walk_comfort_hint": hint,
    }


@router.get("/weather/forecast", response_model=schemas.ForecastWeather, tags=["날씨"])
def weather_forecast(
    scenario: schemas.WeatherScenario = "live",
    hours: int = Query(default=24, ge=1, le=48),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    result = _load_weather(db, user, scenario)
    return {
        "source": result.source,
        "scenario": result.scenario,
        "is_mock": result.is_mock,
        "notice": result.notice,
        "hours": result.hours[:hours],
    }


# 산책 코스
@router.get("/courses", response_model=list[schemas.CourseDetail], tags=["산책 코스"])
def list_courses(db: Session = Depends(get_db), user: User | None = Depends(viewer)) -> list[WalkingCourse]:
    """지금 지역의 추천 후보 코스. 로그인했거나 시연 보호자라면 내 산책길 코스도 함께 돌려준다."""
    return active_courses(db, user)


@router.get("/courses/{course_id}", response_model=schemas.CourseDetail, tags=["산책 코스"])
def get_course(course_id: int, db: Session = Depends(get_db), user: User | None = Depends(viewer)) -> WalkingCourse:
    return _visible_course(db, course_id, user)


@router.post("/courses/{course_id}/approach", response_model=schemas.ApproachRead, tags=["산책 코스"])
def course_approach(
    course_id: int,
    body: schemas.ApproachRequest,
    db: Session = Depends(get_db),
    user: User | None = Depends(viewer),
) -> Approach:
    """현재 위치에서 코스 출발점까지의 도보 경로. 위치는 저장하지 않으며, 로그에 남지 않도록 본문으로 받는다."""
    course = _visible_course(db, course_id, user)
    return plan_approach((body.latitude, body.longitude), (course.start_lat, course.start_lng))


@router.get("/courses/{course_id}/nearby", tags=["산책 코스"])
def course_nearby(
    course_id: int,
    radius_m: int = Query(default=300, ge=50, le=1000),
    types: str | None = Query(default=None, description="쉼표로 구분. 비우면 전체"),
    db: Session = Depends(get_db),
    user: User | None = Depends(viewer),
) -> dict:
    """코스 경로 주변 시설. 미리 수집한 OSM 자료에서 찾으며 사용자 위치는 받지 않는다."""
    course = _visible_course(db, course_id, user)
    wanted = {item.strip() for item in types.split(",") if item.strip()} if types else None
    if wanted and wanted - set(PLACE_LABELS):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "지원하지 않는 시설 종류입니다")
    return nearby_places(course, radius_m, wanted)


# 경로
@router.post("/routes/walking", response_model=schemas.ApproachRead, tags=["경로"])
def walking_route(body: schemas.WalkingRouteRequest) -> Approach:
    """두 지점 사이의 도보 경로. 코스를 벗어났을 때 돌아갈 길을 다시 찾는 데 쓴다."""
    return plan_approach((body.from_latitude, body.from_longitude), (body.to_latitude, body.to_longitude))


def generation_gate() -> route_generator.GenerationGate:
    route_generator.gate.cooldown_s = get_settings().generation_cooldown_seconds
    return route_generator.gate


def generation_router():
    """경유점 경로를 한 번에 받는 라우터. 길찾기를 쓰지 않거나 지원하지 않으면 None."""
    built = build_router(get_settings())
    return built if hasattr(built, "route_via") else None


NO_CANDIDATE_NOTICE = (
    "이 위치와 시간에는 기준에 맞는 순환 경로를 찾지 못했어요. 시간을 늘리거나 출발 위치를 바꿔 보세요. "
    "강변처럼 되돌아와야 하는 길이 많은 곳에서는 짧은 산책 경로가 만들어지지 않을 수 있어요."
)


def _fit_payload(fit: route_fit_service.CandidateFit) -> dict:
    return {
        "score": fit.score,
        "level": fit.level,
        "summary": fit.summary,
        "details": fit.details,
        "cautions": fit.cautions,
        "highlights": fit.highlights,
        "start_label": fit.start_label,
        "unknown": fit.unknown,
        "excluded": fit.excluded,
    }


@router.post("/routes/generate", response_model=schemas.GenerateRouteResponse, tags=["경로"])
def generate_route(
    body: schemas.GenerateRouteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    gate: route_generator.GenerationGate = Depends(generation_gate),
    path_router=Depends(generation_router),
) -> dict:
    """출발점과 원하는 산책 시간으로 순환 경로 후보를 만든다. 공용 길찾기 서버를 쓰므로 수 초 걸린다.

    pet_id를 주면 후보를 그 반려동물의 성향, 날씨, 일정, 지난 피드백으로 평가해 맞는 순서로 돌려준다.
    위치는 계산에만 쓰고 저장하지 않는다. 마음에 드는 후보는 내 산책길로 저장해 쓴다.
    """
    if path_router is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "길찾기를 사용하지 않아 경로를 만들 수 없어요.")
    pet = _get_pet(db, body.pet_id, user) if body.pet_id is not None else None
    try:
        gate.acquire(user.id)
    except route_generator.GenerationBusy as busy:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(busy), headers={"Retry-After": str(busy.retry_after_s)})
    rest = True
    report = None
    settings = get_settings()
    try:
        result = route_generator.generate(
            (body.latitude, body.longitude),
            body.duration_min,
            path_router,
            interval_s=settings.routing_min_interval_seconds,
            max_total_s=settings.generation_max_seconds,
            bearing_count=settings.generation_bearings,
            radius_scales=settings.generation_radius_scale_list,
            spreads=settings.generation_spread_list,
            max_requests=settings.generation_max_requests,
            # 반려동물을 알면 넉넉히 만든 뒤 엔진 점수로 추리고, 모르면 길 품질 순으로 바로 자른다.
            max_results=max(settings.generation_pool_size, settings.generation_max_results) if pet is not None else settings.generation_max_results,
        )
        if pet is not None and result.candidates:
            weather = _load_weather(db, user, body.weather_scenario)
            report = route_fit_service.fit_candidates(
                [c.points for c in result.candidates],
                to_profile(pet),
                to_schedule(user),
                load_state(db, pet),
                weather,
                now_local(),
                scoring_config(),
                body.duration_min,
            )
    except route_generator.RouteGenerationError:
        rest = False  # 우리 쪽 요청 때문이 아닌 서버 장애라 바로 다시 시도할 수 있게 한다.
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "길찾기 서버에서 경로를 받지 못했어요. 잠시 뒤 다시 시도해 주세요.")
    finally:
        gate.release(user.id, rest)

    order = (report.order if report else list(range(len(result.candidates))))[: settings.generation_max_results]
    fit_notice = None
    if report:
        if report.blocked_reasons and all(fit.score is None for fit in report.fits):
            fit_notice = "지금은 산책을 권하지 않는 조건이에요: " + " / ".join(report.blocked_reasons[:2])
        elif not report.environment_measured:
            fit_notice = "주변 환경(도로, 조명, 나무, 공원)을 측정하지 못한 경로가 있어요. 그 항목은 '확인 불가'로 보고 계산했어요."
    return {
        "target_min": body.duration_min,
        "candidates": [
            {
                "route": c.points,
                "distance_m": c.distance_m,
                "duration_min": c.duration_min,
                "repeated_pct": c.repeated_pct,
                "start_snap_m": c.start_snap_m,
                "fit": _fit_payload(report.fits[index]) if report else None,
            }
            for index in order
            for c in [result.candidates[index]]
        ],
        "notice": None if result.candidates else NO_CANDIDATE_NOTICE,
        "scored_for": pet.name if report else None,
        "fit_notice": fit_notice,
    }


@router.post("/routes/alternative", tags=["경로"])
def route_alternative(
    body: schemas.AlternativeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    """산책 중 날씨를 다시 평가해 계속 걸을지, 줄일지, 돌아갈지와 대체 코스를 알려 준다."""
    pet = _get_pet(db, body.pet_id, user)
    course = _visible_course(db, body.course_id, user)
    if (body.latitude is None) != (body.longitude is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "위도와 경도를 함께 보내 주세요")
    position = (body.latitude, body.longitude) if body.latitude is not None else None
    return evaluate_alternative(db, pet, user, course, position, body.progress_m, body.weather_scenario, now_local())


# 안전 지수
@router.get("/safety", tags=["안전 지수"])
def safety(
    pet_id: int,
    course_id: int | None = None,
    scenario: schemas.WeatherScenario = "live",
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    """지금 환경의 안전 평가. course_id를 주면 그 코스를 지금 걷는 경우를 평가한다."""
    pet = _get_pet(db, pet_id, user)
    now = now_local()
    result = _load_weather(db, user, scenario)
    features = build_features(to_profile(pet))
    source = DEMO if result.is_mock else FORECAST
    weather = {"source": result.source, "scenario": result.scenario, "is_mock": result.is_mock, "notice": result.notice}

    if course_id is None:
        return {"course_id": None, "checked_at": now, "weather": weather, "assessment": assessment_payload(assess_conditions(result.hours[0], features, source))}

    course = _visible_course(db, course_id, user)
    forecast = {hour.time: hour for hour in result.hours}
    slot = evaluate_slot(now, course.duration_min, ALL_DAY, forecast, features, load_state(db, pet), now)
    if slot is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "예보를 찾지 못했습니다")
    return {"course_id": course.id, "checked_at": now, "weather": weather, "assessment": assessment_payload(assess_course(to_course_data(course), slot, features, source))}


# 추천
def _recommendation_response(record: Recommendation) -> dict:
    return {"id": record.id, "created_at": record.created_at, **record.payload}


@router.post("/recommendations", status_code=status.HTTP_201_CREATED, tags=["추천"])
def post_recommendation(
    body: schemas.RecommendationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    pet = _get_pet(db, body.pet_id, user)
    return _recommendation_response(create_recommendation(db, pet, user, body.weather_scenario, now_local()))


@router.get("/recommendations", tags=["추천"])
def list_recommendations(
    pet_id: int,
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict]:
    _get_pet(db, pet_id, user)
    records = db.scalars(
        select(Recommendation).where(Recommendation.pet_id == pet_id).order_by(Recommendation.id.desc()).limit(limit)
    )
    return [_recommendation_response(record) for record in records]


@router.get("/recommendations/{recommendation_id}", tags=["추천"])
def get_recommendation(
    recommendation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    record = db.get(Recommendation, recommendation_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "추천 결과를 찾을 수 없습니다")
    _get_pet(db, record.pet_id, user)
    return _recommendation_response(record)


@router.post("/recommendations/{recommendation_id}/explain", tags=["추천"])
def explain_recommendation(
    recommendation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    """추천 이유를 LLM 문장으로 보강한다. 점수는 바꾸지 않으며, LLM이 꺼져 있거나 실패하면 그대로 돌려준다."""
    record = db.get(Recommendation, recommendation_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "추천 결과를 찾을 수 없습니다")
    pet = _get_pet(db, record.pet_id, user)
    return _recommendation_response(enhance_recommendation(db, record, pet))


# 산책 기록
WALK_CLOCK_SKEW = timedelta(minutes=30)


def _walk_response(walk: WalkHistory) -> dict:
    return {
        "id": walk.id,
        "pet_id": walk.pet_id,
        "course_id": walk.course_id,
        "course_name": walk.course.name,
        "distance_km": round(walked_km(walk), 2),
        "recommendation_id": walk.recommendation_id,
        "tracking_source": walk.tracking_source or "manual",
        "is_simulated": is_simulated(walk),
        "started_at": walk.started_at,
        "ended_at": walk.ended_at,
        "duration_min": walk.duration_min,
        "feedback": walk.feedback,
        "community_trail_id": walk.course.community_trail_id,
    }


@router.post("/walks", response_model=schemas.WalkRead, status_code=status.HTTP_201_CREATED, tags=["산책 기록"])
def post_walk(body: schemas.WalkCreate, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    pet = _get_pet(db, body.pet_id, user)
    course = _visible_course(db, body.course_id, user)
    if body.recommendation_id is not None:
        recommendation = db.get(Recommendation, body.recommendation_id)
        if recommendation is None or recommendation.pet_id != pet.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "추천 결과를 찾을 수 없습니다")
    now = now_local()
    started_at = to_local(body.started_at) if body.started_at is not None else None
    # 휴대폰과 서버 시계가 조금 어긋나도 막지 않도록 여유를 둔다.
    if started_at is not None and started_at + timedelta(minutes=body.duration_min) > now + WALK_CLOCK_SKEW:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "아직 끝나지 않은 시각입니다. 다녀온 산책만 기록할 수 있습니다")
    walk = record_walk(
        db,
        pet,
        course,
        body.duration_min,
        started_at,
        body.recommendation_id,
        now,
        tracking_source=body.tracking_source,
        distance_km=body.distance_km,
    )
    return _walk_response(walk)


@router.delete("/walks/{walk_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["산책 기록"])
def delete_walk(walk_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> None:
    """잘못 남긴 산책 기록을 지운다. 피드백을 남긴 산책은 이미 학습에 반영되어 지우지 않는다."""
    walk = db.get(WalkHistory, walk_id)
    if walk is None or walk.pet.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "산책 기록을 찾을 수 없습니다")
    if walk.feedback is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "피드백을 남긴 산책은 학습에 반영되어 지울 수 없습니다")
    remove_walk(db, walk)


@router.get("/walks", response_model=list[schemas.WalkRead], tags=["산책 기록"])
def list_walks(
    pet_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict]:
    query = select(WalkHistory).join(Pet).where(Pet.user_id == user.id)
    if pet_id is not None:
        _get_pet(db, pet_id, user)
        query = query.where(WalkHistory.pet_id == pet_id)
    return [_walk_response(walk) for walk in db.scalars(query.order_by(WalkHistory.started_at.desc()))]


@router.get("/walks/report", tags=["산책 기록"])
def walks_report(
    pet_id: int,
    week_offset: int = Query(default=0, ge=-52, le=0, description="0은 이번 주, -1은 지난주"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    """주간 활동 리포트. 시연용 산책은 통계에서 빼고 건수만 따로 알려 준다."""
    return build_report(db, _get_pet(db, pet_id, user), now_local(), week_offset)


# 피드백
def _feedback_response(feedback: WalkFeedback) -> dict:
    return {
        "id": feedback.id,
        "walk_id": feedback.walk_id,
        "pet_id": feedback.pet_id,
        "course_id": feedback.course_id,
        "course_name": feedback.course.name,
        "walk_rating": feedback.walk_rating,
        "pet_rating": feedback.pet_rating,
        "difficulty": feedback.difficulty,
        "weather_rating": feedback.weather_rating,
        "would_revisit": feedback.would_revisit,
        "memo": feedback.memo,
        "signal": feedback.signal,
        "affinity_before": feedback.affinity_before,
        "affinity_after": feedback.affinity_after,
        "created_at": feedback.created_at,
    }


@router.post("/feedback", response_model=schemas.FeedbackRead, status_code=status.HTTP_201_CREATED, tags=["피드백"])
def post_feedback(body: schemas.FeedbackCreate, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    walk = db.get(WalkHistory, body.walk_id)
    if walk is None or walk.pet.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "산책 기록을 찾을 수 없습니다")
    if walk.feedback is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 피드백을 남긴 산책입니다")
    feedback = FeedbackInput(
        walk_rating=body.walk_rating,
        pet_rating=body.pet_rating,
        difficulty=body.difficulty,
        weather_rating=body.weather_rating,
        would_revisit=body.would_revisit,
    )
    return _feedback_response(submit_feedback(db, walk, feedback, body.memo, now_local()))


@router.get("/feedback/{pet_id}", response_model=list[schemas.FeedbackRead], tags=["피드백"])
def list_feedback(pet_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict]:
    _get_pet(db, pet_id, user)
    records = db.scalars(select(WalkFeedback).where(WalkFeedback.pet_id == pet_id).order_by(WalkFeedback.id.desc()))
    return [_feedback_response(record) for record in records]


# 나만의 산책길
GPX_MEDIA_TYPE = "application/gpx+xml"


def _get_saved_walk(db: Session, walk_id: int, user: User) -> SavedWalk:
    walk = db.get(SavedWalk, walk_id)
    if walk is None or walk.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "산책길을 찾을 수 없습니다")
    return walk


def _walk_summary(walk: SavedWalk) -> schemas.SavedWalkSummary:
    summary = schemas.SavedWalkSummary.model_validate(walk)
    summary.pet_name = walk.pet.name if walk.pet else None
    return summary


def _personal_course(walk: SavedWalk) -> schemas.PersonalCourseRead | None:
    course = walk.course
    if course is None:
        return None
    sources = course.data_sources or {}
    in_area = course.area == get_settings().service_area_label
    measurement = user_course_service.measurement_status(course, now_local())
    notes = {
        "pending": ["주변 도로, 조명, 노면, 나무, 공원을 OpenStreetMap에서 측정하고 있어요. 보통 30초 안팎 걸리고, 그동안은 확인 불가로 계산해요."],
        "failed": ["OpenStreetMap 응답을 받지 못해 차량 노출, 조명, 노면, 그늘, 공원을 확인 불가로 계산해요. 다시 측정해 보세요."],
        "off": ["서버 설정으로 주변 환경을 측정하지 않아 차량 노출, 조명, 노면, 그늘, 공원을 확인 불가로 계산해요."],
    }.get(measurement, [])
    notes.append("혼잡도와 경사는 측정할 수 없어 확인 불가로 표시돼요.")
    if course.is_active and not in_area:
        notes.append(f"지금 서버 지역({get_settings().service_area_label})과 달라 추천에는 나오지 않아요.")
    return schemas.PersonalCourseRead(
        id=course.id,
        active=course.is_active,
        area=course.area,
        in_current_area=in_area,
        environment_measured=bool(course.environment),
        measurement=measurement,
        unknown=list(sources.get("unknown", [])),
        notes=notes,
    )


def _walk_detail(walk: SavedWalk) -> schemas.SavedWalkDetail:
    return schemas.SavedWalkDetail(
        **_walk_summary(walk).model_dump(),
        course=_personal_course(walk),
        memo=walk.memo,
        share_token=walk.share_token,
        share_expires_at=walk.share_expires_at,
        share_memo=walk.share_memo,
        route=saved_walk_service.route_segments(walk.points),
        photos=[schemas.PhotoRead.model_validate(photo) for photo in walk.photos],
    )


async def _read_limited(request: Request, limit: int, message: str) -> bytes:
    """파일을 끝까지 받기 전에 크기를 확인한다."""
    too_large = HTTPException(413, message)
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > limit:
        raise too_large
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise too_large
        chunks.append(chunk)
    return b"".join(chunks)


async def _read_gpx_body(request: Request) -> bytes:
    return await _read_limited(request, MAX_GPX_BYTES, f"파일이 너무 커요. {MAX_GPX_BYTES // (1024 * 1024)}MB까지 가져올 수 있어요.")


async def _read_photo_body(request: Request) -> bytes:
    return await _read_limited(request, MAX_PHOTO_BYTES, f"사진이 너무 커요. {MAX_PHOTO_BYTES // (1024 * 1024)}MB까지 올릴 수 있어요.")


@router.post("/my-walks/import/preview", response_model=schemas.GpxPreview, tags=["나만의 산책길"])
def preview_gpx_import(data: bytes = Depends(_read_gpx_body), db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    """GPX 원본을 본문으로 받아 검증하고 저장 전 미리보기를 돌려준다. 저장은 하지 않는다."""
    try:
        parsed = parse_gpx(data)
    except GpxError as error:
        raise HTTPException(422, str(error)) from error
    return saved_walk_service.preview_gpx(db, user, parsed)


@router.post("/my-walks", response_model=schemas.SavedWalkDetail, status_code=status.HTTP_201_CREATED, tags=["나만의 산책길"])
def create_saved_walk(
    body: schemas.SavedWalkCreate,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> schemas.SavedWalkDetail:
    if body.pet_id is not None:
        _get_pet(db, body.pet_id, user)
    walk, created = saved_walk_service.create_saved_walk(db, user, body)
    if not created:
        response.status_code = status.HTTP_200_OK
    return _walk_detail(walk)


@router.get("/my-walks", response_model=list[schemas.SavedWalkSummary], tags=["나만의 산책길"])
def list_saved_walks(
    sort: schemas.SavedWalkSort = "recent",
    pet_id: int | None = None,
    visibility: schemas.Visibility | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[schemas.SavedWalkSummary]:
    return [_walk_summary(walk) for walk in saved_walk_service.list_saved_walks(db, user, sort, pet_id, visibility)]


@router.get("/my-walks/{walk_id}", response_model=schemas.SavedWalkDetail, tags=["나만의 산책길"])
def get_saved_walk(walk_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> schemas.SavedWalkDetail:
    return _walk_detail(_get_saved_walk(db, walk_id, user))


@router.patch("/my-walks/{walk_id}", response_model=schemas.SavedWalkDetail, tags=["나만의 산책길"])
def update_saved_walk(
    walk_id: int,
    body: schemas.SavedWalkUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> schemas.SavedWalkDetail:
    walk = _get_saved_walk(db, walk_id, user)
    changes = body.model_dump(exclude_unset=True)
    # 반려동물 연결만 비울 수 있다. 나머지 항목을 null로 보내면 저장하지 않고 알려 준다.
    cleared = [key for key, value in changes.items() if value is None and key != "pet_id"]
    if cleared:
        raise HTTPException(422, f"비울 수 없는 항목이에요: {', '.join(cleared)}")
    if changes.get("pet_id") is not None:
        _get_pet(db, changes["pet_id"], user)
    return _walk_detail(saved_walk_service.update_saved_walk(db, walk, changes))


@router.delete("/my-walks/{walk_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["나만의 산책길"])
def delete_saved_walk(walk_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> None:
    walk = _get_saved_walk(db, walk_id, user)
    # 이 코스로 남긴 산책 기록이 있을 수 있어 코스는 지우지 않고 추천에서만 뺀다.
    user_course_service.detach(db, walk)
    # 커뮤니티에 공유한 글과 좋아요, 저장, 후기도 함께 지워진다.
    community_service.before_walk_deleted(db, walk)
    db.delete(walk)
    db.commit()


@router.post("/my-walks/{walk_id}/course", response_model=schemas.SavedWalkDetail, tags=["나만의 산책길"])
def register_course(
    walk_id: int,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> schemas.SavedWalkDetail:
    """산책길을 내 추천 후보 코스로 등록한다. 주변 환경은 응답을 보낸 뒤 측정하며, 다시 부르면 다시 측정한다."""
    walk = _get_saved_walk(db, walk_id, user)
    try:
        course, token = user_course_service.register(db, user, walk, get_settings(), now_local())
    except user_course_service.CourseError as error:
        raise HTTPException(422, str(error)) from error
    if token:
        background.add_task(user_course_service.measure, course.id, token)
    return _walk_detail(walk)


@router.delete("/my-walks/{walk_id}/course", response_model=schemas.SavedWalkDetail, tags=["나만의 산책길"])
def unregister_course(walk_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> schemas.SavedWalkDetail:
    """추천 후보에서 뺀다. 이 코스로 남긴 산책 기록과 피드백은 그대로 둔다."""
    walk = _get_saved_walk(db, walk_id, user)
    user_course_service.unregister(db, walk)
    return _walk_detail(walk)


@router.get("/my-walks/{walk_id}/gpx", tags=["나만의 산책길"])
def export_saved_walk(walk_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    walk = _get_saved_walk(db, walk_id, user)
    return Response(
        build_gpx(walk.title, saved_walk_service.to_gpx_points(walk)),
        media_type=GPX_MEDIA_TYPE,
        headers={"Content-Disposition": content_disposition(walk.title, walk.started_at)},
    )


@router.post("/my-walks/{walk_id}/share", response_model=schemas.SavedWalkDetail, tags=["나만의 산책길"])
def share_saved_walk(
    walk_id: int,
    body: schemas.ShareRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> schemas.SavedWalkDetail:
    walk = _get_saved_walk(db, walk_id, user)
    return _walk_detail(saved_walk_service.enable_share(db, walk, body, now_local()))


@router.delete("/my-walks/{walk_id}/share", response_model=schemas.SavedWalkDetail, tags=["나만의 산책길"])
def unshare_saved_walk(walk_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> schemas.SavedWalkDetail:
    return _walk_detail(saved_walk_service.disable_share(db, _get_saved_walk(db, walk_id, user)))


def _get_photo(db: Session, walk: SavedWalk, photo_id: int) -> SavedWalkPhoto:
    photo = db.get(SavedWalkPhoto, photo_id)
    if photo is None or photo.walk_id != walk.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "사진을 찾을 수 없습니다")
    return photo


@router.post("/my-walks/{walk_id}/photos", response_model=schemas.PhotoRead, status_code=status.HTTP_201_CREATED, tags=["나만의 산책길"])
def upload_photo(
    walk_id: int,
    data: bytes = Depends(_read_photo_body),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> SavedWalkPhoto:
    """사진 원본을 본문으로 받는다. 형식은 파일 내용으로 판단하고, 촬영 위치 같은 메타데이터를 지운 뒤 저장한다."""
    walk = _get_saved_walk(db, walk_id, user)
    if len(walk.photos) >= MAX_PHOTOS_PER_WALK:
        raise HTTPException(status.HTTP_409_CONFLICT, f"사진은 {MAX_PHOTOS_PER_WALK}장까지 올릴 수 있어요.")
    try:
        content_type, cleaned = clean_image(data)
    except PhotoError as error:
        raise HTTPException(422, str(error)) from error
    photo = SavedWalkPhoto(walk=walk, content_type=content_type, data=cleaned, size_bytes=len(cleaned))
    db.add(photo)
    db.commit()
    return photo


@router.get("/my-walks/{walk_id}/photos/{photo_id}", tags=["나만의 산책길"])
def get_photo(walk_id: int, photo_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    photo = _get_photo(db, _get_saved_walk(db, walk_id, user), photo_id)
    return Response(
        photo.data,
        media_type=photo.content_type,
        headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff", "Content-Disposition": "inline"},
    )


@router.delete("/my-walks/{walk_id}/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["나만의 산책길"])
def delete_photo(walk_id: int, photo_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> None:
    photo = _get_photo(db, _get_saved_walk(db, walk_id, user), photo_id)
    community_service.clear_cover(db, photo)
    db.delete(photo)
    db.commit()


def _get_shared(db: Session, token: str) -> SavedWalk:
    walk = saved_walk_service.find_shared(db, token)
    if walk is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "공유가 해제되었거나 없는 링크예요")
    if saved_walk_service.is_expired(walk, now_local()):
        raise HTTPException(status.HTTP_410_GONE, "공유 기간이 끝난 링크예요")
    return walk


@router.get("/shared/{token}", response_model=schemas.SharedWalkRead, tags=["공유"])
def get_shared_walk(token: str, db: Session = Depends(get_db)) -> dict:
    return saved_walk_service.shared_payload(_get_shared(db, token))


@router.get("/shared/{token}/gpx", tags=["공유"])
def export_shared_walk(token: str, db: Session = Depends(get_db)) -> Response:
    """공유용 GPX. 언제 걸었는지 드러나지 않도록 시각과 고도를 뺀다."""
    walk = _get_shared(db, token)
    return Response(
        build_gpx(walk.title, saved_walk_service.to_gpx_points(walk), include_details=False),
        media_type=GPX_MEDIA_TYPE,
        headers={"Content-Disposition": content_disposition(walk.title, None)},
    )


@router.get("/public-walks", response_model=list[schemas.PublicWalkSummary], tags=["공유"])
def list_public_walks(db: Session = Depends(get_db)) -> list[dict]:
    return [saved_walk_service.public_summary(walk) for walk in saved_walk_service.list_public_walks(db)]


# 산책길 커뮤니티
PAGE_SIZE = Query(default=12, ge=1, le=50)
PHOTO_HEADERS = {"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff", "Content-Disposition": "inline"}


def _get_trail(db: Session, trail_id: int, viewer_user: User | None) -> CommunityTrail:
    """공개 산책길이거나 내 산책길일 때만 돌려준다. 다른 보호자의 비공개 산책길은 없는 것과 같다."""
    trail = db.get(CommunityTrail, trail_id)
    if trail is None or not community_service.can_view(trail, viewer_user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "산책길을 찾을 수 없습니다")
    return trail


def _own_trail(db: Session, trail_id: int, user: User) -> CommunityTrail:
    trail = _get_trail(db, trail_id, user)
    if trail.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "내가 공유한 산책길만 고칠 수 있어요.")
    return trail


def _own_review(db: Session, review_id: int, user: User) -> TrailReview:
    review = db.get(TrailReview, review_id)
    if review is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "후기를 찾을 수 없습니다")
    if review.user_id != user.id:
        # 볼 수 없는 산책길의 후기라면 있다는 것도 알리지 않는다.
        _get_trail(db, review.community_trail_id, user)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "내가 쓴 후기만 고칠 수 있어요.")
    return review


@router.post("/community/trails/preview", response_model=schemas.TrailPreview, tags=["산책길 커뮤니티"])
def preview_trail(body: schemas.TrailPreviewRequest, db: Session = Depends(get_db), user: User = Depends(signed_in_user)) -> dict:
    """출발점과 도착점 주변을 가린 뒤 실제로 공개될 경로를 미리 보여 준다. 저장하지 않는다."""
    walk = _get_saved_walk(db, body.saved_walk_id, user)
    try:
        return community_service.preview_public(walk, body.hide_radius_m)
    except community_service.CommunityError as error:
        raise HTTPException(error.status_code, error.message) from error


@router.post("/community/trails/nearby", response_model=list[schemas.TrailNearby], tags=["산책길 커뮤니티"])
def nearby_trails(body: schemas.TrailNearbyRequest, db: Session = Depends(get_db), viewer_user: User | None = Depends(signed_in_viewer)) -> list[dict]:
    """가까운 공개 산책길. 위치는 저장하지 않으며, 로그에 남지 않도록 본문으로 받는다."""
    return community_service.nearby_trails(db, viewer_user, body.latitude, body.longitude, body.radius_km, body.limit)


@router.get("/community/trails/recommended", response_model=list[schemas.TrailRecommended], tags=["산책길 커뮤니티"])
def recommended_trails(
    pet_id: int,
    limit: int = Query(default=6, ge=1, le=20),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    viewer_user: User | None = Depends(signed_in_viewer),
) -> list[dict]:
    """반려동물의 권장 거리, 보호자가 표시한 추천 대상, 학습된 취향, 평점으로 고른 공개 산책길."""
    return community_service.recommend_trails(db, viewer_user, _get_pet(db, pet_id, user), limit)


@router.get("/community/regions", response_model=list[schemas.TrailRegionRead], tags=["산책길 커뮤니티"])
def trail_regions(db: Session = Depends(get_db)) -> list[dict]:
    return community_service.list_regions(db)


@router.get("/community/trails", response_model=schemas.TrailPage, tags=["산책길 커뮤니티"])
def list_trails(
    filters: schemas.TrailFilters = Depends(),
    page: int = Query(default=1, ge=1),
    size: int = PAGE_SIZE,
    db: Session = Depends(get_db),
    viewer_user: User | None = Depends(signed_in_viewer),
) -> dict:
    """공개 산책길 목록. 로그인 없이 볼 수 있다."""
    return community_service.list_trails(db, viewer_user, filters, page, size)


@router.post("/community/trails", response_model=schemas.TrailDetail, status_code=status.HTTP_201_CREATED, tags=["산책길 커뮤니티"])
def create_trail(body: schemas.TrailCreate, db: Session = Depends(get_db), user: User = Depends(signed_in_user)) -> dict:
    """저장한 산책길을 커뮤니티에 공유한다. 좌표를 복사하지 않고 원본을 참조한다."""
    walk = _get_saved_walk(db, body.saved_walk_id, user)
    try:
        trail = community_service.create_trail(db, user, walk, body, now_local())
    except community_service.CommunityError as error:
        raise HTTPException(error.status_code, error.message) from error
    return community_service.trail_detail(db, trail, user)


@router.get("/community/trails/{trail_id}", response_model=schemas.TrailDetail, tags=["산책길 커뮤니티"])
def get_trail(trail_id: int, db: Session = Depends(get_db), viewer_user: User | None = Depends(signed_in_viewer)) -> dict:
    return community_service.trail_detail(db, _get_trail(db, trail_id, viewer_user), viewer_user)


@router.patch("/community/trails/{trail_id}", response_model=schemas.TrailDetail, tags=["산책길 커뮤니티"])
def update_trail(trail_id: int, body: schemas.TrailUpdate, db: Session = Depends(get_db), user: User = Depends(signed_in_user)) -> dict:
    trail = _own_trail(db, trail_id, user)
    changes = body.model_dump(exclude_unset=True)
    # 대표 이미지만 비울 수 있다. 나머지 항목을 null로 보내면 저장하지 않고 알려 준다.
    cleared = [key for key, value in changes.items() if value is None and key != "cover_photo_id"]
    if cleared:
        raise HTTPException(422, f"비울 수 없는 항목이에요: {', '.join(cleared)}")
    try:
        return community_service.trail_detail(db, community_service.update_trail(db, trail, changes), user)
    except community_service.CommunityError as error:
        raise HTTPException(error.status_code, error.message) from error


@router.delete("/community/trails/{trail_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["산책길 커뮤니티"])
def delete_trail(trail_id: int, db: Session = Depends(get_db), user: User = Depends(signed_in_user)) -> None:
    """공유를 해제한다. 원본 산책길은 남고, 좋아요와 저장, 후기는 함께 지운다."""
    community_service.delete_trail(db, _own_trail(db, trail_id, user))


@router.post("/community/trails/{trail_id}/view", status_code=status.HTTP_204_NO_CONTENT, tags=["산책길 커뮤니티"])
def view_trail(trail_id: int, db: Session = Depends(get_db), viewer_user: User | None = Depends(signed_in_viewer)) -> None:
    """조회수를 올린다. 화면이 세션마다 한 번만 부른다."""
    community_service.count_view(db, _get_trail(db, trail_id, viewer_user), viewer_user)


@router.get("/community/trails/{trail_id}/gpx", tags=["산책길 커뮤니티"])
def export_trail(trail_id: int, db: Session = Depends(get_db), viewer_user: User | None = Depends(signed_in_viewer)) -> Response:
    """공개용 GPX. 가린 경로만 담고 시각, 고도, 원본 이름, 메모, 작성자, 날짜를 넣지 않는다."""
    trail = _get_trail(db, trail_id, viewer_user)
    return Response(
        build_gpx(trail.title, community_service.trail_points(trail), include_details=False),
        media_type=GPX_MEDIA_TYPE,
        headers={"Content-Disposition": content_disposition(trail.title, None)},
    )


@router.get("/community/trails/{trail_id}/cover", tags=["산책길 커뮤니티"])
def trail_cover(trail_id: int, db: Session = Depends(get_db), viewer_user: User | None = Depends(signed_in_viewer)) -> Response:
    """주인이 대표로 고른 사진 한 장만 공개한다. 산책길의 다른 사진은 열지 않는다."""
    trail = _get_trail(db, trail_id, viewer_user)
    photo = db.get(SavedWalkPhoto, trail.cover_photo_id) if trail.cover_photo_id else None
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "대표 이미지가 없습니다")
    return Response(photo.data, media_type=photo.content_type, headers=PHOTO_HEADERS)


@router.post("/community/trails/{trail_id}/start", response_model=schemas.TrailCourseRead, tags=["산책길 커뮤니티"])
def start_trail(trail_id: int, db: Session = Depends(get_db), viewer_user: User | None = Depends(signed_in_viewer)) -> dict:
    """이 산책길로 길 안내를 받을 코스 번호를 돌려준다. 산책길마다 코스는 하나만 만든다."""
    trail = _get_trail(db, trail_id, viewer_user)
    try:
        return {"course_id": community_service.start_course(db, trail).id}
    except community_service.CommunityError as error:
        raise HTTPException(error.status_code, error.message) from error


@router.post("/community/trails/{trail_id}/like", response_model=schemas.LikeState, tags=["산책길 커뮤니티"])
def like_trail(trail_id: int, db: Session = Depends(get_db), user: User = Depends(signed_in_user)) -> dict:
    return {"liked": True, "like_count": community_service.set_reaction(db, TrailLike, user, _get_trail(db, trail_id, user), True)}


@router.delete("/community/trails/{trail_id}/like", response_model=schemas.LikeState, tags=["산책길 커뮤니티"])
def unlike_trail(trail_id: int, db: Session = Depends(get_db), user: User = Depends(signed_in_user)) -> dict:
    return {"liked": False, "like_count": community_service.set_reaction(db, TrailLike, user, _get_trail(db, trail_id, user), False)}


@router.post("/community/trails/{trail_id}/bookmark", response_model=schemas.BookmarkState, tags=["산책길 커뮤니티"])
def bookmark_trail(trail_id: int, db: Session = Depends(get_db), user: User = Depends(signed_in_user)) -> dict:
    return {"bookmarked": True, "bookmark_count": community_service.set_reaction(db, TrailBookmark, user, _get_trail(db, trail_id, user), True)}


@router.delete("/community/trails/{trail_id}/bookmark", response_model=schemas.BookmarkState, tags=["산책길 커뮤니티"])
def unbookmark_trail(trail_id: int, db: Session = Depends(get_db), user: User = Depends(signed_in_user)) -> dict:
    return {"bookmarked": False, "bookmark_count": community_service.set_reaction(db, TrailBookmark, user, _get_trail(db, trail_id, user), False)}


@router.get("/community/trails/{trail_id}/reviews", response_model=schemas.ReviewPage, tags=["산책길 커뮤니티"])
def list_reviews(
    trail_id: int,
    page: int = Query(default=1, ge=1),
    size: int = PAGE_SIZE,
    db: Session = Depends(get_db),
    viewer_user: User | None = Depends(signed_in_viewer),
) -> dict:
    return community_service.list_reviews(db, _get_trail(db, trail_id, viewer_user), viewer_user, page, size)


@router.post("/community/trails/{trail_id}/reviews", response_model=schemas.ReviewRead, status_code=status.HTTP_201_CREATED, tags=["산책길 커뮤니티"])
def create_review(trail_id: int, body: schemas.ReviewCreate, db: Session = Depends(get_db), user: User = Depends(signed_in_user)) -> dict:
    """산책길마다 한 번만 남긴다. 이 산책길을 GPS로 걸은 기록이 있으면 산책 인증이 붙는다."""
    trail = _get_trail(db, trail_id, user)
    try:
        review = community_service.create_review(db, user, trail, body.rating, body.content, now_local())
    except community_service.CommunityError as error:
        raise HTTPException(error.status_code, error.message) from error
    return community_service.review_items(db, [review], user)[0]


@router.patch("/community/reviews/{review_id}", response_model=schemas.ReviewRead, tags=["산책길 커뮤니티"])
def update_review(review_id: int, body: schemas.ReviewUpdate, db: Session = Depends(get_db), user: User = Depends(signed_in_user)) -> dict:
    review = _own_review(db, review_id, user)
    changes = body.model_dump(exclude_unset=True)
    cleared = [key for key, value in changes.items() if value is None]
    if cleared:
        raise HTTPException(422, f"비울 수 없는 항목이에요: {', '.join(cleared)}")
    return community_service.review_items(db, [community_service.update_review(db, review, changes, now_local())], user)[0]


@router.delete("/community/reviews/{review_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["산책길 커뮤니티"])
def delete_review(review_id: int, db: Session = Depends(get_db), user: User = Depends(signed_in_user)) -> None:
    db.delete(_own_review(db, review_id, user))
    db.commit()


@router.post("/community/reviews/{review_id}/photos", response_model=schemas.ReviewPhotoRead, status_code=status.HTTP_201_CREATED, tags=["산책길 커뮤니티"])
def upload_review_photo(
    review_id: int,
    data: bytes = Depends(_read_photo_body),
    db: Session = Depends(get_db),
    user: User = Depends(signed_in_user),
) -> TrailReviewPhoto:
    """산책길 사진과 같은 검사를 거친다. 형식은 파일 내용으로 판단하고 촬영 위치 같은 메타데이터를 지운다."""
    review = _own_review(db, review_id, user)
    if len(review.photos) >= community_service.MAX_REVIEW_PHOTOS:
        raise HTTPException(status.HTTP_409_CONFLICT, f"후기 사진은 {community_service.MAX_REVIEW_PHOTOS}장까지 올릴 수 있어요.")
    try:
        content_type, cleaned = clean_image(data)
    except PhotoError as error:
        raise HTTPException(422, str(error)) from error
    photo = TrailReviewPhoto(review=review, content_type=content_type, data=cleaned, size_bytes=len(cleaned))
    db.add(photo)
    db.commit()
    return photo


def _get_review_photo(db: Session, review_id: int, photo_id: int) -> TrailReviewPhoto:
    photo = db.get(TrailReviewPhoto, photo_id)
    if photo is None or photo.review_id != review_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "사진을 찾을 수 없습니다")
    return photo


@router.get("/community/reviews/{review_id}/photos/{photo_id}", tags=["산책길 커뮤니티"])
def get_review_photo(review_id: int, photo_id: int, db: Session = Depends(get_db), viewer_user: User | None = Depends(signed_in_viewer)) -> Response:
    photo = _get_review_photo(db, review_id, photo_id)
    if viewer_user is None or photo.review.user_id != viewer_user.id:
        _get_trail(db, photo.review.community_trail_id, viewer_user)
    return Response(photo.data, media_type=photo.content_type, headers=PHOTO_HEADERS)


@router.delete("/community/reviews/{review_id}/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["산책길 커뮤니티"])
def delete_review_photo(review_id: int, photo_id: int, db: Session = Depends(get_db), user: User = Depends(signed_in_user)) -> None:
    review = _own_review(db, review_id, user)
    db.delete(_get_review_photo(db, review.id, photo_id))
    db.commit()


@router.get("/community/my/trails", response_model=schemas.TrailPage, tags=["산책길 커뮤니티"])
def my_trails(page: int = Query(default=1, ge=1), size: int = PAGE_SIZE, db: Session = Depends(get_db), user: User = Depends(signed_in_user)) -> dict:
    return community_service.my_trails(db, user, page, size)


@router.get("/community/my/bookmarks", response_model=schemas.TrailReactionPage, tags=["산책길 커뮤니티"])
def my_bookmarks(page: int = Query(default=1, ge=1), size: int = PAGE_SIZE, db: Session = Depends(get_db), user: User = Depends(signed_in_user)) -> dict:
    return community_service.my_reactions(db, TrailBookmark, user, page, size)


@router.get("/community/my/likes", response_model=schemas.TrailReactionPage, tags=["산책길 커뮤니티"])
def my_likes(page: int = Query(default=1, ge=1), size: int = PAGE_SIZE, db: Session = Depends(get_db), user: User = Depends(signed_in_user)) -> dict:
    return community_service.my_reactions(db, TrailLike, user, page, size)


@router.get("/community/my/reviews", response_model=schemas.MyReviewPage, tags=["산책길 커뮤니티"])
def my_reviews(page: int = Query(default=1, ge=1), size: int = PAGE_SIZE, db: Session = Depends(get_db), user: User = Depends(signed_in_user)) -> dict:
    return community_service.my_reviews(db, user, page, size)

