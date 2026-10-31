import { ChevronRight, Footprints, RotateCw } from 'lucide-react';
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { EmptyState, ErrorNotice, InfoNotice, LinkButton } from '../components/ui';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import { dayLabel, windowLabel } from '../lib/format';
import { PERSONALITY_LABELS, WEATHER_SOURCE_LABELS } from '../lib/labels';
import type { CurrentWeather, Pet, Recommendation, RecommendedCourse, Slot } from '../lib/types';

// 홈은 "오늘 언제, 어디로 걸을까"에 먼저 답한다. 멍고 오렌지는 추천 시간과 산책 버튼에만 쓴다.
const PANEL = 'rounded-lg border border-line bg-white p-5';

export default function HomePage() {
  const { petsLoaded, loadError, selectedPet, schedule, scenario, loadRecommendation, cachedRecommendation } = useApp();
  const [weather, setWeather] = useState<CurrentWeather | null>(null);
  const [weatherError, setWeatherError] = useState<string | null>(null);
  const [recommendError, setRecommendError] = useState<string | null>(null);
  const petId = selectedPet?.id;

  useEffect(() => {
    if (!petsLoaded) return;
    let active = true;
    api
      .currentWeather(scenario, petId)
      .then((result) => {
        if (!active) return;
        setWeather(result);
        setWeatherError(null);
      })
      .catch((error: Error) => active && setWeatherError(error.message));
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
              title={bestSlot ? `${dayLabel(bestSlot.start)} 산책 시간표` : '산책 시간표'}
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
          <WeatherPanel weather={weather} error={weatherError} />
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
  return (
    <section className={PANEL} aria-labelledby="answer-title">
      <h2 id="answer-title" className="text-lg font-bold leading-snug text-ink">
        {top.name}
      </h2>
      <p className="mt-1 text-sm tabular-nums text-ink-soft">
        {clockRange(slot.start, slot.end)} · {top.distance_km.toFixed(2)}km · {top.duration_min}분 · 추천 점수 {top.total_score.toFixed(0)}
      </p>
      <p className="mt-3 text-base leading-relaxed text-ink" data-testid="home-reason">
        {top.reason.llm_summary ?? top.reason.summary}
      </p>
      <div className="mt-5 grid grid-cols-[1fr_auto] gap-2">
        <Link
          to={`/navigate?course=${top.course_id}&recommendation=${recommendation.id}`}
          className="inline-flex min-h-12 items-center justify-center gap-2 rounded-md bg-mango-500 px-5 text-sm font-bold text-ink transition-[background-color,transform] hover:bg-mango-600 active:scale-[0.98]"
        >
          <Footprints size={16} aria-hidden />
          이 코스로 산책
        </Link>
        <Link
          to="/recommend"
          className="inline-flex min-h-12 items-center justify-center rounded-md bg-cream-deep px-4 text-sm font-semibold text-ink transition-[background-color,transform] hover:bg-peach-deep active:scale-[0.98]"
        >
          추천 자세히
        </Link>
      </div>
    </section>
  );
}

function OtherCourses({ courses, loading }: { courses: RecommendedCourse[]; loading: boolean }) {
  if (!loading && courses.length === 0) return null;
  return (
    <section className={PANEL} aria-labelledby="others-title">
      <PanelHeader
        id="others-title"
        title="다른 코스"
        action={
          <Link to="/recommend" className="text-sm font-semibold text-ink underline underline-offset-2">
            전체 보기
          </Link>
        }
      />
      {loading ? (
        <>
          <Bar className="h-10 w-full" />
          <Bar className="mt-3 h-10 w-full" />
        </>
      ) : (
        <ul className="-my-1">
          {courses.map((course) => (
            <li key={course.course_id}>
              <Link to="/recommend" className="group -mx-2 flex min-h-14 items-center gap-3 rounded-md px-2 py-2 hover:bg-cream">
                <span className="w-4 shrink-0 text-sm tabular-nums text-ink-soft">{course.rank}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-base font-semibold text-ink">{course.name}</span>
                  <span className="block text-sm tabular-nums text-ink-soft">
                    {clockRange(course.recommended_time.start, course.recommended_time.end)} · {course.distance_km.toFixed(2)}km · {course.duration_min}분
                  </span>
                </span>
                <span className="shrink-0 text-right text-base tabular-nums text-ink">
                  {course.total_score.toFixed(0)}
                  <span className="text-sm text-ink-soft">점</span>
                </span>
                <ChevronRight size={16} className="shrink-0 text-ink-muted group-hover:text-ink" aria-hidden />
              </Link>
            </li>
          ))}
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
      <div ref={scroller} className="relative -mx-1 overflow-x-auto px-1 pt-1 pb-1">
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

/** 시간표에서 고른 시간의 날씨를 네 칸(체감·강수·바람·자외선)으로 나눠 보여 준다. */
function SlotStats({ slot }: { slot: Slot }) {
  const w = slot.weather;
  const cells = [
    { label: '체감', value: `${w.apparent_temperature.toFixed(0)}°` },
    { label: '강수', value: `${w.precipitation_probability.toFixed(0)}%` },
    { label: '바람', value: w.wind_speed.toFixed(1), unit: 'm/s' },
    { label: '자외선', value: w.uv_index === null ? '–' : w.uv_index.toFixed(0) },
  ];
  return (
    <div className="mt-3" aria-live="polite">
      <p className="text-sm text-ink">
        <span className="font-semibold">{hourPhrase(slot.start)} 출발</span>
        <span className="text-ink-soft">
          {' '}
          · {slot.excluded_reason ? `${slot.excluded_reason}로 제외` : `${slot.score.toFixed(0)}점`}
          {slot.is_dark ? ' · 해진 뒤' : ''}
        </span>
      </p>
      <dl key={slot.start} className="pp-swap mt-2 grid grid-cols-4 divide-x divide-line rounded-md bg-cream py-2.5">
        {cells.map((cell) => (
          <div key={cell.label} className="min-w-0 px-3">
            <dt className="text-xs text-ink-soft">{cell.label}</dt>
            <dd className="mt-0.5 truncate text-base font-semibold tabular-nums text-ink">
              {cell.value}
              {cell.unit && <span className="ml-0.5 text-xs font-normal text-ink-soft">{cell.unit}</span>}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function WeatherPanel({ weather, error }: { weather: CurrentWeather | null; error: string | null }) {
  return (
    <section className={PANEL} aria-labelledby="weather-title">
      <PanelHeader
        id="weather-title"
        title="지금 날씨"
        action={weather && <span className="text-xs text-ink-soft">출처: {WEATHER_SOURCE_LABELS[weather.source] ?? '시연용 시나리오'}</span>}
      />
      {error && <ErrorNotice message={error} />}
      {!weather && !error && <Bar className="h-16 w-full" />}
      {weather && (
        <>
          <div className="flex items-baseline gap-3">
            <p className="text-3xl font-semibold tabular-nums leading-none text-ink">{weather.current.temperature.toFixed(0)}°</p>
            <p className="text-sm text-ink-soft">
              체감 {weather.current.apparent_temperature.toFixed(0)}° · {weather.condition}
            </p>
          </div>
          <p className="mt-2 text-sm text-ink">{weather.walk_comfort_hint}</p>
          <dl className="mt-4 grid grid-cols-4 divide-x divide-line border-y border-line py-2.5">
            <Stat label="강수" value={`${weather.current.precipitation_probability.toFixed(0)}%`} />
            <Stat label="습도" value={`${weather.current.humidity.toFixed(0)}%`} />
            <Stat label="바람" value={`${weather.current.wind_speed.toFixed(1)}m/s`} />
            <Stat label="자외선" value={weather.current.uv_index?.toFixed(0) ?? '–'} />
          </dl>
          {weather.notice && (
            <div className="mt-3">
              <InfoNotice>{weather.notice}</InfoNotice>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="px-2 first:pl-0">
      <dt className="text-xs text-ink-soft">{label}</dt>
      <dd className="mt-0.5 text-sm font-semibold tabular-nums text-ink">{value}</dd>
    </div>
  );
}

function PanelHeader({ id, title, action }: { id: string; title: string; action?: ReactNode }) {
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
