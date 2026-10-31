import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Clock,
  Footprints,
  Home as HomeIcon,
  Map as MapIcon,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import HBarChart from '../components/charts/HBarChart';
import RouteThumbnail from '../components/RouteThumbnail';
import SafetyPanel from '../components/SafetyPanel';
import { Button, Card, EmptyState, ErrorNotice, InfoNotice, LinkButton, Loading, SectionTitle } from '../components/ui';
import WeatherScenarioPicker from '../components/WeatherScenarioPicker';
import WeatherSourceTag from '../components/WeatherSourceTag';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import { dayLabel, signed } from '../lib/format';
import { CROWD_LABELS, FACILITY_LABELS } from '../lib/labels';
import type { Course, Recommendation, RecommendationStatus, RecommendedCourse } from '../lib/types';

const RANK_BADGE: Record<number, string> = {
  1: 'bg-mango-700',
  2: 'bg-leaf-500',
  3: 'bg-sky-500',
};

/** 산책을 권하지 않을 때 이유별 제목. 데이터가 없는 것과 날씨가 나쁜 것을 구분한다. */
const BLOCKED_TITLE: Record<RecommendationStatus, string> = {
  ok: '',
  unsafe: '오늘은 실내 놀이를 추천해요',
  no_forecast: '날씨를 확인하지 못했어요',
  no_window: '산책 가능 시간이 없어요',
  no_candidates: '추천할 코스가 없어요',
};

