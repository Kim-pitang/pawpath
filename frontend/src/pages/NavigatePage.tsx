import {
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  ChevronLeft,
  ExternalLink,
  Flag,
  LocateFixed,
  PartyPopper,
  Satellite,
  Undo2,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import NavigationMap from '../components/NavigationMap';
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
import type { Approach, Course } from '../lib/types';

type WalkMode = 'gps' | 'simulation';
type Phase = 'locating' | 'gps_error' | 'far' | 'approach' | 'walking' | 'off_course' | 'finished';

const APPROACH_REFRESH_MS = 30000;
const OFF_APPROACH_M = 60;
const WEAK_GPS_M = 60;
const FAR_LIMIT_M = 3000;

const GUIDANCE_ICONS = {
  left: ArrowLeft,
  right: ArrowRight,
  uturn: Undo2,
  straight: ArrowUp,
  arrive: Flag,
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
  const navigate = useNavigate();
  const { selectedPet } = useApp();
  const courseId = Number(params.get('course')) || null;
  const recommendationId = Number(params.get('recommendation')) || null;

  const [course, setCourse] = useState<Course | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<WalkMode>('gps');
  const [tracking, setTracking] = useState<Tracking>(INITIAL_TRACKING);
  const [follow, setFollow] = useState(true);
  const [now, setNow] = useState(() => Date.now());
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!courseId) return;
    api.getCourse(courseId).then(setCourse).catch((loadError: Error) => setError(loadError.message));
  }, [courseId]);

  const route = useMemo(() => (course ? buildRoute(course.route) : null), [course]);
  const gps = useGeolocation(mode === 'gps');
  const simulated = useSimulatedWalk(route, mode === 'simulation');
  const position = mode === 'simulation' ? simulated : gps.position;

  useEffect(() => {
    if (!route || !position) return;
    setTracking((previous) => advanceTracking(route, previous, position.point, position.accuracy, Date.now()));
  }, [route, position]);

  const started = tracking.startedAt !== null;
  const { approach, model: approachModel, progress: approachProgress } = useApproach(
    course,
    position,
    mode === 'gps' && !started,
  );

  useEffect(() => {
    if (!started || tracking.finished) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [started, tracking.finished]);

  useWakeLock(started && !tracking.finished);

  const switchMode = (next: WalkMode) => {
    setTracking(INITIAL_TRACKING);
    setFollow(true);
    setMode(next);
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
        // 시연용 걷기는 빠르게 진행되므로 코스 예상 시간으로 기록한다.
        duration_min: isSimulation ? course.duration_min : Math.max(1, Math.round((Date.now() - tracking.startedAt) / 60000)),
        started_at: isSimulation ? undefined : toLocalIso(new Date(tracking.startedAt)),
      });
      navigate('/walk', { state: { walk } });
    } catch (saveError) {
      setError((saveError as Error).message);
      setSaving(false);
    }
  };

  const leave = () => {
    if (started && !tracking.finished && !window.confirm('산책을 그만둘까요? 지금까지의 기록은 남지 않아요.')) return;
    navigate(-1);
  };

  if (!courseId) {
    return (
      <main className="mx-auto max-w-md p-4">
        <EmptyState title="안내할 코스를 먼저 골라 주세요">
          <LinkButton to="/recommend">오늘의 추천 보기</LinkButton>
        </EmptyState>
      </main>
    );
  }
  if (!course || !route) {
    return (
      <main className="mx-auto max-w-md p-4">
        {error ? <ErrorNotice message={error} /> : <Loading label="코스를 불러오는 중이에요" />}
      </main>
    );
  }

  const tolerance = toleranceFor(position?.accuracy ?? null);
  const offCourse = started && tracking.offset !== null && tracking.offset > tolerance;
  const gpsMessage = GPS_MESSAGES[gps.status];
  const phase: Phase = tracking.finished
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
  // 코스에 들어오기 전에는 어디로 가야 할지 보이게 전체를 보여 주고, 걷기 시작하면 내 위치를 따라간다.
  const overview = phase === 'far' ? route.points : showApproach;
  const followOnMap = follow && started;

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
          approach={showApproach}
          rejoinPoint={offCourse ? tracking.nearest : null}
          facilities={course.facilities}
          overview={overview}
          follow={followOnMap}
          onUserPan={() => setFollow(false)}
        />
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
        className="z-10 flex max-h-[55dvh] flex-col gap-3 overflow-y-auto rounded-t-3xl border-t border-line bg-white p-4 pb-[max(1rem,env(safe-area-inset-bottom))] shadow-[0_-4px_16px_rgb(120_90_40/0.12)]"
      >
        {error && <ErrorNotice message={error} />}

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
        {phase === 'approach' && (
          <ApproachPanel approach={approach} model={approachModel} progress={approachProgress} />
        )}
        {(phase === 'walking' || phase === 'off_course') && (
          <>
            {phase === 'off_course' && tracking.offset !== null ? (
              <Instruction
                icon={Undo2}
                tone="warning"
                headline={`코스에서 ${formatDistance(tracking.offset)} 벗어났어요`}
                detail="점선을 따라 코스로 돌아가면 안내가 이어져요."
              />
            ) : (
              <GuidanceView guidance={guidanceFor(route, tracking.progress, '곧 코스 끝이에요')} />
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

        {mode === 'simulation' && phase !== 'finished' && (
          <p className="text-xs text-ink-muted">실제 GPS가 아니라 코스를 따라 움직이는 시연용 위치예요.</p>
        )}

        <div className="flex flex-col gap-2">
          {phase === 'far' && (
            <a
              href={kakaoDirectionsUrl(course)}
              target="_blank"
              rel="noreferrer"
              className="inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl bg-leaf-500 px-5 text-sm font-bold text-white"
            >
              <ExternalLink size={16} aria-hidden />
              카카오맵에서 출발점 길찾기
            </a>
          )}
          {(phase === 'walking' || phase === 'off_course') && (
            <Button onClick={finishWalk} disabled={saving} variant="ghost">
              {saving ? '저장 중이에요' : '산책 끝내기'}
            </Button>
          )}
          {phase === 'finished' && (
            <Button onClick={finishWalk} disabled={saving} variant="accent">
              {saving ? '저장 중이에요' : '피드백 남기기'}
            </Button>
          )}
          {!started && (
            <div className="grid grid-cols-2 gap-2">
              <Button variant="ghost" className="!px-2" onClick={() => switchMode('simulation')}>
                시연용 위치로 걷기
              </Button>
              <Link
                to={`/walk?course=${course.id}${recommendationId ? `&recommendation=${recommendationId}` : ''}`}
                className="inline-flex min-h-12 items-center justify-center rounded-2xl border border-line bg-white px-2 text-sm font-bold text-ink"
              >
                GPS 없이 기록하기
              </Link>
            </div>
          )}
          {mode === 'simulation' && phase !== 'finished' && (
            <button type="button" onClick={() => switchMode('gps')} className="min-h-10 text-sm font-semibold text-ink-soft">
              실제 GPS로 돌아가기
            </button>
          )}
        </div>
      </section>
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
        className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl text-white ${tone === 'warning' ? 'bg-carrot-500' : 'bg-leaf-500'}`}
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
        className="h-2.5 overflow-hidden rounded-full bg-leaf-100"
      >
        <div className="h-full rounded-full bg-leaf-500 transition-[width] duration-500" style={{ width: `${percent}%` }} />
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
