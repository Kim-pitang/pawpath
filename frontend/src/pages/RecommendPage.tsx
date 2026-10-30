import {
  AlertTriangle,
  ArrowUp,
  ChevronDown,
  Clock,
  Footprints,
  Home as HomeIcon,
  Map as MapIcon,
  RefreshCw,
  Route,
  ShieldCheck,
  Thermometer,
  TrendingUp,
} from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import HBarChart from '../components/charts/HBarChart';
import SlotColumns from '../components/charts/SlotColumns';
import { Button, Card, Chip, EmptyState, ErrorNotice, InfoNotice, LinkButton, Loading, PageTitle, SectionTitle } from '../components/ui';
import WeatherScenarioPicker from '../components/WeatherScenarioPicker';
import { useApp } from '../context/AppContext';
import { signed, slotRange } from '../lib/format';
import { CROWD_LABELS, FACILITY_LABELS, TRAFFIC_LABELS, WEATHER_SOURCE_LABELS } from '../lib/labels';
import type { Recommendation, RecommendedCourse } from '../lib/types';

const RANK_BADGE: Record<number, string> = {
  1: 'bg-leaf-500',
  2: 'bg-carrot-500',
  3: 'bg-sky-500',
};

export default function RecommendPage() {
  const { selectedPet, petsLoaded, scenario, loadRecommendation, cachedRecommendation } = useApp();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const petId = selectedPet?.id;

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

  if (petsLoaded && !selectedPet) {
    return (
      <Card>
        <EmptyState title="먼저 반려동물을 등록해 주세요">
          <LinkButton to="/pets/new">반려동물 등록하기</LinkButton>
        </EmptyState>
      </Card>
    );
  }

  const result = cachedRecommendation;

  return (
    <div className="flex flex-col gap-4">
      <PageTitle sub="성향, 일정, 날씨, 지난 피드백을 함께 계산했어요.">
        {selectedPet ? `${selectedPet.name}의 오늘의 산책각` : '오늘의 산책각'}
      </PageTitle>

      <Card>
        <WeatherScenarioPicker />
        {result?.weather.notice && (
          <div className="mt-3">
            <InfoNotice>{result.weather.notice}</InfoNotice>
          </div>
        )}
        {result && !result.weather.is_mock && (
          <p className="mt-2 text-xs text-ink-muted">날씨 출처: {WEATHER_SOURCE_LABELS[result.weather.source] ?? result.weather.source}</p>
        )}
      </Card>

      {error && <ErrorNotice message={error} />}
      {loading && !result && <Loading label="날씨와 코스를 분석하는 중이에요" />}

      {result && (
        <div className={`flex flex-col gap-4 transition-opacity ${loading ? 'opacity-60' : ''}`}>
          {result.learning.is_personalized && (
            <InfoNotice>
              지금까지의 피드백 {result.learning.feedback_total}건을 학습해 점수에 반영했어요. 과거 선호도 반영 강도가{' '}
              {Math.round(result.weights.preference * 100)}%로 올라갔어요.
            </InfoNotice>
          )}
          <TimeSection result={result} />
          {result.walkable ? (
            <section aria-label="추천 코스 TOP 3" className="flex flex-col gap-4">
              <h2 className="font-brand text-xl text-leaf-800">추천 코스 TOP 3</h2>
              <div className="grid items-start gap-4 lg:grid-cols-3">
                {result.courses.map((course) => (
                  <CourseCard key={course.course_id} course={course} recommendationId={result.id} />
                ))}
              </div>
            </section>
          ) : (
            <IndoorCard result={result} />
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
            <li key={slot.start} className="rounded-2xl bg-carrot-50 p-3">
              <p className="flex items-center gap-1.5 font-bold text-ink">
                <Clock size={17} className="text-carrot-500" aria-hidden />
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

function CourseCard({ course, recommendationId }: { course: RecommendedCourse; recommendationId: number }) {
  const [open, setOpen] = useState(false);
  const time = course.recommended_time;
  const facilities = Object.entries(course.safety.verified_facilities);
  const cautions = course.cautions.slice(0, -1);
  const disclaimer = course.cautions[course.cautions.length - 1];
  // 다녀오지 않은 코스의 작은 감소는 가중치 이동에 따른 것이라 표시하지 않는다.
  const showLearning = course.feedback_count > 0 ? course.learning_delta !== 0 : course.learning_delta >= 0.5;

  return (
    <Card className={course.rank === 1 ? 'border-leaf-300' : ''}>
      <article data-testid={`course-card-${course.rank}`}>
        <div className="flex items-start gap-3">
          <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full font-brand text-lg text-white ${RANK_BADGE[course.rank]}`}>
            {course.rank}
          </span>
          <div className="min-w-0 flex-1">
            <h3 className="font-bold leading-snug">{course.name}</h3>
            <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-ink-soft">
              <span className="flex items-center gap-0.5"><Route size={13} aria-hidden />{course.distance_km.toFixed(1)}km</span>
              <span className="flex items-center gap-0.5"><Footprints size={13} aria-hidden />약 {course.duration_min}분</span>
            </p>
          </div>
          <div className="shrink-0 text-right">
            <p className="text-2xl font-bold leading-none text-ink">{course.total_score.toFixed(1)}</p>
            <p className="text-[11px] text-ink-muted">추천 점수</p>
          </div>
        </div>

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

        <p className="mt-3 rounded-2xl bg-leaf-50 p-3 text-sm font-medium leading-relaxed text-leaf-800" data-testid="reason-summary">
          {course.reason.summary}
        </p>

        <dl className="mt-3 flex flex-col gap-1.5 text-sm">
          <InfoRow icon={<Clock size={15} />} label="추천 시간">{slotRange(time.start, time.end)}</InfoRow>
          <InfoRow icon={<Thermometer size={15} />} label="날씨">
            체감 {time.weather.apparent_temperature.toFixed(0)}°C · 강수 {time.weather.precipitation_probability.toFixed(0)}% · 바람{' '}
            {time.weather.wind_speed.toFixed(1)}m/s
          </InfoRow>
          <InfoRow icon={<ShieldCheck size={15} />} label="안전 정보">
            {[
              course.safety.has_park ? '공원 포함' : '공원 없음',
              `${course.safety.lighting_text}(추정)`,
              course.safety.surface_note,
              TRAFFIC_LABELS[course.safety.traffic_exposure],
              `혼잡도 ${CROWD_LABELS[course.safety.crowd_level]}(추정)`,
            ].join(' · ')}
          </InfoRow>
          {facilities.length > 0 && (
            <InfoRow icon={<MapIcon size={15} />} label="확인된 시설">
              {facilities.map(([type, count]) => `${FACILITY_LABELS[type] ?? type} ${count}`).join(' · ')}
            </InfoRow>
          )}
        </dl>

        {cautions.length > 0 && (
          <ul className="mt-3 flex flex-col gap-1.5 rounded-2xl bg-carrot-50 p-3 text-sm text-carrot-700">
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
          className="mt-3 flex min-h-10 w-full items-center justify-between text-sm font-semibold text-ink-soft"
        >
          점수 근거 보기
          <ChevronDown size={18} className={`transition ${open ? 'rotate-180' : ''}`} aria-hidden />
        </button>
        {open && (
          <div className="mt-2 flex flex-col gap-3">
            <HBarChart
              ariaLabel="항목별 점수"
              items={course.factors.map((factor) => ({
                key: factor.key,
                label: factor.label,
                value: factor.score,
                note: `비중 ${Math.round(factor.weight * 100)}%`,
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

        <div className="mt-3 grid grid-cols-2 gap-2">
          <LinkButton to={`/map?course=${course.course_id}`} variant="ghost" className="whitespace-nowrap !px-2">
            <MapIcon size={16} aria-hidden />
            지도 보기
          </LinkButton>
          <LinkButton to={`/walk?course=${course.course_id}&recommendation=${recommendationId}`} variant={course.rank === 1 ? 'primary' : 'ghost'} className="whitespace-nowrap !px-2">
            <Footprints size={16} aria-hidden />
            이 코스로 산책
          </LinkButton>
        </div>
      </article>
    </Card>
  );
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
          <HomeIcon size={18} className="text-carrot-500" aria-hidden />
          오늘은 실내 놀이를 추천해요
        </span>
      </SectionTitle>
      {result.blocked_reasons.length > 0 && (
        <p className="mb-3 text-sm text-ink-soft">산책 제외 이유: {result.blocked_reasons.join(', ')}</p>
      )}
      <ul className="flex flex-col gap-2 text-sm text-ink">
        {result.indoor_alternatives.map((tip) => (
          <li key={tip} className="rounded-2xl bg-cream p-3">{tip}</li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-ink-muted">{result.disclaimer}</p>
    </Card>
  );
}
