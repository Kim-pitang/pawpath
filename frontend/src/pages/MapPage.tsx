import { Footprints, Route } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import CourseMap, { FACILITY_MARKERS, RANK_COLORS } from '../components/CourseMap';
import NearbyPlaces from '../components/NearbyPlaces';
import { Chip, ErrorNotice, LinkButton, Loading, PageTitle } from '../components/ui';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import { CROWD_LABELS, DIFFICULTY_COURSE_LABELS, FACILITY_LABELS, TRAFFIC_LABELS } from '../lib/labels';
import { isGpxCourse, type Course } from '../lib/types';

const CROWD_ORDER: Record<string, number> = { low: 0, medium: 1, high: 2 };

// 조건으로 코스를 거른다. 지도도 거른 코스만 그린다.
const FILTERS: { key: string; label: string; test: (course: Course, rank?: number) => boolean }[] = [
  { key: 'all', label: '전체', test: () => true },
  { key: 'ranked', label: '오늘 추천', test: (_, rank) => rank !== undefined },
  { key: 'short', label: '30분 이하', test: (course) => course.duration_min <= 30 },
  { key: 'park', label: '공원 지나요', test: (course) => course.has_park },
  { key: 'shade', label: '그늘 많음', test: (course) => course.shade_level >= 0.6 },
];

const SORTS: { key: string; label: string; compare: (a: Course, b: Course) => number }[] = [
  { key: 'rank', label: '추천순', compare: () => 0 },
  { key: 'short', label: '짧은순', compare: (a, b) => a.duration_min - b.duration_min },
  { key: 'quiet', label: '한산한순', compare: (a, b) => CROWD_ORDER[a.crowd_level] - CROWD_ORDER[b.crowd_level] },
];

const COLUMNS = 'grid-cols-[1fr_2.75rem_2.5rem_2.75rem]';

function walkLink(course: Course, recommendationId?: number) {
  return `/navigate?course=${course.id}${recommendationId ? `&recommendation=${recommendationId}` : ''}`;
}

function shadeLabel(level: number) {
  return level >= 0.6 ? '그늘 많음' : level >= 0.3 ? '그늘 조금' : '그늘 적음';
}

