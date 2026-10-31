import { Footprints, Route } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import CourseMap, { FACILITY_MARKERS, RANK_COLORS } from '../components/CourseMap';
import NearbyPlaces from '../components/NearbyPlaces';
import { Card, Chip, ErrorNotice, LinkButton, Loading, PageTitle } from '../components/ui';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import { CROWD_LABELS, DIFFICULTY_COURSE_LABELS, FACILITY_LABELS, TRAFFIC_LABELS } from '../lib/labels';
import type { Course } from '../lib/types';

export default function MapPage() {
  const { cachedRecommendation } = useApp();
  const [params, setParams] = useSearchParams();
  const [courses, setCourses] = useState<Course[]>([]);
  const [error, setError] = useState<string | null>(null);
  const selectedId = Number(params.get('course')) || null;

  useEffect(() => {
    api.listCourses().then(setCourses).catch((loadError: Error) => setError(loadError.message));
  }, []);

  const select = useCallback((id: number) => setParams({ course: String(id) }, { replace: true }), [setParams]);

  const rankById = useMemo(() => {
    const ranks: Record<number, number> = {};
    for (const course of cachedRecommendation?.courses ?? []) ranks[course.course_id] = course.rank;
    return ranks;
  }, [cachedRecommendation]);

  const ordered = useMemo(
    () => [...courses].sort((a, b) => (rankById[a.id] ?? 99) - (rankById[b.id] ?? 99) || a.id - b.id),
    [courses, rankById],
  );
  const selected = courses.find((course) => course.id === selectedId);
  const typesShown = Array.from(new Set(selected?.facilities.map((facility) => facility.type) ?? []));

  if (error) return <ErrorNotice message={error} />;
  if (courses.length === 0) return <Loading label="코스를 불러오는 중이에요" />;

  return (
    <div>
      <PageTitle sub={`${courses[0].area}의 실제 경로예요. 코스를 고르면 시설이 표시돼요.`}>산책 코스 지도</PageTitle>
      <div className="grid gap-4 md:grid-cols-[1.4fr_1fr] md:items-start">
        <div className="flex flex-col gap-3">
          <CourseMap courses={courses} selectedId={selectedId} rankById={rankById} onSelect={select} />
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
          {selected && <SelectedCourse course={selected} recommendationId={cachedRecommendation?.id} />}
        </div>

        <ul className="flex flex-col gap-2" aria-label="코스 목록">
          {ordered.map((course) => {
            const rank = rankById[course.id];
            const active = course.id === selectedId;
            return (
              <li key={course.id}>
                <button
                  type="button"
                  aria-pressed={active}
                  onClick={() => select(course.id)}
                  className={`flex w-full items-center gap-3 rounded-2xl border p-3 text-left transition ${
                    active ? 'border-leaf-500 bg-leaf-50' : 'border-line bg-white'
                  }`}
                >
                  <span
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full font-brand text-white"
                    style={{ background: rank ? RANK_COLORS[rank] : '#a39d8d' }}
                  >
                    {rank ?? <Route size={15} aria-hidden />}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-bold">{course.name}</span>
                    {course.is_personal && <span className="mt-0.5 inline-block text-[11px] font-semibold text-carrot-700">내 산책길</span>}
                    <span className="block text-xs text-ink-soft">
                      {course.distance_km.toFixed(1)}km · 약 {course.duration_min}분
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}

function SelectedCourse({ course, recommendationId }: { course: Course; recommendationId?: number }) {
  const estimates = course.data_sources.team_estimates?.length;
  const unknown = new Set(course.data_sources.unknown ?? []);
  const road = course.environment?.road;
  return (
    <Card>
      <h2 className="font-bold" data-testid="selected-course-name">{course.name}</h2>
      <p className="mt-1 text-sm text-ink-soft">{course.description}</p>
      <p className="mt-2 flex items-center gap-3 text-sm font-semibold">
        <span className="flex items-center gap-1"><Route size={15} aria-hidden />{course.distance_km.toFixed(2)}km</span>
        <span className="flex items-center gap-1"><Footprints size={15} aria-hidden />약 {course.duration_min}분</span>
      </p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {course.is_personal && <Chip tone="carrot">내 산책길</Chip>}
        {course.park_names.map((name) => <Chip key={name} tone="leaf">{name}</Chip>)}
        <Chip>{unknown.has('difficulty') ? '경사 확인 불가' : DIFFICULTY_COURSE_LABELS[course.difficulty]}</Chip>
        <Chip>혼잡도 {unknown.has('crowd_level') ? '확인 불가' : CROWD_LABELS[course.crowd_level]}</Chip>
        {!road && <Chip>{unknown.has('traffic_exposure') ? '차량 노출 확인 불가' : `${TRAFFIC_LABELS[course.traffic_exposure]} (추정)`}</Chip>}
      </div>
      {road && road.unknown <= 0.3 && (
        <p className="mt-2 text-xs text-ink-soft">
          OSM 도로 기록: 보행 전용 {Math.round(road.pedestrian * 100)}%, 생활도로 {Math.round(road.local * 100)}%, 큰 도로 {Math.round(road.major * 100)}%
        </p>
      )}
      <p className="mt-3 text-xs leading-relaxed text-ink-muted">
        {course.is_personal ? `내 산책길로 만든 코스예요(${course.data_sources.route ?? '내 경로'}). 주변 환경은 OpenStreetMap 기록으로 측정했고, 기록이 없는 항목은 확인 불가예요.` : '경로와 시설 위치는 OpenStreetMap 기준이에요.'}
        {estimates ? ' 혼잡도, 그늘, 노면, 난이도는 팀 추정값이고, 조명은 기록이 없으면 확인 불가예요. 현장에서 확인해 주세요.' : ''} {course.pet_rule_note}
      </p>
      <LinkButton
        to={`/navigate?course=${course.id}${recommendationId ? `&recommendation=${recommendationId}` : ''}`}
        className="mt-3 w-full"
      >
        <Footprints size={16} aria-hidden />
        이 코스로 산책
      </LinkButton>
      <NearbyPlaces courseId={course.id} />
    </Card>
  );
}
