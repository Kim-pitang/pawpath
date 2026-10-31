import { ChevronRight, Footprints, RotateCw } from 'lucide-react';
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import RouteThumbnail from '../components/RouteThumbnail';
import WeatherSourceTag from '../components/WeatherSourceTag';
import { EmptyState, ErrorNotice, LinkButton } from '../components/ui';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import { dayLabel, windowLabel } from '../lib/format';
import { PERSONALITY_LABELS } from '../lib/labels';
import type { CurrentWeather, Pet, Recommendation, RecommendedCourse, Slot } from '../lib/types';

// 홈은 "오늘 언제, 어디로 걸을까"에 먼저 답한다. 멍고 오렌지는 추천 시간과 산책 버튼에만 쓴다.
const PANEL = 'rounded-lg border border-line bg-white p-5';

export default function HomePage() {
  const { petsLoaded, loadError, selectedPet, schedule, scenario, loadRecommendation, cachedRecommendation } = useApp();
  const [weather, setWeather] = useState<CurrentWeather | null>(null);
  const [recommendError, setRecommendError] = useState<string | null>(null);
  const petId = selectedPet?.id;

  // 날씨 카드는 두지 않는다. 시간표 제목 옆 출처 태그에 쓸 출처와 안내만 받아 온다.
  useEffect(() => {
    if (!petsLoaded) return;
    let active = true;
    api
      .currentWeather(scenario, petId)
      .then((result) => active && setWeather(result))
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [scenario, petId, petsLoaded]);

  // 추천 화면과 같은 캐시를 쓰므로 홈에서 계산한 추천을 추천 화면이 그대로 이어 쓴다.
  useEffect(() => {
    if (!petId) return;
    let active = true;
    setRecommendError(null);
    loadRecommendation().catch((error: Error) => active && setRecommendError(error.message));
    return () => {
      active = false;
    };
  }, [petId, scenario, loadRecommendation]);

  if (petsLoaded && !selectedPet) {
    return (
      <div className="flex flex-col gap-4">
        {loadError && <ErrorNotice message={loadError} />}
        <EmptyState title="아직 등록된 반려동물이 없어요">
          <LinkButton to="/pets/new">반려동물 등록하기</LinkButton>
        </EmptyState>
      </div>
    );
  }

  const recommendation = cachedRecommendation;
  const top = recommendation?.courses[0];
  const bestSlot = top?.recommended_time ?? recommendation?.time_recommendation.best_slots[0];

  return (
    <div className="flex flex-col gap-4">
      {loadError && <ErrorNotice message={loadError} />}

      {/* 반려동물 바꾸기는 머리글 계정 영역에서 한다. 여기서는 누가 선택됐는지 보조 정보로만 보여 준다. */}
      <header className="pt-1">
        {selectedPet && <PetTag pet={selectedPet} />}
        {/* 이름표의 동그라미에서 이어지는 말풍선. 반려동물에게 맞춘 답이라는 느낌을 준다. 문장은 앱의 말투 그대로다. */}
        <div className="relative mt-2 ml-1.5">
          <span className="absolute -top-1.5 left-2 h-3 w-3 rotate-45 rounded-[2px] bg-white" aria-hidden />
          <h1 key={selectedPet?.id} className="pp-bubble relative rounded-xl bg-white px-4 py-3 text-xl font-bold leading-snug text-ink">
            {selectedPet ? headline(selectedPet.name, recommendation, bestSlot, recommendError) : <Bar className="h-7 w-56" />}
          </h1>
        </div>
      </header>

      <div className="grid gap-4 md:grid-cols-2 md:items-start">
        <div className="flex min-w-0 flex-col gap-4">
          <section className={PANEL} aria-labelledby="timeline-title">
            <PanelHeader
              id="timeline-title"
              title={
                <>
                  {bestSlot ? `${dayLabel(bestSlot.start)} 산책 시간표` : '산책 시간표'}
                  {weather && <WeatherSourceTag weather={weather} changeLink />}
                </>
              }
              action={
                schedule && (
                  <Link to="/schedule" className="text-sm text-ink-soft hover:text-ink">
                    {schedule.available_windows.map((window) => windowLabel(window.start_hour, window.end_hour)).join(', ')}
                    <span className="ml-1.5 font-semibold text-ink underline underline-offset-2">변경</span>
                  </Link>
                )
              }
            />
            {recommendation ? (
              <TimeStrip slots={recommendation.time_recommendation.slots} best={bestSlot ?? null} />
            ) : recommendError ? (
              <p className="text-sm text-ink-soft">추천을 불러오면 시간대별 점수가 여기에 표시돼요.</p>
            ) : (
              <Bar className="h-11 w-full" />
            )}
          </section>
          <AnswerPanel recommendation={recommendation} top={top} error={recommendError} onRetry={() => loadRecommendation({ force: true }).catch((error: Error) => setRecommendError(error.message))} />
        </div>
        <div className="flex min-w-0 flex-col gap-4">
          <OtherCourses courses={recommendation?.courses.slice(1, 3) ?? []} loading={!recommendation && !recommendError} />
        </div>
      </div>
    </div>
  );
}

/** 제목 위의 작은 이름표. 견종·나이·체중·성격을 보여 주고, 누르면 프로필 수정으로 간다. */
function PetTag({ pet }: { pet: Pet }) {
  const facts = [pet.breed, `${pet.age_years}세`, `${pet.weight_kg}kg`, PERSONALITY_LABELS[pet.personality]];
  return (
    <Link
      to={`/pets/${pet.id}/edit`}
      aria-label={`${pet.name} 프로필 보기: ${facts.join(', ')}`}
      className="group -ml-1 inline-flex min-h-8 max-w-full items-center gap-1.5 rounded-md px-1 text-sm text-ink-soft hover:bg-cream-deep"
    >
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-mango-500 font-brand text-[11px] text-ink" aria-hidden>
        {pet.name.slice(0, 1)}
      </span>
      {facts.map((fact, index) => (
        <span key={index} className="flex min-w-0 items-center gap-1.5">
          {index > 0 && (
            <span className="text-line" aria-hidden>
              |
            </span>
          )}
          <span className="truncate">{fact}</span>
        </span>
      ))}
      <ChevronRight size={14} className="shrink-0 text-ink-muted transition-transform duration-150 ease-out group-hover:translate-x-0.5" aria-hidden />
    </Link>
  );
}

function headline(name: string, recommendation: Recommendation | null, slot: Slot | undefined, error: string | null): string {
  if (!recommendation) return error ? `${name}의 오늘 산책` : `${name} 산책 시간을 계산하고 있어요`;
  if (!recommendation.walkable || !slot) return `오늘은 ${withParticle(name, '과', '와')} 실내에서 노는 게 좋아요`;
  const time = hourPhrase(slot.start);
  return `${dayLabel(slot.start)} ${name} 산책은 ${withParticle(time, '이', '가')} 좋아요`;
}

/** 마지막 글자의 받침에 따라 조사를 붙인다. 한글이 아니면 받침 없는 쪽을 쓴다. */
function withParticle(word: string, afterBatchim: string, afterVowel: string): string {
  const code = word.charCodeAt(word.length - 1) - 0xac00;
  const batchim = code >= 0 && code <= 11171 && code % 28 !== 0;
  return `${word}${batchim ? afterBatchim : afterVowel}`;
}

function AnswerPanel({
  recommendation,
  top,
  error,
  onRetry,
}: {
  recommendation: Recommendation | null;
  top: RecommendedCourse | undefined;
  error: string | null;
  onRetry: () => void;
}) {
  const courseId = top?.course_id;
  const [route, setRoute] = useState<{ id: number; points: [number, number][] } | null>(null);

  // 카드 왼쪽에 코스 모양을 그리려고 대표 코스의 경로만 받아 온다. 실패해도 빈 그림으로 그대로 보인다.
  useEffect(() => {
    if (!courseId) return;
    let active = true;
    api
      .getCourse(courseId)
      .then((course) => active && setRoute({ id: course.id, points: course.route }))
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [courseId]);

  if (error && !recommendation) {
    return (
      <section className={PANEL} aria-labelledby="answer-title">
        <PanelHeader id="answer-title" title="오늘의 추천 코스" />
        <p className="text-sm text-ink">추천을 계산하지 못했어요. {error}</p>
        <button type="button" onClick={onRetry} className="mt-3 inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-ink underline underline-offset-2">
          <RotateCw size={15} aria-hidden />
          다시 시도
        </button>
      </section>
    );
  }

  if (!recommendation) {
    return (
      <section className={PANEL} aria-label="오늘의 추천 코스 불러오는 중" aria-busy="true">
        <Bar className="h-6 w-48" />
        <Bar className="mt-3 h-4 w-40" />
        <Bar className="mt-4 h-12 w-full" />
        <Bar className="mt-5 h-12 w-full" />
      </section>
    );
  }

  if (!recommendation.walkable || !top) {
    return (
      <section className={PANEL} aria-labelledby="answer-title">
        <PanelHeader id="answer-title" title="오늘 산책을 미루는 이유" />
        <ul className="flex flex-col gap-1.5 text-base text-ink">
          {recommendation.blocked_reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
        {recommendation.indoor_alternatives.length > 0 && (
          <>
            <h3 className="mt-4 text-sm font-semibold text-ink">대신 해 볼 만한 것</h3>
            <ul className="mt-1.5 flex flex-col gap-1 text-sm text-ink-soft">
              {recommendation.indoor_alternatives.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </>
        )}
        <LinkButton to="/recommend" variant="ghost" className="mt-5 w-full !rounded-md">
          추천 자세히
        </LinkButton>
      </section>
    );
  }

  const slot = top.recommended_time;
  const points = route?.id === top.course_id ? route.points : [];
  // 추천 화면의 티켓 카드와 같은 경로 그림을 써서, 같은 코스를 모양으로 알아보게 한다.
  return (
    <section className={PANEL} aria-labelledby="answer-title">
      <div className="flex gap-4">
        <RouteThumbnail segments={points.length > 1 ? [points] : []} size={88} label={`${top.name} 경로 모양`} />
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold text-mango-700">오늘의 추천 코스</p>
          <h2 id="answer-title" className="mt-0.5 text-lg font-bold leading-snug text-ink">
            {top.name}
          </h2>
          <p className="mt-1 text-sm tabular-nums text-ink-soft">
            {clockRange(slot.start, slot.end)} · {top.distance_km.toFixed(2)}km · {top.duration_min}분 ·{' '}
            <span className="font-semibold text-ink">{top.total_score.toFixed(0)}점</span>
          </p>
        </div>
      </div>
      <p className="mt-3 text-base leading-relaxed text-ink" data-testid="home-reason">
        {top.reason.llm_summary ?? top.reason.summary}
      </p>
      {/* 주요 행동은 버튼 하나로 두고, 보조 행동은 글자 링크로 낮춘다. 시간·거리는 카드 위쪽에 이미 있어 버튼에는 다시 적지 않는다. */}
      <div className="mt-5">
        <Link
          to={`/navigate?course=${top.course_id}&recommendation=${recommendation.id}`}
          className="group pp-press flex min-h-14 items-center gap-3 rounded-md bg-mango-500 px-4 py-2.5 text-ink hover:bg-mango-600"
        >
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/60" aria-hidden>
            <Footprints size={18} />
          </span>
          <span className="min-w-0 flex-1 text-base font-bold">이 코스로 산책</span>
          <ChevronRight size={20} className="shrink-0 transition-transform duration-150 ease-out group-hover:translate-x-0.5" aria-hidden />
        </Link>
        <div className="mt-2 flex justify-center">
          <Link to="/recommend" className="flex min-h-10 items-center text-sm font-semibold text-ink-soft underline underline-offset-2 hover:text-ink">
            다른 코스와 추천 근거 보기
          </Link>
        </div>
      </div>
    </section>
  );
}

/** 2·3위를 경로 모양이 있는 작은 카드로 가로로 늘어놓는다. 위 대표 카드와 같은 그림이라 코스를 모양으로 비교할 수 있다. */
function OtherCourses({ courses, loading }: { courses: RecommendedCourse[]; loading: boolean }) {
  const [routes, setRoutes] = useState<Record<number, [number, number][]>>({});
  const ids = courses.map((course) => course.course_id).join(',');

  // 경로 그림만 필요하므로 코스 목록을 한 번 받아 둔다. 실패해도 카드는 빈 그림으로 그대로 보인다.
  useEffect(() => {
    if (!ids) return;
    let active = true;
    api
      .listCourses()
      .then((list) => active && setRoutes(Object.fromEntries(list.map((item) => [item.id, item.route]))))
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [ids]);

  if (!loading && courses.length === 0) return null;
  return (
    <section className={PANEL} aria-labelledby="others-title">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 id="others-title" className="text-base font-semibold text-ink">
          다른 코스
          {!loading && <span className="ml-1.5 text-sm font-normal text-ink-soft">{courses.length}곳</span>}
        </h2>
        <Link to="/recommend" className="text-sm font-semibold text-ink underline underline-offset-2">
          전체 보기
        </Link>
      </div>
      {loading ? (
        <div className="flex gap-2">
          <Bar className="h-40 w-40" />
          <Bar className="h-40 w-40" />
        </div>
      ) : (
        <ul className="-mx-5 flex snap-x scroll-px-5 gap-2 overflow-x-auto overscroll-x-contain px-5 pb-1 [scrollbar-width:none]">
          {courses.map((course) => {
            const route = routes[course.course_id] ?? [];
            return (
              <li key={course.course_id} className="snap-start">
                <Link to="/recommend" className="pp-press flex h-full w-40 flex-col gap-2 rounded-lg bg-cream p-3 hover:bg-cream-deep">
                  <span className="relative block w-fit">
                    <RouteThumbnail segments={route.length > 1 ? [route] : []} size={56} label={`${course.name} 경로 모양`} />
                    <span className="absolute -top-1 -left-1 flex h-5 w-5 items-center justify-center rounded-full bg-ink font-brand text-[11px] text-white" aria-hidden>
                      {course.rank}
                    </span>
                  </span>
                  <span>
                    <span className="line-clamp-2 text-sm font-semibold leading-snug text-ink">
                      <span className="sr-only">{course.rank}위 </span>
                      {course.name}
                    </span>
                    <span className="mt-1 block text-xs tabular-nums text-ink-soft">
                      {clockRange(course.recommended_time.start, course.recommended_time.end).split('–')[0]} · {course.distance_km.toFixed(1)}km · {course.duration_min}분
                    </span>
                    <span className="mt-0.5 block text-xs font-semibold tabular-nums text-ink">{course.total_score.toFixed(0)}점</span>
                  </span>
                </Link>
              </li>
            );
          })}
          <li className="snap-start">
            <Link
              to="/recommend"
              className="pp-press flex h-full w-24 flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-line text-sm font-semibold text-ink-soft hover:text-ink"
            >
              <ChevronRight size={20} aria-hidden />
              전체 보기
            </Link>
          </li>
        </ul>
      )}
    </section>
  );
}

type SlotKind = 'best' | 'open' | 'rain' | 'excluded';

const KIND_LABEL: Record<SlotKind, string> = {
  best: '추천 시간',
  open: '걸을 수 있음',
  rain: '비 겹침',
  excluded: '날씨로 제외',
};

// 빗금은 그라데이션이 아니라 작은 SVG 무늬로 그린다. 범례는 두지 않고, 막대마다 화면 읽기용 이름에 종류를 적는다.
const hatch = (line: string, ground: string) =>
  `url("data:image/svg+xml,${encodeURIComponent(
    `<svg xmlns='http://www.w3.org/2000/svg' width='6' height='6'><rect width='6' height='6' fill='${ground}'/><path d='M-1 7L7 -1M5 7L7 5M-1 1L1 -1' stroke='${line}' stroke-width='1.2'/></svg>`,
  )}")`;

const KIND_STYLE: Record<SlotKind, CSSProperties> = {
  best: { backgroundColor: 'var(--color-mango-500)' },
  open: { backgroundColor: 'var(--color-cream-deep)' },
  rain: { backgroundImage: hatch('#c4a68c', '#fdf1e4') },
  excluded: { backgroundImage: hatch('#806b5d', '#efdfcf') },
};

function slotKind(slot: Slot, best: Slot | null): SlotKind {
  if (slot.excluded_reason) return 'excluded';
  if (best && slot.start === best.start) return 'best';
  if (slot.rain_overlap_min > 0) return 'rain';
  return 'open';
}

const PLOT_HEIGHT = 112;

/** 가능 시간마다 반려동물 기준 점수를 막대 높이로 그린다. 추천 시간만 색으로 칠하고, 제외된 시간은 낮은 빗금 막대로 둔다. */
function TimeStrip({ slots, best }: { slots: Slot[]; best: Slot | null }) {
  const day = (best ?? slots[0])?.start.slice(0, 10);
  const shown = slots.filter((slot) => slot.start.slice(0, 10) === day);
  const [selected, setSelected] = useState<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);

  // 가능 시간이 길어 막대가 넘치면 카드 안에서만 가로로 밀고, 처음에는 추천 시간이 가운데 오게 한다.
  useEffect(() => {
    const frame = scroller.current;
    const cell = frame?.querySelector<HTMLElement>('[data-best]');
    if (!frame || !cell) return;
    frame.scrollLeft = cell.offsetLeft - (frame.clientWidth - cell.offsetWidth) / 2;
  }, [best?.start]);

  if (shown.length === 0) return <p className="text-sm text-ink-soft">앞으로 24시간 안에 산책 가능 시간이 없어요.</p>;

  const active = shown.find((slot) => slot.start === selected) ?? best ?? shown[0];
  const rainOnset = best?.before_rain ? best.rain_onset : null;

  return (
    <div>
      <div ref={scroller} className="relative -mx-1 overflow-x-auto overscroll-x-contain px-1 pt-1 pb-1">
        <div className="flex items-end gap-1" style={{ height: PLOT_HEIGHT + 40 }} role="group" aria-label="시간대별 산책 점수">
          {shown.map((slot, index) => {
            const kind = slotKind(slot, best);
            const isActive = slot.start === active.start;
            // 점수 0~100을 막대 높이로 그린다. 제외된 시간은 점수 대신 낮은 빗금 막대로 표시한다.
            const height = kind === 'excluded' ? 14 : Math.max(14, (slot.score / 100) * PLOT_HEIGHT);
            return (
              <button
                key={slot.start}
                type="button"
                aria-pressed={isActive}
                aria-label={`${hourPhrase(slot.start)} 출발, ${slot.excluded_reason ? `제외: ${slot.excluded_reason}` : `${slot.score.toFixed(0)}점`}, ${KIND_LABEL[kind]}`}
                onClick={() => setSelected(slot.start)}
                data-best={kind === 'best' ? '' : undefined}
                className="group flex h-full min-w-9 flex-1 flex-col items-center justify-end"
              >
                <span className={`mb-1 text-xs font-semibold tabular-nums ${kind === 'best' || isActive ? 'text-ink' : 'text-ink-muted'}`}>
                  {kind === 'excluded' ? '–' : slot.score.toFixed(0)}
                </span>
                <span
                  className={`pp-bar block w-full max-w-8 rounded-t-[4px] transition-transform group-active:scale-95 ${isActive ? 'outline-2 outline-offset-2 outline-ink' : ''}`}
                  style={{ height, animationDelay: `${index * 20}ms`, ...KIND_STYLE[kind] }}
                />
                <span className={`mt-1.5 text-xs tabular-nums ${isActive ? 'font-semibold text-ink' : 'text-ink-soft'}`}>
                  {new Date(slot.start).getHours()}시
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <SlotStats slot={active} />
      {rainOnset && <p className="mt-2 text-sm text-ink-soft">{hourPhrase(rainOnset)}부터 비 예보가 있어 그 전에 다녀오는 시간을 골랐어요.</p>}
    </div>
  );
}

// 이 값부터는 걷기에 신경 쓸 만하다. 추천 엔진이 감점을 시작하는 지점에 맞췄다(습도는 엔진이 더울 때만 쓰지만 여기서는 늘 70%로 본다).
const METRIC_CAUTION = { rain: 30, humidity: 70, wind: 5, uv: 6 };

/** 시간표에서 고른 시간의 강수·습도·바람·자외선을 칩으로 늘어놓고, 주의할 값만 색으로 칠한다. 체감온도는 위 줄에 적는다. */
function SlotStats({ slot }: { slot: Slot }) {
  const w = slot.weather;
  const metrics = [
    { key: 'rain', label: '강수', value: w.precipitation_probability, text: `${w.precipitation_probability.toFixed(0)}%`, caution: METRIC_CAUTION.rain },
    { key: 'humidity', label: '습도', value: w.humidity, text: `${w.humidity.toFixed(0)}%`, caution: METRIC_CAUTION.humidity },
    { key: 'wind', label: '바람', value: w.wind_speed, text: `${w.wind_speed.toFixed(1)}m/s`, caution: METRIC_CAUTION.wind },
    { key: 'uv', label: '자외선', value: w.uv_index, text: w.uv_index === null ? '–' : w.uv_index.toFixed(0), caution: METRIC_CAUTION.uv },
  ];
  const warnings = metrics.filter((metric) => metric.value !== null && metric.value >= metric.caution);

  return (
    <div className="mt-3" aria-live="polite">
      <p className="text-sm text-ink">
        <span className="font-semibold">{hourPhrase(slot.start)} 출발</span>
        <span className="text-ink-soft">
          {' '}
          · {slot.excluded_reason ? `${slot.excluded_reason}로 제외` : `${slot.score.toFixed(0)}점`} · 체감 {w.apparent_temperature.toFixed(0)}°
          {slot.is_dark ? ' · 해진 뒤' : ''}
        </span>
      </p>
      <ul key={slot.start} className="pp-swap mt-2 flex flex-wrap gap-1.5" aria-label="날씨 지표">
        {metrics.map((metric) => {
          const warn = metric.value !== null && metric.value >= metric.caution;
          return (
            <li
              key={metric.key}
              className={`flex min-h-8 items-center gap-1 rounded-full px-3 text-sm tabular-nums ${warn ? 'bg-[#fffbeb] text-[#92400e]' : 'bg-cream text-ink'}`}
            >
              <span className={warn ? '' : 'text-ink-soft'}>{metric.label}</span>
              <span className="font-semibold">{metric.text}</span>
              {warn && <span className="sr-only">(주의)</span>}
            </li>
          );
        })}
      </ul>
      <p className="mt-2 text-xs text-ink-soft">
        {warnings.length === 0 ? '걷기에 신경 쓸 만한 값은 없어요.' : `${warnings.map((metric) => metric.label).join('·')} 값을 살펴보세요.`}
      </p>
    </div>
  );
}

function PanelHeader({ id, title, action }: { id: string; title: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
      <h2 id={id} className="text-base font-semibold text-ink">
        {title}
      </h2>
      {action}
    </div>
  );
}

function Bar({ className }: { className: string }) {
  return <span className={`block rounded bg-cream-deep ${className}`} aria-hidden />;
}

/** "오후 5시", 정시가 아니면 "오후 5시 30분". */
function hourPhrase(iso: string): string {
  const date = new Date(iso);
  const hours = date.getHours();
  const hour12 = hours % 12 === 0 ? 12 : hours % 12;
  const minutes = date.getMinutes();
  return `${hours < 12 ? '오전' : '오후'} ${hour12}시${minutes ? ` ${minutes}분` : ''}`;
}

function clockRange(startIso: string, endIso: string): string {
  const hm = (iso: string) => {
    const date = new Date(iso);
    return `${date.getHours()}:${String(date.getMinutes()).padStart(2, '0')}`;
  };
  return `${hm(startIso)}–${hm(endIso)}`;
}
