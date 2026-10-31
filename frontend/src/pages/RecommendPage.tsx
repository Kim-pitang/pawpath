import {
  AlertTriangle,
  ArrowUp,
  ChevronDown,
  ChevronRight,
  Clock,
  Footprints,
  Home as HomeIcon,
  Map as MapIcon,
  RefreshCw,
  ShieldCheck,
  TrendingUp,
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import HBarChart from '../components/charts/HBarChart';
import SlotColumns from '../components/charts/SlotColumns';
import RouteThumbnail from '../components/RouteThumbnail';
import SafetyPanel from '../components/SafetyPanel';
import { Button, Card, Chip, EmptyState, ErrorNotice, LinkButton, Loading, SectionTitle } from '../components/ui';
import WeatherScenarioPicker from '../components/WeatherScenarioPicker';
import WeatherSourceTag from '../components/WeatherSourceTag';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import { dayLabel, signed, slotRange } from '../lib/format';
import { CROWD_LABELS, FACILITY_LABELS } from '../lib/labels';
import type { Course, Recommendation, RecommendedCourse } from '../lib/types';

const RANK_BADGE: Record<number, string> = {
  1: 'bg-mango-700',
  2: 'bg-leaf-500',
  3: 'bg-sky-500',
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
      </Card>

      {error && <ErrorNotice message={error} />}
      {loading && !result && <Loading label="날씨와 코스를 분석하는 중이에요" />}

      {result && (
        <div className={`flex flex-col gap-4 transition-opacity ${loading ? 'opacity-60' : ''}`}>
          <TimeSection result={result} />
          {result.walkable ? (
            <section aria-label="추천 코스 TOP 3" className="flex flex-col gap-4">
              <h2 className="text-lg font-bold text-ink">추천 코스 TOP 3</h2>
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
  const title = result ? (top ? `코스 ${result.courses.length}곳을 골랐어요` : '오늘은 실내가 좋아요') : '코스를 고르는 중이에요';
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

function TimeSection({ result }: { result: Recommendation }) {
  const { best_slots: best, slots, recommended_duration_min: duration } = result.time_recommendation;
  if (slots.length === 0) {
    return (
      <Card>
        <SectionTitle>추천 시간대</SectionTitle>
        <p className="text-sm text-ink-soft">지금부터 24시간 안에 가능한 시간이 없어요. 산책 가능 시간을 확인해 주세요.</p>
      </Card>
    );
  }
  return (
    <Card>
      <SectionTitle>추천 시간대</SectionTitle>
      {best.length > 0 ? (
        <ul className="mb-4 flex flex-col gap-2">
          {best.map((slot) => (
            <li key={slot.start} className="rounded-lg bg-cream-deep p-3">
              <p className="flex items-center gap-1.5 font-bold text-ink">
                <Clock size={17} className="text-ink-soft" aria-hidden />
                {slotRange(slot.start, slot.end)}
              </p>
              <p className="mt-1 text-sm text-ink-soft">
                약 {slot.duration_min}분 · 체감 {slot.weather.apparent_temperature.toFixed(0)}°C · 강수 확률{' '}
                {slot.weather.precipitation_probability.toFixed(0)}%
                {slot.before_rain && ' · 비 오기 전'}
              </p>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mb-4 text-sm font-semibold text-carrot-700">오늘은 가능한 시간이 모두 산책에 좋지 않아요.</p>
      )}
      <SlotColumns slots={slots} bestSlots={best} />
      <p className="mt-2 text-xs text-ink-muted">권장 산책 시간 약 {duration}분 기준 점수예요.</p>
    </Card>
  );
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
  // 다녀오지 않은 코스의 작은 감소는 가중치 이동에 따른 것이라 표시하지 않는다.
  const showLearning = course.feedback_count > 0 ? course.learning_delta !== 0 : course.learning_delta >= 0.5;
  const primary = course.rank === 1;

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
        <div className="min-w-0 flex-1">
          <h3 className="text-lg font-bold leading-snug text-ink">{course.name}</h3>
          <p className="mt-0.5 text-sm tabular-nums text-ink-soft">
            {course.distance_km.toFixed(2)}km · 약 {course.duration_min}분 ·{' '}
            <span className="font-semibold text-ink">{course.total_score.toFixed(1)}점</span>
          </p>
          {(showLearning || course.rank_change > 0) && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {showLearning && (
                <Chip tone={course.learning_delta > 0 ? 'leaf' : 'carrot'}>
                  <TrendingUp size={13} aria-hidden />
                  학습 효과 {signed(course.learning_delta)}점
                </Chip>
              )}
              {course.rank_change > 0 && (
                <Chip tone="leaf">
                  <ArrowUp size={13} aria-hidden />
                  학습 전보다 {course.rank_change}계단 상승
                </Chip>
              )}
            </div>
          )}
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
                {[
                  course.safety.has_park ? '공원 포함' : '공원 없음',
                  `노면: ${course.safety.surface_note}(추정)`,
                  `혼잡도 ${CROWD_LABELS[course.safety.crowd_level]}(추정)`,
                ].join(' · ')}
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
                note: `비중 ${Math.round(group.weight * 100)}%`,
              }))}
            />
            <ul className="flex flex-col gap-1 text-xs leading-relaxed text-ink-soft">
              {course.reason.details.map((detail) => (
                <li key={detail}>{detail}</li>
              ))}
            </ul>
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
          오늘은 실내 놀이를 추천해요
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
