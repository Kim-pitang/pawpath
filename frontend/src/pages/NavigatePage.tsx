import {
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  ChevronLeft,
  CloudRain,
  ExternalLink,
  Flag,
  Home as HomeIcon,
  LocateFixed,
  MapPin,
  PartyPopper,
  Route as RouteIcon,
  Satellite,
  Undo2,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import NavigationMap from '../components/NavigationMap';
import { SafetyBadge } from '../components/SafetyPanel';
import { Button, Chip, EmptyState, ErrorNotice, InfoNotice, LinkButton, Loading } from '../components/ui';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import { toLocalIso } from '../lib/format';
import { GPS_MESSAGES, useGeolocation, useSimulatedWalk, useWakeLock, type WalkPosition } from '../lib/location';
import {
  INITIAL_TRACKING,
  advanceTracking,
  buildRoute,
  distanceM,
  formatDistance,
  guidanceFor,
  locate,
  toleranceFor,
  type Guidance,
  type LatLng,
  type RouteModel,
  type Tracking,
} from '../lib/navigation';
import type { AlternativeResult, Approach, Course, NearbyPlace, WeatherScenario } from '../lib/types';

type WalkMode = 'gps' | 'simulation';
type Phase = 'locating' | 'gps_error' | 'far' | 'approach' | 'walking' | 'off_course' | 'finished' | 'returning' | 'returned';

const APPROACH_REFRESH_MS = 30000;
const REROUTE_INTERVAL_MS = 30000;
// 예보는 시간 단위이고 서버 캐시도 있으니 자주 물어봐도 달라지지 않는다.
const WEATHER_CHECK_INTERVAL_MS = 5 * 60 * 1000;
const OFF_APPROACH_M = 60;
const WEAK_GPS_M = 60;
const FAR_LIMIT_M = 3000;
// 지도가 가려지지 않도록 산책에 필요한 시설만 표시한다. 전체 목록은 지도 탭에서 볼 수 있다.
const WALK_PLACE_TYPES = ['park', 'dog_park', 'veterinary', 'drinking_water', 'toilets', 'pet_friendly'];

const GUIDANCE_ICONS = {
  left: ArrowLeft,
  right: ArrowRight,
  uturn: Undo2,
  straight: ArrowUp,
  arrive: Flag,
};

const CHECK_HEADLINES: Record<AlternativeResult['status'], string> = {
  continue: '지금은 계속 걸어도 괜찮아 보여요',
  shorten: '산책을 줄이는 편이 좋아요',
  return_now: '지금은 돌아가는 편이 좋아요',
  unknown: '날씨를 확인하지 못했어요',
};

function kakaoDirectionsUrl(course: Course): string {
  return `https://map.kakao.com/link/to/${encodeURIComponent(`${course.name} 출발점`)},${course.start_lat},${course.start_lng}`;
}

function clock(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  return `${minutes}:${String(totalSeconds % 60).padStart(2, '0')}`;
}

/** 코스에 들어오기 전, 출발점까지의 경로를 가져오고 벗어나면 다시 찾는다. */
function useApproach(course: Course | null, position: WalkPosition | null, enabled: boolean) {
  const [approach, setApproach] = useState<Approach | null>(null);
  const [progress, setProgress] = useState(0);
  const lastRequest = useRef(0);
  const inFlight = useRef(false);
  const model = useMemo<RouteModel | null>(
    () => (approach && approach.route.length >= 2 ? buildRoute(approach.route) : null),
    [approach],
  );

  useEffect(() => {
    if (!model || !position) return;
    setProgress((previous) => locate(model, position.point, previous, OFF_APPROACH_M).progress);
  }, [model, position]);

  useEffect(() => {
    if (!enabled || !course || !position || inFlight.current) return;
    const start: LatLng = [course.start_lat, course.start_lng];
    const sinceLast = Date.now() - lastRequest.current;
    let needed = approach === null;
    if (approach && sinceLast >= APPROACH_REFRESH_MS) {
      needed =
        approach.mode === 'too_far'
          ? distanceM(position.point, start) <= FAR_LIMIT_M
          : model !== null && locate(model, position.point, progress, OFF_APPROACH_M).offset > OFF_APPROACH_M;
    }
    if (!needed) return;

    inFlight.current = true;
    lastRequest.current = Date.now();
    api
      .approach(course.id, position.point[0], position.point[1])
      .then((result) => {
        setApproach(result);
        setProgress(0);
      })
      .catch(() => {
        // 서버에 닿지 못해도 방향은 알 수 있도록 직선으로 보여 준다.
        const distance = distanceM(position.point, start);
        setApproach({
          mode: distance > FAR_LIMIT_M ? 'too_far' : 'straight',
          distance_m: distance,
          duration_min: Math.max(1, Math.round(distance / 60)),
          route: distance > FAR_LIMIT_M ? [] : [position.point, start],
          notice: '길찾기를 불러오지 못해 직선으로 표시했어요. 실제 길을 확인하며 이동해 주세요.',
        });
        setProgress(0);
      })
      .finally(() => {
        inFlight.current = false;
      });
  }, [enabled, course, position, approach, model, progress]);

  return { approach, model, progress };
}

export default function NavigatePage() {
  const [params] = useSearchParams();
  const courseId = Number(params.get('course')) || null;
  const recommendationId = Number(params.get('recommendation')) || null;

  if (!courseId) {
    return (
      <main className="mx-auto max-w-md p-4">
        <EmptyState title="안내할 코스를 먼저 골라 주세요">
          <LinkButton to="/recommend">오늘의 추천 보기</LinkButton>
        </EmptyState>
      </main>
    );
  }
  // 대체 코스로 바꾸면 위치 추적과 진행도를 처음부터 다시 시작한다.
  return <NavigationView key={courseId} courseId={courseId} recommendationId={recommendationId} />;
}

function NavigationView({ courseId, recommendationId }: { courseId: number; recommendationId: number | null }) {
  const navigate = useNavigate();
  const { selectedPet, scenario } = useApp();

  const [course, setCourse] = useState<Course | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<WalkMode>('gps');
  const [tracking, setTracking] = useState<Tracking>(INITIAL_TRACKING);
  const [follow, setFollow] = useState(true);
  const [now, setNow] = useState(() => Date.now());
  const [saving, setSaving] = useState(false);

  const [check, setCheck] = useState<AlternativeResult | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkOpen, setCheckOpen] = useState(false);
  const [demoRain, setDemoRain] = useState(false);

  const [returnModel, setReturnModel] = useState<RouteModel | null>(null);
  const [returnNotice, setReturnNotice] = useState<string | null>(null);
  const [returnTracking, setReturnTracking] = useState<Tracking>(INITIAL_TRACKING);

  const [rejoinRoute, setRejoinRoute] = useState<LatLng[] | null>(null);
  const lastReroute = useRef(0);

  const [placesOn, setPlacesOn] = useState(false);
  const [places, setPlaces] = useState<NearbyPlace[]>([]);

  useEffect(() => {
    api.getCourse(courseId).then(setCourse).catch((loadError: Error) => setError(loadError.message));
  }, [courseId]);

  const route = useMemo(() => (course ? buildRoute(course.route) : null), [course]);
  const gps = useGeolocation(mode === 'gps');
  const simulated = useSimulatedWalk(returnModel ?? route, mode === 'simulation');
  const position = mode === 'simulation' ? simulated : gps.position;

  useEffect(() => {
    if (!position) return;
    if (returnModel) {
      setReturnTracking((previous) => advanceTracking(returnModel, previous, position.point, position.accuracy, Date.now(), true));
    } else if (route) {
      setTracking((previous) => advanceTracking(route, previous, position.point, position.accuracy, Date.now()));
    }
  }, [route, returnModel, position]);

  const started = tracking.startedAt !== null;
  const { approach, model: approachModel, progress: approachProgress } = useApproach(course, position, mode === 'gps' && !started);

  useEffect(() => {
    if (!started || tracking.finished || returnTracking.finished) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [started, tracking.finished, returnTracking.finished]);

  useWakeLock(started && !tracking.finished && !returnTracking.finished);

  // 비동기 요청과 주기 확인에서도 항상 최신 위치와 진행도를 쓴다.
  const latest = useRef({ position, progress: tracking.progress, petId: selectedPet?.id });
  latest.current = { position, progress: tracking.progress, petId: selectedPet?.id };
  const activeScenario: WeatherScenario = demoRain ? 'rain_now' : scenario;

  const runCheck = useCallback(
    async (open: boolean) => {
      const { position: here, progress, petId } = latest.current;
      if (!petId) {
        setError('날씨를 다시 확인하려면 먼저 반려동물을 등록해 주세요.');
        return;
      }
      setChecking(true);
      try {
        const result = await api.alternativeRoute({
          pet_id: petId,
          course_id: courseId,
          latitude: here ? here.point[0] : null,
          longitude: here ? here.point[1] : null,
          progress_m: progress,
          weather_scenario: activeScenario,
        });
        setCheck(result);
        if (open || result.status === 'return_now' || result.status === 'shorten') setCheckOpen(true);
      } catch (checkError) {
        setError((checkError as Error).message);
      } finally {
        setChecking(false);
      }
    },
    [courseId, activeScenario],
  );

  useEffect(() => {
    if (!started || tracking.finished || returnModel) return;
    void runCheck(false);
    const timer = window.setInterval(() => void runCheck(false), WEATHER_CHECK_INTERVAL_MS);
    return () => window.clearInterval(timer);
    // 산책을 시작할 때와 날씨 조건이 바뀔 때 다시 확인한다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [started, tracking.finished, returnModel, activeScenario]);

  const tolerance = toleranceFor(position?.accuracy ?? null);
  const offCourse = started && !returnModel && tracking.offset !== null && tracking.offset > tolerance;

  // 코스를 벗어나면 돌아갈 실제 길을 다시 찾는다. 못 찾으면 직선 점선이 남는다.
  useEffect(() => {
    if (!offCourse) {
      setRejoinRoute(null);
      return;
    }
    if (!position || !tracking.nearest || Date.now() - lastReroute.current < REROUTE_INTERVAL_MS) return;
    lastReroute.current = Date.now();
    api
      .walkingRoute(position.point, tracking.nearest)
      .then((result) => setRejoinRoute(result.mode !== 'too_far' && result.route.length >= 2 ? result.route : null))
      .catch(() => setRejoinRoute(null));
  }, [offCourse, position, tracking.nearest]);

  const togglePlaces = () => {
    if (placesOn) {
      setPlacesOn(false);
      setPlaces([]);
      return;
    }
    setPlacesOn(true);
    api
      .nearbyPlaces(courseId, 300, WALK_PLACE_TYPES)
      .then((result) => setPlaces(result.places))
      .catch(() => {
        setPlacesOn(false);
        setError('주변 시설을 불러오지 못했어요.');
      });
  };

  const switchMode = (next: WalkMode) => {
    setTracking(INITIAL_TRACKING);
    setReturnModel(null);
    setReturnTracking(INITIAL_TRACKING);
    setCheck(null);
    setCheckOpen(false);
    setDemoRain(false);
    setFollow(true);
    setMode(next);
  };

  const startReturn = () => {
    if (!check?.return_route || check.return_route.route.length < 2) return;
    setReturnModel(buildRoute(check.return_route.route));
    setReturnNotice(check.return_route.notice);
    setReturnTracking(INITIAL_TRACKING);
    setCheckOpen(false);
    setFollow(true);
  };

  const finishWalk = async () => {
    if (!course || tracking.startedAt === null) return;
    if (!selectedPet) {
      setError('기록을 남기려면 먼저 반려동물을 등록해 주세요.');
      return;
    }
    setSaving(true);
    setError(null);
    const isSimulation = mode === 'simulation';
    try {
      const walk = await api.createWalk({
        pet_id: selectedPet.id,
        course_id: course.id,
        recommendation_id: recommendationId,
        // 시연용 걷기는 빠르게 진행되므로 코스 예상 시간으로 기록하고, 활동 통계에서는 뺀다.
        duration_min: isSimulation ? course.duration_min : Math.max(1, Math.round((Date.now() - tracking.startedAt) / 60000)),
        started_at: isSimulation ? undefined : toLocalIso(new Date(tracking.startedAt)),
        tracking_source: isSimulation ? 'simulation' : 'gps',
        distance_km: Math.round(tracking.progress + returnTracking.progress) / 1000,
      });
      navigate('/walk', { state: { walk } });
    } catch (saveError) {
      setError((saveError as Error).message);
      setSaving(false);
    }
  };

  const leave = () => {
    const walking = started && !tracking.finished && !returnTracking.finished;
    if (walking && !window.confirm('산책을 그만둘까요? 지금까지의 기록은 남지 않아요.')) return;
    navigate(-1);
  };

  if (!course || !route) {
    return (
      <main className="mx-auto max-w-md p-4">
        {error ? <ErrorNotice message={error} /> : <Loading label="코스를 불러오는 중이에요" />}
      </main>
    );
  }

  const gpsMessage = GPS_MESSAGES[gps.status];
  const phase: Phase = returnModel
    ? returnTracking.finished
      ? 'returned'
      : 'returning'
    : tracking.finished
      ? 'finished'
      : started
        ? offCourse
          ? 'off_course'
          : 'walking'
        : !position
          ? mode === 'gps' && gpsMessage
            ? 'gps_error'
            : 'locating'
          : approach?.mode === 'too_far'
            ? 'far'
            : 'approach';

  const remaining = route.total - tracking.progress;
  const metersPerMinute = route.total / course.duration_min;
  const percent = Math.min(100, Math.round((tracking.progress / route.total) * 100));
  const elapsed = tracking.startedAt === null ? 0 : Math.max(0, Math.floor((now - tracking.startedAt) / 1000));
  const showApproach = phase === 'approach' && approachModel ? approachModel.points : null;
  const dashedRoute = returnModel?.points ?? showApproach ?? rejoinRoute;
  // 코스에 들어오기 전에는 어디로 가야 할지 보이게 전체를 보여 주고, 걷기 시작하면 내 위치를 따라간다.
  const overview = phase === 'far' ? route.points : showApproach;
  const followOnMap = follow && started;
  const onWalk = phase === 'walking' || phase === 'off_course';
  const riskBanner = check && check.status !== 'continue' && check.status !== 'unknown' && !checkOpen && onWalk;

  return (
    <div className="flex h-dvh flex-col bg-cream">
      <header className="z-10 flex items-center gap-2 border-b border-line bg-cream px-2 py-1.5">
        <button type="button" onClick={leave} aria-label="나가기" className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-ink-soft">
          <ChevronLeft size={24} aria-hidden />
        </button>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-base font-bold" data-testid="navigate-course-name">{course.name}</h1>
          <p className="text-xs text-ink-soft">
            {course.distance_km.toFixed(1)}km · 약 {course.duration_min}분
          </p>
        </div>
        {mode === 'simulation' ? (
          <Chip tone="carrot">시연용 위치</Chip>
        ) : position?.accuracy != null && position.accuracy > WEAK_GPS_M ? (
          <Chip tone="carrot">
            <Satellite size={13} aria-hidden />
            GPS 약함
          </Chip>
        ) : position ? (
          <Chip tone="leaf">
            <Satellite size={13} aria-hidden />
            GPS ±{Math.round(position.accuracy ?? 0)}m
          </Chip>
        ) : null}
      </header>

      <div className="relative min-h-0 flex-1">
        <NavigationMap
          key={course.id}
          route={route}
          progress={tracking.progress}
          position={position?.point ?? null}
          accuracy={position?.accuracy ?? null}
          approach={dashedRoute}
          rejoinPoint={offCourse && !rejoinRoute ? tracking.nearest : null}
          facilities={course.facilities}
          overview={overview}
          places={places}
          follow={followOnMap}
          onUserPan={() => setFollow(false)}
        />
        <button
          type="button"
          aria-pressed={placesOn}
          onClick={togglePlaces}
          className={`absolute top-3 left-3 z-10 flex min-h-10 items-center gap-1.5 rounded-full px-3.5 text-sm font-bold shadow-md ${
            placesOn ? 'bg-mango-500 text-ink' : 'bg-white text-ink'
          }`}
        >
          <MapPin size={16} aria-hidden />
          주변 시설{placesOn && places.length > 0 ? ` ${places.length}` : ''}
        </button>
        {started && !follow && (
          <button
            type="button"
            onClick={() => setFollow(true)}
            className="absolute right-3 bottom-3 z-10 flex min-h-11 items-center gap-1.5 rounded-full bg-white px-4 text-sm font-bold text-ink shadow-md"
          >
            <LocateFixed size={17} className="text-sky-500" aria-hidden />내 위치
          </button>
        )}
      </div>

      <section
        aria-live="polite"
        className="z-10 flex max-h-[62dvh] flex-col gap-3 overflow-y-auto rounded-t-xl border-t border-line bg-white p-4 pb-[max(1rem,env(safe-area-inset-bottom))] shadow-[0_-4px_16px_rgb(120_90_40/0.12)]"
      >
        {error && <ErrorNotice message={error} />}

        {checkOpen && check ? (
          <CheckPanel
            check={check}
            onReturn={startReturn}
            onClose={() => setCheckOpen(false)}
            onChooseCourse={(id) => navigate(`/navigate?course=${id}`, { replace: true })}
          />
        ) : (
          <>
            {riskBanner && (
              <button
                type="button"
                onClick={() => setCheckOpen(true)}
                data-testid="risk-banner"
                className="flex items-start gap-2 rounded-lg bg-[#fffbeb] p-3 text-left text-sm font-semibold text-[#92400e]"
              >
                <CloudRain size={18} className="mt-0.5 shrink-0" aria-hidden />
                <span>{CHECK_HEADLINES[check.status]}. 눌러서 복귀 경로와 대체 코스를 확인하세요.</span>
              </button>
            )}

            {phase === 'locating' && (
              <Instruction icon={LocateFixed} headline="현재 위치를 찾고 있어요" detail="위치 권한을 물어보면 허용해 주세요." />
            )}
            {phase === 'gps_error' && gpsMessage && <ErrorNotice message={gpsMessage} />}
            {phase === 'far' && approach && (
              <Instruction
                icon={Flag}
                headline={`출발점까지 직선으로 ${formatDistance(approach.distance_m)} 떨어져 있어요`}
                detail="걸어가기엔 멀어요. 출발점 근처로 이동하면 안내가 시작돼요."
              />
            )}
            {phase === 'approach' && <ApproachPanel approach={approach} model={approachModel} progress={approachProgress} />}
            {onWalk && (
              <>
                {phase === 'off_course' && tracking.offset !== null ? (
                  <Instruction
                    icon={Undo2}
                    tone="warning"
                    headline={`코스에서 ${formatDistance(tracking.offset)} 벗어났어요`}
                    detail={rejoinRoute ? '돌아갈 길을 다시 찾았어요. 점선을 따라가면 안내가 이어져요.' : '점선 방향으로 돌아가면 안내가 이어져요.'}
                  />
                ) : (
                  <GuidanceView guidance={guidanceFor(route, tracking.progress, '곧 코스 끝이에요')} />
                )}
                {check?.assessment && (
                  <div className="flex flex-wrap items-center gap-2" data-testid="walk-environment">
                    <SafetyBadge assessment={check.assessment} />
                    <span className="text-xs text-ink-muted">
                      {check.assessment.items.find((item) => item.key === 'temperature')?.value}
                      {' · '}
                      {check.assessment.items.find((item) => item.key === 'rain')?.value}
                    </span>
                  </div>
                )}
                <WalkStats percent={percent} remaining={remaining} minutes={Math.ceil(remaining / metersPerMinute)} elapsed={elapsed} />
              </>
            )}
            {phase === 'finished' && (
              <>
                <Instruction icon={PartyPopper} headline="코스를 완주했어요!" detail={`${selectedPet?.name ?? '우리 아이'}의 반응을 피드백으로 남겨 주세요. 다음 추천에 반영돼요.`} />
                <WalkStats percent={100} remaining={0} minutes={0} elapsed={elapsed} />
              </>
            )}
            {phase === 'returning' && returnModel && (
              <>
                <GuidanceView guidance={guidanceFor(returnModel, returnTracking.progress, '곧 출발점이에요')} />
                <p className="text-sm font-semibold text-ink-soft" data-testid="return-summary">
                  복귀 안내 중 · 출발점까지 약 {formatDistance(Math.max(0, returnModel.total - returnTracking.progress))}
                </p>
                {returnNotice && <InfoNotice>{returnNotice}</InfoNotice>}
              </>
            )}
            {phase === 'returned' && (
              <Instruction icon={HomeIcon} headline="출발점에 도착했어요" detail={`${selectedPet?.name ?? '우리 아이'}의 반응을 피드백으로 남겨 주세요.`} />
            )}

            {mode === 'simulation' && phase !== 'finished' && phase !== 'returned' && (
              <p className="text-xs text-ink-muted">실제 GPS가 아니라 코스를 따라 움직이는 시연용 위치예요.</p>
            )}

            <div className="flex flex-col gap-2">
              {phase === 'far' && (
                <a
                  href={kakaoDirectionsUrl(course)}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex min-h-12 items-center justify-center gap-2 rounded-lg bg-mango-500 px-5 text-sm font-bold text-ink"
                >
                  <ExternalLink size={16} aria-hidden />
                  카카오맵에서 출발점 길찾기
                </a>
              )}
              {onWalk && (
                <div className="grid grid-cols-2 gap-2">
                  <Button variant="ghost" className="!px-2" onClick={() => void runCheck(true)} disabled={checking}>
                    <RouteIcon size={16} aria-hidden />
                    {checking ? '확인 중이에요' : '대체 경로'}
                  </Button>
                  <Button onClick={finishWalk} disabled={saving} variant="ghost" className="!px-2">
                    {saving ? '저장 중이에요' : '산책 끝내기'}
                  </Button>
                </div>
              )}
              {onWalk && mode === 'simulation' && !demoRain && (
                <Button variant="ghost" onClick={() => setDemoRain(true)}>
                  <CloudRain size={16} aria-hidden />
                  시연: 지금부터 비 내리기
                </Button>
              )}
              {(phase === 'finished' || phase === 'returned' || phase === 'returning') && (
                <Button onClick={finishWalk} disabled={saving} variant={phase === 'returning' ? 'ghost' : 'accent'}>
                  {saving ? '저장 중이에요' : phase === 'returning' ? '여기서 산책 끝내기' : '피드백 남기기'}
                </Button>
              )}
              {!started && (
                <div className="grid grid-cols-2 gap-2">
                  <Button variant="ghost" className="!px-2" onClick={() => switchMode('simulation')}>
                    시연용 위치로 걷기
                  </Button>
                  <Link
                    to={`/walk?course=${course.id}${recommendationId ? `&recommendation=${recommendationId}` : ''}`}
                    className="inline-flex min-h-12 items-center justify-center rounded-lg border border-line bg-white px-2 text-sm font-bold text-ink"
                  >
                    GPS 없이 기록하기
                  </Link>
                </div>
              )}
              {mode === 'simulation' && phase !== 'finished' && phase !== 'returned' && (
                <button type="button" onClick={() => switchMode('gps')} className="min-h-10 text-sm font-semibold text-ink-soft">
                  실제 GPS로 돌아가기
                </button>
              )}
            </div>
          </>
        )}
      </section>
    </div>
  );
}

function CheckPanel({
  check,
  onReturn,
  onClose,
  onChooseCourse,
}: {
  check: AlternativeResult;
  onReturn: () => void;
  onClose: () => void;
  onChooseCourse: (courseId: number) => void;
}) {
  const route = check.return_route;
  const canReturn = route !== null && route.route.length >= 2;
  return (
    <div className="flex flex-col gap-3" data-testid="alternative-panel">
      <Instruction
        icon={check.status === 'continue' ? ArrowUp : CloudRain}
        tone={check.status === 'continue' ? 'normal' : 'warning'}
        headline={CHECK_HEADLINES[check.status]}
      />
      <ul className="flex flex-col gap-1 text-sm text-ink-soft">
        {check.reasons.map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
      </ul>
      {check.weather.notice && <InfoNotice>{check.weather.notice}</InfoNotice>}
      {check.location_notice && <ErrorNotice message={check.location_notice} />}
      {check.action === 'finish_course' && (
        <p className="rounded-lg bg-cream-deep p-3 text-sm text-ink">남은 코스를 마저 걷는 편이 출발점으로 되돌아가는 것보다 짧아요.</p>
      )}
      {check.action === 'no_walking_route' && <ErrorNotice message="출발점이 멀어 도보 경로를 안내할 수 없어요. 지도 앱을 이용해 주세요." />}
      {route?.notice && <InfoNotice>{route.notice}</InfoNotice>}

      {canReturn && check.status !== 'continue' && (
        <Button onClick={onReturn} variant="accent">
          <HomeIcon size={16} aria-hidden />
          출발점으로 돌아가기 · 약 {formatDistance(route.distance_m)}
        </Button>
      )}

      {check.alternatives.length > 0 && (
        <div>
          <p className="mb-1.5 text-sm font-bold">지금 걷기 좋은 대체 코스</p>
          <ul className="flex flex-col gap-1.5" aria-label="대체 코스">
            {check.alternatives.map((option) => (
              <li key={option.course_id}>
                <button
                  type="button"
                  onClick={() => onChooseCourse(option.course_id)}
                  className="w-full rounded-lg border border-line p-3 text-left"
                >
                  <span className="block text-sm font-bold">{option.name}</span>
                  <span className="block text-xs text-ink-soft">{option.reason}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {check.status !== 'continue' && check.alternatives.length === 0 && (
        <p className="text-sm text-ink-soft">지금은 비나 위험 조건을 피할 수 있는 가까운 코스가 없어요.</p>
      )}

      <p className="text-xs text-ink-muted">{check.data_limit}</p>
      <Button variant="ghost" onClick={onClose}>
        {check.status === 'continue' ? '안내로 돌아가기' : '계속 걷기'}
      </Button>
    </div>
  );
}

function Instruction({
  icon: Icon,
  headline,
  detail,
  tone = 'normal',
}: {
  icon: typeof Flag;
  headline: string;
  detail?: string | null;
  tone?: 'normal' | 'warning';
}) {
  return (
    <div className="flex items-center gap-3" data-testid="nav-instruction">
      <span
        className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-lg ${tone === 'warning' ? 'bg-[#b42318] text-white' : 'bg-mango-500 text-ink'}`}
      >
        <Icon size={26} aria-hidden />
      </span>
      <div className="min-w-0">
        <p className="text-lg font-bold leading-snug text-ink">{headline}</p>
        {detail && <p className="mt-0.5 text-sm text-ink-soft">{detail}</p>}
      </div>
    </div>
  );
}

function GuidanceView({ guidance }: { guidance: Guidance }) {
  return <Instruction icon={GUIDANCE_ICONS[guidance.kind]} headline={guidance.headline} detail={guidance.detail} />;
}

function ApproachPanel({ approach, model, progress }: { approach: Approach | null; model: RouteModel | null; progress: number }) {
  if (!approach || !model) return <Instruction icon={LocateFixed} headline="출발점까지 길을 찾고 있어요" />;
  const remaining = Math.max(0, model.total - progress);
  return (
    <>
      <GuidanceView guidance={guidanceFor(model, progress, '곧 코스 출발점이에요')} />
      <p className="text-sm font-semibold text-ink-soft" data-testid="approach-summary">
        코스 출발점까지 약 {formatDistance(remaining)} · 약 {Math.max(1, Math.round(remaining / 60))}분
      </p>
      {approach.notice && <InfoNotice>{approach.notice}</InfoNotice>}
    </>
  );
}

function WalkStats({ percent, remaining, minutes, elapsed }: { percent: number; remaining: number; minutes: number; elapsed: number }) {
  return (
    <div>
      <div
        role="progressbar"
        aria-label="코스 진행률"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
        data-testid="walk-progress"
        className="h-2.5 overflow-hidden rounded-full bg-cream-deep"
      >
        <div className="h-full rounded-full bg-mango-500 transition-[width] duration-500" style={{ width: `${percent}%` }} />
      </div>
      <dl className="mt-2 grid grid-cols-3 text-center">
        <Stat label="진행률" value={`${percent}%`} />
        <Stat label="남은 거리" value={remaining <= 0 ? '0m' : formatDistance(remaining)} />
        <Stat label="걸은 시간" value={clock(elapsed)} sub={minutes > 0 ? `약 ${minutes}분 남음` : undefined} />
      </dl>
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <dt className="text-xs text-ink-muted">{label}</dt>
      <dd className="text-base font-bold tabular-nums text-ink">{value}</dd>
      {sub && <dd className="text-[11px] text-ink-muted">{sub}</dd>}
    </div>
  );
}