export default function RecommendPage() {
  const { selectedPet, petsLoaded, scenario, loadRecommendation, cachedRecommendation, replaceRecommendation } = useApp();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [routes, setRoutes] = useState<Record<number, Course['route']>>({});
  const petId = selectedPet?.id;

  // 카드에 코스 모양을 그리려고 경로를 한 번 받아 둔다. 실패해도 카드는 빈 그림으로 그대로 보인다.
  useEffect(() => {
    api
      .listCourses()
      .then((list) => setRoutes(Object.fromEntries(list.map((item) => [item.id, item.route]))))
      .catch(() => undefined);
  }, []);

  const load = useCallback(
    async (force: boolean) => {
      setLoading(true);
      setError(null);
      try {
        await loadRecommendation({ force });
      } catch (loadError) {
        setError((loadError as Error).message);
      } finally {
        setLoading(false);
      }
    },
    [loadRecommendation],
  );

  useEffect(() => {
    if (petId && !cachedRecommendation) void load(false);
    // 반려동물이나 날씨 조건이 바뀌어 캐시가 비었을 때만 다시 계산한다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [petId, scenario, cachedRecommendation]);

  // 추천은 먼저 보여 주고, 문장 보강은 따로 요청해 끝나면 바꾼다. 실패해도 템플릿 문장이 남는다.
  const explaining = useRef<number | null>(null);
  const result = cachedRecommendation;
  useEffect(() => {
    if (!result || result.explanation_engine?.status !== 'pending' || explaining.current === result.id) return;
    explaining.current = result.id;
    api.explainRecommendation(result.id).then(replaceRecommendation).catch(() => undefined);
  }, [result, replaceRecommendation]);

  if (petsLoaded && !selectedPet) {
    return (
      <Card>
        <EmptyState title="먼저 반려동물을 등록해 주세요">
          <LinkButton to="/pets/new">반려동물 등록하기</LinkButton>
        </EmptyState>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <RecommendTitle petName={selectedPet?.name} result={result} />

      <Card>
        <WeatherScenarioPicker status={result && <WeatherSourceTag weather={result.weather} />} />
        {result?.data_notice && <div className="mt-3" data-testid="data-notice"><InfoNotice>{result.data_notice}</InfoNotice></div>}
      </Card>

      {error && <ErrorNotice message={error} />}
      {loading && !result && <Loading label="날씨와 코스를 분석하는 중이에요" />}

      {result && (
        <div className={`flex flex-col gap-4 transition-opacity ${loading ? 'opacity-60' : ''}`}>
          {result.walkable ? (
            <section aria-label="추천 코스 TOP 3" className="flex flex-col gap-4">
              <aside aria-label="산책 시간 기준" className="flex flex-wrap items-center gap-x-2 gap-y-1 px-1 py-1 text-sm text-ink-soft">
                <Clock size={16} className="shrink-0" aria-hidden />
                <span>권장 <strong className="font-semibold text-ink">약 {result.time_recommendation.recommended_duration_min}분</strong> 기준</span>
                <span className="hidden h-3 w-px bg-line sm:block" aria-hidden />
                <span className="text-xs">아래 코스를 고를 때 참고해 주세요.</span>
              </aside>
              <div className="grid items-start gap-4 lg:grid-cols-3">
                {result.courses.map((course) => (
                  <CourseCard
                    key={course.course_id}
                    course={course}
                    route={routes[course.course_id] ?? []}
                    recommendationId={result.id}
                    explanationStatus={result.explanation_engine?.status}
                  />
                ))}
              </div>
              <ExcludedCourses result={result} />
            </section>
          ) : (
            <>
              <IndoorCard result={result} />
              <ExcludedCourses result={result} />
            </>
          )}
          <Button variant="ghost" onClick={() => load(true)} disabled={loading}>
            <RefreshCw size={16} aria-hidden />
            다시 추천받기
          </Button>
          {result.algorithm && (
            <p className="px-1 text-center text-[11px] text-ink-muted">
              추천 알고리즘 {result.algorithm.version} · 안전 평가를 먼저 하고, 위험 코스는 점수와 관계없이 뒤로 보내요.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * 화면 제목은 무엇을 계산했는지보다 무엇이 나왔는지를 먼저 말한다.
 * 1위 코스와 출발 시각을 바로 아래에 두고, 누르면 그 카드로 내려간다. 계산 기준은 작은 설명으로 남긴다.
 */
function RecommendTitle({ petName, result }: { petName?: string; result: Recommendation | null }) {
  const top = result?.walkable ? result.courses[0] : undefined;
  const blockedTitle = !result?.status || result.status === 'unsafe' ? '오늘은 실내가 좋아요' : BLOCKED_TITLE[result.status] || '추천할 코스가 없어요';
  const title = result ? (top ? `코스 ${result.courses.length}곳을 골랐어요` : blockedTitle) : '코스를 고르는 중이에요';
  const goToTop = () => {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    document.querySelector('[data-testid="course-card-1"]')?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
  };

  return (
    <header>
      <p className="text-sm font-semibold text-mango-700">{petName ? `${petName}의 오늘의 산책각` : '오늘의 산책각'}</p>
      <h1 className="mt-0.5 text-2xl font-bold tracking-[-0.01em] text-ink">{title}</h1>
      {top && (
        <button type="button" onClick={goToTop} className="mt-2 flex min-h-8 items-center gap-1 text-left text-sm text-ink hover:underline">
          <span className="text-ink-soft">1위</span>
          <span className="font-semibold">{top.name}</span>
          <span className="text-ink-soft">· {clockPhrase(top.recommended_time.start)} 출발</span>
          <ChevronRight size={14} className="shrink-0 text-ink-soft" aria-hidden />
        </button>
      )}
      <p className="mt-1 text-xs text-ink-soft">성향, 일정, 날씨, 지난 피드백을 함께 계산했어요.</p>
    </header>
  );
}

/** "오전 7:00"처럼 오전·오후와 시각. */
function clockPhrase(iso: string): string {
  const date = new Date(iso);
  const hours = date.getHours();
  return `${hours < 12 ? '오전' : '오후'} ${hours % 12 === 0 ? 12 : hours % 12}:${String(date.getMinutes()).padStart(2, '0')}`;
}

function ExcludedCourses({ result }: { result: Recommendation }) {
  if (result.excluded_courses.length === 0) return null;
  return (
    <details className="rounded-lg border border-line bg-white p-3 text-sm" data-testid="excluded-courses">
      <summary className="cursor-pointer font-semibold text-ink-soft">
        위험 조건으로 제외한 코스 {result.excluded_courses.length}곳
      </summary>
      <ul className="mt-2 flex flex-col gap-2">
        {result.excluded_courses.map((course) => (
          <li key={course.course_id}>
            <p className="font-semibold">{course.name}</p>
            <p className="text-xs text-ink-soft">{course.reasons.join(' / ')}</p>
          </li>
        ))}
      </ul>
    </details>
  );
}

function ReasonSource({ course, status }: { course: RecommendedCourse; status?: Recommendation['explanation_engine']['status'] }) {
  if (course.reason.llm_summary) return <p className="mt-1 px-1 text-[11px] text-ink-muted">AI가 근거 자료로 다듬은 문장이에요. 점수에는 영향을 주지 않아요.</p>;
  if (status === 'pending') return <p className="mt-1 px-1 text-[11px] text-ink-muted">AI 문장을 만드는 중이에요. 아래 내용은 계산 결과로 만든 문장이에요.</p>;
  return null;
}

function CourseCard({
  course,
  route,
  recommendationId,
  explanationStatus,
}: {
  course: RecommendedCourse;
  route: [number, number][];
  recommendationId: number;
  explanationStatus?: Recommendation['explanation_engine']['status'];
}) {
  const [open, setOpen] = useState(false);
  const time = course.recommended_time;
  const facilities = Object.entries(course.safety.verified_facilities);
  // 날씨와 환경 위험은 안전 패널에 있으므로 여기서는 그 밖의 주의사항만 보여 준다.
  const cautions = course.other_cautions;
  const disclaimer = course.cautions[course.cautions.length - 1];
  const primary = course.rank === 1;
  const skipped = (course.score_groups ?? []).filter((group) => !group.available);
  const markSelected = () => {
    api.recommendationEvent(recommendationId, course.course_id, 'select').catch(() => undefined);
  };

  // 경로 티켓: 코스 모양이 카드의 얼굴이고, 아래 띠가 출발 시각을 표처럼 보여 준다.
  return (
    <article
      data-testid={`course-card-${course.rank}`}
      className={`pp-rise overflow-hidden rounded-xl border bg-white ${primary ? 'border-mango-500' : 'border-line'}`}
      style={{ animationDelay: `${(course.rank - 1) * 60}ms` }}
    >
      <div className="flex gap-4 p-4 pb-0">
        <div className="relative shrink-0">
          <RouteThumbnail segments={route.length > 1 ? [route] : []} size={96} label={`${course.name} 경로 모양`} />
          <span
            className={`absolute -top-1.5 -left-1.5 flex h-7 w-7 items-center justify-center rounded-full font-brand text-sm text-white ${RANK_BADGE[course.rank]}`}
          >
            {course.rank}
          </span>
        </div>
        <div className="min-w-0 flex-1 self-center">
          <h3 className="text-lg font-bold leading-snug text-ink">{course.name}</h3>
          {course.is_personal && <span className="text-xs font-semibold text-mango-700">내 산책길</span>}
          {course.exploration && <span className="ml-1 text-xs font-semibold text-ink-soft">새 코스 제안</span>}
          <p className="mt-0.5 text-sm tabular-nums text-ink-soft">
            {course.distance_km.toFixed(2)}km · 약 {course.duration_min}분 ·{' '}
            <span className="font-semibold text-ink">{course.total_score.toFixed(1)}점</span>
          </p>
        </div>
      </div>

      <div className="px-4 pt-3 pb-4">
        <p className="text-sm leading-relaxed text-ink" data-testid="reason-summary">
          {course.reason.llm_summary ?? course.reason.summary}
        </p>
        <ReasonSource course={course} status={explanationStatus} />

        <div className="mt-3">
          <SafetyPanel assessment={course.safety_assessment} />
        </div>

        {course.alternative && (
          <p className="mt-2 rounded-lg bg-cream-deep px-3 py-2 text-sm text-ink">
            더 안전한 대체 코스:{' '}
            <Link to={`/map?course=${course.alternative.course_id}`} className="font-bold underline">
              {course.alternative.name}
            </Link>{' '}
            ({course.alternative.distance_km.toFixed(1)}km, 약 {course.alternative.duration_min}분)
          </p>
        )}

        {cautions.length > 0 && (
          <ul className="mt-3 flex flex-col gap-1.5 rounded-lg bg-[#fffbeb] p-3 text-sm text-[#92400e]">
            {cautions.map((caution) => (
              <li key={caution} className="flex items-start gap-1.5">
                <AlertTriangle size={15} className="mt-0.5 shrink-0" aria-hidden />
                <span>{caution}</span>
              </li>
            ))}
          </ul>
        )}

        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          className="mt-2 -mb-2 flex min-h-10 w-full items-center justify-between text-sm font-semibold text-ink-soft hover:text-ink"
        >
          점수 근거 보기
          <ChevronDown size={18} className={`transition-transform duration-200 ease-out ${open ? 'rotate-180' : ''}`} aria-hidden />
        </button>
        {open && (
          <div className="mt-3 flex flex-col gap-3">
            <dl className="flex flex-col gap-1.5 text-sm">
              <InfoRow icon={<ShieldCheck size={15} />} label="코스 정보">
                {courseInfo(course).join(' · ')}
              </InfoRow>
              {facilities.length > 0 && (
                <InfoRow icon={<MapIcon size={15} />} label="확인된 시설">
                  {facilities.map(([type, count]) => `${FACILITY_LABELS[type] ?? type} ${count}`).join(' · ')}
                </InfoRow>
              )}
            </dl>
            <HBarChart
              ariaLabel="항목별 점수"
              items={course.score_breakdown.map((group) => ({
                key: group.key,
                label: group.label,
                value: group.score,
                note: group.key === 'feedback' ? `조정 ${signed(group.contribution)}점` : `비중 ${Math.round(group.weight * 100)}%`,
              }))}
            />
            {course.personalization_score != null && (
              <p className="text-xs text-ink-soft" data-testid="score-formula">
                개인화 {course.personalization_score.toFixed(1)}점
                {course.safety_penalty ? ` − 안전 감점 ${course.safety_penalty.toFixed(1)}점` : ''}
                {course.skip_penalty ? ` − 최근 다른 코스를 고른 날 ${course.skip_penalty.toFixed(0)}점` : ''} = 추천 점수 {course.total_score.toFixed(1)}점
              </p>
            )}
            {skipped.length > 0 && (
              <p className="text-xs text-ink-muted" data-testid="skipped-groups">
                반영하지 않은 항목: {skipped.map((group) => group.label).join(', ')} (데이터가 없어 다른 항목으로 나눠 계산했어요)
              </p>
            )}
            {course.reason.basis && course.reason.basis.length > 0 && (
              <dl className="flex flex-col gap-1.5 text-xs leading-relaxed" aria-label="추천 근거">
                {course.reason.basis.map((item) => (
                  <div key={item.key}>
                    <dt className="font-semibold text-ink">{item.label}</dt>
                    <dd className="text-ink-soft">
                      {item.text} <span className="text-ink-muted">({item.source})</span>
                    </dd>
                  </div>
                ))}
              </dl>
            )}
            {/* 예전 추천에는 항목별 근거가 없어 세부 문장을 보여 준다. */}
            {!course.reason.basis?.length && (
              <ul className="flex flex-col gap-1 text-xs leading-relaxed text-ink-soft">
                {course.reason.details.map((detail) => (
                  <li key={detail}>{detail}</li>
                ))}
              </ul>
            )}
            <p className="text-xs text-ink-muted">{course.safety.pet_rule_note}</p>
            <p className="text-xs text-ink-muted">{disclaimer}</p>
          </div>
        )}

      </div>

      <div className={`flex items-center gap-3 px-4 py-3 ${primary ? 'bg-mango-500' : 'bg-cream-deep'}`}>
        <div className="min-w-0 flex-1">
          <p className="text-2xl font-bold leading-none tabular-nums text-ink">
            <span className="mr-1 text-sm font-semibold">{dayLabel(time.start)}</span>
            {clockLabel(time.start)}
            <span className="ml-1 text-sm font-semibold">출발</span>
          </p>
          <p className="mt-1 text-xs tabular-nums text-ink">
            체감 {time.weather.apparent_temperature.toFixed(0)}° · 강수 {time.weather.precipitation_probability.toFixed(0)}% · 바람{' '}
            {time.weather.wind_speed.toFixed(1)}m/s
          </p>
        </div>
        <Link
          to={`/map?course=${course.course_id}`}
          aria-label="지도 보기"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-white/70 text-ink transition-[background-color,transform] hover:bg-white active:scale-95"
        >
          <MapIcon size={18} aria-hidden />
        </Link>
        <Link
          to={`/navigate?course=${course.course_id}&recommendation=${recommendationId}`}
          onClick={markSelected}
          aria-label="이 코스로 산책"
          className="inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-full bg-ink px-4 text-sm font-bold text-white transition-[background-color,transform] hover:bg-black active:scale-[0.97]"
        >
          <Footprints size={15} aria-hidden />
          산책
        </Link>
      </div>
    </article>
  );
}

/** "7:00", "17:30"처럼 시각만 짧게. */
function clockLabel(iso: string): string {
  const date = new Date(iso);
  return `${date.getHours()}:${String(date.getMinutes()).padStart(2, '0')}`;
}

function courseInfo(course: RecommendedCourse): string[] {
  const { safety } = course;
  const unknown = new Set(safety.unknown ?? []);
  if (!safety.is_personal) {
    return [safety.has_park ? '공원 포함' : '공원 없음', `노면: ${safety.surface_note}(추정)`, `혼잡도 ${CROWD_LABELS[safety.crowd_level]}(추정)`];
  }
  return [
    unknown.has('has_park') ? '공원 확인 불가' : safety.has_park ? '공원 포함' : '공원 없음',
    `노면: ${safety.surface_note}`,
    '혼잡도 확인 불가',
  ];
}

function InfoRow({ icon, label, children }: { icon: React.ReactNode; label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-1.5">
      <dt className="flex shrink-0 items-center gap-1 pt-px text-ink-muted">
        <span aria-hidden>{icon}</span>
        <span className="sr-only">{label}</span>
      </dt>
      <dd className="text-ink-soft">{children}</dd>
    </div>
  );
}

function IndoorCard({ result }: { result: Recommendation }) {
  return (
    <Card className="border-carrot-100">
      <SectionTitle>
        <span className="flex items-center gap-1.5">
          <HomeIcon size={18} className="text-ink-soft" aria-hidden />
          {BLOCKED_TITLE[result.status ?? 'unsafe'] || BLOCKED_TITLE.unsafe}
        </span>
      </SectionTitle>
      {result.blocked_reasons.length > 0 && (
        <p className="mb-3 text-sm text-ink-soft">산책 제외 이유: {result.blocked_reasons.join(', ')}</p>
      )}
      <ul className="flex flex-col gap-2 text-sm text-ink">
        {result.indoor_alternatives.map((tip) => (
          <li key={tip} className="rounded-lg bg-cream p-3">{tip}</li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-ink-muted">{result.disclaimer}</p>
    </Card>
  );
}