export default function MapPage() {
  const { cachedRecommendation } = useApp();
  const [params, setParams] = useSearchParams();
  const [courses, setCourses] = useState<Course[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState('all');
  const [sort, setSort] = useState('rank');
  const selectedId = Number(params.get('course')) || null;

  useEffect(() => {
    api.listCourses().then(setCourses).catch((loadError: Error) => setError(loadError.message));
  }, []);

  const select = useCallback(
    (id: number | null) => setParams(id === null ? {} : { course: String(id) }, { replace: true }),
    [setParams],
  );

  const rankById = useMemo(() => {
    const ranks: Record<number, number> = {};
    for (const course of cachedRecommendation?.courses ?? []) ranks[course.course_id] = course.rank;
    return ranks;
  }, [cachedRecommendation]);

  const test = FILTERS.find((item) => item.key === filter)!.test;
  const compare = SORTS.find((item) => item.key === sort)!.compare;
  const shown = useMemo(
    () =>
      [...courses]
        .sort((a, b) => (rankById[a.id] ?? 99) - (rankById[b.id] ?? 99) || a.id - b.id)
        .filter((course) => test(course, rankById[course.id]))
        .sort(compare),
    [courses, rankById, test, compare],
  );
  const selected = shown.find((course) => course.id === selectedId);
  const typesShown = Array.from(new Set(selected?.facilities.map((facility) => facility.type) ?? []));

  if (error) return <ErrorNotice message={error} />;
  if (courses.length === 0) return <Loading label="코스를 불러오는 중이에요" />;

  return (
    <div>
      <PageTitle sub={`${courses[0].area}의 실제 경로예요. 조건을 고르면 지도도 함께 걸러져요.`}>산책 코스 지도</PageTitle>
      <div className="-mx-4 mb-3 flex gap-1.5 overflow-x-auto overscroll-x-contain px-4 [scrollbar-width:none] md:mx-0 md:px-0" role="group" aria-label="코스 조건">
        {FILTERS.map((item) => {
          const count = courses.filter((course) => item.test(course, rankById[course.id])).length;
          return (
            <button
              key={item.key}
              type="button"
              aria-pressed={filter === item.key}
              onClick={() => setFilter(item.key)}
              disabled={count === 0}
              className={`min-h-9 shrink-0 rounded-full border px-3 text-sm font-semibold whitespace-nowrap disabled:opacity-40 ${
                filter === item.key ? 'border-ink bg-ink text-white' : 'border-line bg-white text-ink-soft'
              }`}
            >
              {item.label} <span className="tabular-nums opacity-70">{count}</span>
            </button>
          );
        })}
      </div>

      <div className="grid gap-4 md:grid-cols-[1.3fr_1fr] md:items-start">
        <div className="flex flex-col gap-2 md:sticky md:top-20">
          <CourseMap courses={shown} selectedId={selected?.id ?? null} rankById={rankById} onSelect={select} />
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-soft" aria-label="지도 범례">
            {Object.keys(rankById).length > 0 && (
              <>
                {[1, 2, 3].map((rank) => (
                  <span key={rank} className="flex items-center gap-1">
                    <span className="h-1 w-4 rounded" style={{ background: RANK_COLORS[rank] }} aria-hidden />
                    추천 {rank}위
                  </span>
                ))}
                <span className="flex items-center gap-1">
                  <span className="h-1 w-4 rounded bg-[#a39d8d]" aria-hidden />
                  기타 코스
                </span>
              </>
            )}
            {typesShown.map((type) => (
              <span key={type} className="flex items-center gap-1">
                <span
                  className="flex h-4 w-4 items-center justify-center rounded-full text-[9px] font-bold text-white"
                  style={{ background: FACILITY_MARKERS[type]?.color }}
                  aria-hidden
                >
                  {FACILITY_MARKERS[type]?.glyph}
                </span>
                {FACILITY_LABELS[type] ?? type}
              </span>
            ))}
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm text-ink-soft">
              <strong className="font-semibold text-ink">{shown.length}곳</strong> / {courses.length}곳
            </p>
            <div className="flex rounded-lg bg-cream-deep p-0.5 text-xs" role="group" aria-label="정렬">
              {SORTS.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  aria-pressed={sort === item.key}
                  onClick={() => setSort(item.key)}
                  className={`min-h-8 rounded-md px-2.5 font-semibold ${sort === item.key ? 'bg-white text-ink shadow-[0_1px_2px_rgb(66_45_33/0.12)]' : 'text-ink-soft'}`}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>

          <div className="mt-2 overflow-hidden rounded-xl border border-line bg-white">
            <div className={`grid ${COLUMNS} gap-2 border-b border-line bg-cream px-3 py-2 text-xs font-semibold text-ink-soft`} aria-hidden>
              <span>코스</span>
              <span className="text-right">거리</span>
              <span className="text-right">시간</span>
              <span>그늘</span>
            </div>
            <ul aria-label="코스 목록">
              {shown.map((course) => (
                <CourseRow
                  key={course.id}
                  course={course}
                  rank={rankById[course.id]}
                  active={course.id === selected?.id}
                  recommendationId={cachedRecommendation?.id}
                  onToggle={() => select(course.id === selected?.id ? null : course.id)}
                />
              ))}
            </ul>
          </div>
          <p className="mt-2 text-xs text-ink-muted">줄을 누르면 지도에서 그 코스로 이동해요. 왼쪽으로 밀면 바로 산책을 시작해요.</p>
        </div>
      </div>
    </div>
  );
}

// 이만큼 밀면 손을 떼는 순간 산책을 시작한다.
const COMMIT_PX = 96;

function CourseRow({
  course,
  rank,
  active,
  recommendationId,
  onToggle,
}: {
  course: Course;
  rank?: number;
  active: boolean;
  recommendationId?: number;
  onToggle: () => void;
}) {
  const navigate = useNavigate();
  const [offset, setOffset] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const drag = useRef<{ x: number; y: number; id: number; horizontal: boolean | null } | null>(null);
  // 밀고 난 뒤 따라오는 click은 펼치기로 읽지 않는다.
  const swiped = useRef(false);

  const start = () => {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce) {
      navigate(walkLink(course, recommendationId));
      return;
    }
    setLeaving(true);
    window.setTimeout(() => navigate(walkLink(course, recommendationId)), 180);
  };

  const onPointerDown = (event: ReactPointerEvent<HTMLButtonElement>) => {
    if (event.pointerType === 'mouse' && event.button !== 0) return;
    drag.current = { x: event.clientX, y: event.clientY, id: event.pointerId, horizontal: null };
    swiped.current = false;
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const state = drag.current;
    if (!state || state.id !== event.pointerId) return;
    const dx = event.clientX - state.x;
    const dy = event.clientY - state.y;
    // 처음 움직인 방향으로 가로 밀기인지 세로 스크롤인지 정한다.
    if (state.horizontal === null) {
      if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return;
      state.horizontal = Math.abs(dx) > Math.abs(dy);
      if (!state.horizontal) return;
      event.currentTarget.setPointerCapture(event.pointerId);
      setDragging(true);
    }
    if (!state.horizontal) return;
    swiped.current = true;
    // 왼쪽으로만 민다. 문턱을 넘으면 저항을 줘서 더 끌려가지 않게 한다.
    const pull = Math.min(0, dx);
    setOffset(pull < -COMMIT_PX ? -COMMIT_PX + (pull + COMMIT_PX) * 0.35 : pull);
  };

  const onPointerEnd = () => {
    const state = drag.current;
    drag.current = null;
    if (!state?.horizontal) return;
    setDragging(false);
    if (offset <= -COMMIT_PX) start();
    else setOffset(0);
  };

  const armed = offset <= -COMMIT_PX;

  return (
    <li className={`relative overflow-hidden border-b border-line last:border-b-0 ${active ? 'bg-cream' : ''}`}>
      {/* 밀면 드러나는 바탕. 문턱을 넘으면 색이 진해져 손을 떼면 시작한다는 걸 알린다. */}
      <div
        className={`absolute inset-y-0 right-0 flex w-full items-center justify-end gap-1.5 pr-5 text-sm font-semibold text-ink transition-colors duration-150 ${
          armed || leaving ? 'bg-mango-500' : 'bg-cream-deep'
        } ${offset === 0 && !leaving ? 'invisible' : ''}`}
        aria-hidden
      >
        <Footprints size={17} />
        {armed || leaving ? '놓으면 산책 시작' : '산책 시작'}
      </div>
      <div
        className={`relative ${active ? 'bg-cream' : 'bg-white'}`}
        style={{
          transform: `translateX(${leaving ? '-100%' : `${offset}px`})`,
          transition: dragging ? 'none' : 'transform 200ms cubic-bezier(0.23, 1, 0.32, 1)',
        }}
      >
        <button
          type="button"
          aria-pressed={active}
          onClick={() => {
            if (swiped.current) {
              swiped.current = false;
              return;
            }
            onToggle();
          }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerEnd}
          onPointerCancel={onPointerEnd}
          className={`grid w-full touch-pan-y ${COLUMNS} items-center gap-2 px-3 py-2.5 text-left text-sm`}
        >
          <span className="flex min-w-0 items-center gap-2">
            <span
              className="flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full font-brand text-xs text-white"
              style={{ background: rank ? RANK_COLORS[rank] : '#a39d8d' }}
              aria-label={rank ? `추천 ${rank}위` : undefined}
            >
              {rank ?? <Route size={11} aria-hidden />}
            </span>
            <span className="min-w-0">
              <span className="line-clamp-2 block font-semibold leading-snug text-ink" data-testid={active ? 'selected-course-name' : undefined}>
                {course.name}
              </span>
              <span className="block text-xs text-ink-soft">
                {course.is_personal && <span className="mr-1 font-semibold text-carrot-700">내 산책길</span>}
                {isGpxCourse(course) && <span className="mr-1 font-semibold text-sky-500">GPX 코스</span>}
                혼잡 {course.data_sources.unknown?.includes('crowd_level') ? '확인 불가' : CROWD_LABELS[course.crowd_level]}
              </span>
            </span>
          </span>
          <span className="text-right tabular-nums text-ink">{course.distance_km.toFixed(1)}km</span>
          <span className="text-right tabular-nums text-ink">{course.duration_min}분</span>
          <span className="flex items-center" aria-label={shadeLabel(course.shade_level)}>
            <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-cream-deep">
              <span className="block h-full rounded-full bg-leaf-500" style={{ width: `${Math.round(course.shade_level * 100)}%` }} />
            </span>
          </span>
        </button>
        {active && <CourseDetail course={course} recommendationId={recommendationId} />}
      </div>
    </li>
  );
}

function CourseDetail({ course, recommendationId }: { course: Course; recommendationId?: number }) {
  const estimates = course.data_sources.team_estimates?.length;
  const unknown = new Set(course.data_sources.unknown ?? []);
  const road = course.environment?.road;
  const gpx = isGpxCourse(course) ? course.data_sources.gpx : undefined;
  return (
    <div className="pp-rise px-3 pb-3">
      <p className="text-sm text-ink-soft">{course.description}</p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {course.is_personal && <Chip tone="carrot">내 산책길</Chip>}
        {gpx && <Chip tone="leaf">GPX 코스</Chip>}
        {gpx && <Chip>{gpx.route_type === 'one_way' ? `편도 ${gpx.one_way_km.toFixed(2)}km 왕복` : '순환'}</Chip>}
        {course.park_names.map((name) => (
          <Chip key={name} tone="leaf">
            {name}
          </Chip>
        ))}
        <Chip>{unknown.has('difficulty') ? '경사 확인 불가' : DIFFICULTY_COURSE_LABELS[course.difficulty]}</Chip>
        <Chip>혼잡도 {unknown.has('crowd_level') ? '확인 불가' : CROWD_LABELS[course.crowd_level]}</Chip>
        {!road && <Chip>{unknown.has('traffic_exposure') ? '차량 노출 확인 불가' : `${TRAFFIC_LABELS[course.traffic_exposure]} (추정)`}</Chip>}
      </div>
      {road && road.unknown <= 0.3 && (
        <p className="mt-2 text-xs text-ink-soft">
          OSM 도로 기록: 보행 전용 {Math.round(road.pedestrian * 100)}%, 생활도로 {Math.round(road.local * 100)}%, 큰 도로 {Math.round(road.major * 100)}%
        </p>
      )}
      <p className="mt-2 text-xs leading-relaxed text-ink-muted">
        {gpx
          ? `공개 GPX 경로(${course.data_sources.source_file ?? 'GPX'})로 만든 코스예요. 좌표 ${gpx.point_count}개로 잰 거리이고, 걷는 시간은 시속 3.6km로 추정했어요. 고도 ${gpx.elevation ? `상승 ${gpx.elevation.gain_m}m` : '기록이 없어 경사는 확인 불가'}예요.`
          : course.is_personal
          ? `내 산책길로 만든 코스예요(${course.data_sources.route ?? '내 경로'}). 주변 환경은 OpenStreetMap 기록으로 측정했고, 기록이 없는 항목은 확인 불가예요.`
          : '경로와 시설 위치는 OpenStreetMap 기준이에요.'}
        {estimates ? ' 혼잡도, 그늘, 노면, 난이도는 팀 추정값이고, 조명은 기록이 없으면 확인 불가예요. 현장에서 확인해 주세요.' : ''} {course.pet_rule_note}
      </p>
      <LinkButton to={walkLink(course, recommendationId)} className="mt-3 w-full">
        <Footprints size={16} aria-hidden />
        이 코스로 산책
      </LinkButton>
      <NearbyPlaces courseId={course.id} />
    </div>
  );
}
