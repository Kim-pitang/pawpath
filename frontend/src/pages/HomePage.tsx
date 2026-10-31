import { CalendarClock, ChevronRight, Droplets, PawPrint, Sparkles, Sun, Thermometer, Wind } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { PawPathMark } from '../components/Logo';
import { Card, Chip, EmptyState, ErrorNotice, InfoNotice, LinkButton, SectionTitle } from '../components/ui';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import { slotRange, windowLabel } from '../lib/format';
import { ACTIVITY_LABELS, PATH_LABELS, PERSONALITY_LABELS, SIZE_LABELS, WEATHER_SOURCE_LABELS } from '../lib/labels';
import type { CurrentWeather, Recommendation } from '../lib/types';

export default function HomePage() {
  const { pets, petsLoaded, loadError, selectedPet, selectPet, schedule, scenario, cachedRecommendation } = useApp();
  const [weather, setWeather] = useState<CurrentWeather | null>(null);
  const [weatherError, setWeatherError] = useState<string | null>(null);
  const [latest, setLatest] = useState<Recommendation | null>(null);
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

  useEffect(() => {
    if (!petId) return;
    let active = true;
    api
      .latestRecommendations(petId)
      .then((list) => active && setLatest(list[0] ?? null))
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [petId]);

  const recommendation = cachedRecommendation ?? latest;
  const topCourse = recommendation?.courses[0];

  return (
    <div className="flex flex-col gap-4 md:grid md:grid-cols-2 md:items-start">
      <section className="relative overflow-hidden rounded-3xl bg-leaf-500 p-6 text-white md:col-span-2">
        <PawPrint className="absolute -right-3 -bottom-4 text-white/10" size={132} aria-hidden />
        <div className="relative flex items-center gap-3">
          <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-cream">
            <PawPathMark className="h-11 w-11" />
          </span>
          <div>
            <h1 className="font-brand text-3xl leading-none">PawPath</h1>
            <p className="mt-1 font-brand text-lg leading-none text-carrot-100">댕댕 산책각</p>
          </div>
        </div>
        <p className="relative mt-4 text-lg font-bold">Every Paw Deserves a Perfect Path.</p>
        <p className="relative mt-1 text-xs text-leaf-100">AI-Powered Personalized Pet Walking Recommendation</p>
        <p className="relative mt-3 text-sm leading-relaxed text-white/90">
          우리 아이의 성향과 보호자의 일정, 날씨와 동네 환경을 함께 살펴 오늘 가장 좋은 산책 시간과 코스를 골라 드려요.
        </p>
      </section>

      {loadError && <ErrorNotice message={loadError} />}

      <Card>
        <SectionTitle action={<Link to="/pets" className="text-xs font-semibold text-leaf-600">관리</Link>}>우리 아이</SectionTitle>
        {selectedPet ? (
          <>
            {pets.length > 1 && (
              <div className="mb-3 flex flex-wrap gap-1.5">
                {pets.map((pet) => (
                  <button
                    key={pet.id}
                    type="button"
                    aria-pressed={pet.id === selectedPet.id}
                    onClick={() => selectPet(pet.id)}
                    className={`min-h-9 rounded-full border px-3 text-sm font-semibold ${
                      pet.id === selectedPet.id ? 'border-leaf-500 bg-leaf-50 text-leaf-800' : 'border-line text-ink-soft'
                    }`}
                  >
                    {pet.name}
                  </button>
                ))}
              </div>
            )}
            <div className="flex items-center gap-3">
              <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-carrot-50 text-carrot-500">
                <PawPrint size={28} aria-hidden />
              </span>
              <div>
                <p className="text-lg font-bold">{selectedPet.name}</p>
                <p className="text-sm text-ink-soft">
                  {selectedPet.breed} · {selectedPet.age_years}세 · {selectedPet.weight_kg}kg
                </p>
              </div>
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              <Chip tone="leaf">{SIZE_LABELS[selectedPet.size]}</Chip>
              <Chip tone="leaf">활동량 {ACTIVITY_LABELS[selectedPet.activity_level]}</Chip>
              <Chip tone="carrot">{PERSONALITY_LABELS[selectedPet.personality]}</Chip>
              <Chip tone="carrot">{PATH_LABELS[selectedPet.path_preference]}</Chip>
            </div>
          </>
        ) : (
          petsLoaded && (
            <EmptyState title="아직 등록된 반려동물이 없어요">
              <LinkButton to="/pets/new">반려동물 등록하기</LinkButton>
            </EmptyState>
          )
        )}
      </Card>

      <Card>
        <SectionTitle>지금 날씨</SectionTitle>
        {weatherError && <ErrorNotice message={weatherError} />}
        {weather && (
          <>
            <div className="flex items-end justify-between gap-2">
              <div>
                <p className="text-4xl font-bold leading-none">{weather.current.temperature.toFixed(0)}°</p>
                <p className="mt-1 text-sm text-ink-soft">
                  체감 {weather.current.apparent_temperature.toFixed(0)}° · {weather.condition}
                </p>
              </div>
              <p className="max-w-[55%] text-right text-sm font-semibold text-leaf-800">{weather.walk_comfort_hint}</p>
            </div>
            <dl className="mt-3 grid grid-cols-4 gap-1 text-center">
              <WeatherStat icon={<Droplets size={16} />} label="강수" value={`${weather.current.precipitation_probability.toFixed(0)}%`} />
              <WeatherStat icon={<Thermometer size={16} />} label="습도" value={`${weather.current.humidity.toFixed(0)}%`} />
              <WeatherStat icon={<Wind size={16} />} label="바람" value={`${weather.current.wind_speed.toFixed(1)}m/s`} />
              <WeatherStat icon={<Sun size={16} />} label="자외선" value={weather.current.uv_index?.toFixed(0) ?? '정보 없음'} />
            </dl>
            <p className="mt-3 text-xs text-ink-muted">출처: {WEATHER_SOURCE_LABELS[weather.source] ?? '시연용 시나리오'}</p>
            {weather.notice && (
              <div className="mt-2">
                <InfoNotice>{weather.notice}</InfoNotice>
              </div>
            )}
          </>
        )}
      </Card>

      <Card>
        <SectionTitle action={<Link to="/schedule" className="text-xs font-semibold text-leaf-600">변경</Link>}>산책 가능 시간</SectionTitle>
        {schedule && (
          <div className="flex items-start gap-3">
            <CalendarClock className="mt-0.5 shrink-0 text-carrot-500" size={22} aria-hidden />
            <div>
              <p className="font-semibold">
                {schedule.available_windows.map((window) => windowLabel(window.start_hour, window.end_hour)).join(', ')}
              </p>
              <p className="text-sm text-ink-soft">
                한 번에 {schedule.preferred_duration_min}분 · 하루 {schedule.walks_per_day}번
              </p>
            </div>
          </div>
        )}
      </Card>

      <Card className="border-carrot-100 bg-carrot-50">
        <SectionTitle>오늘의 산책 추천</SectionTitle>
        {topCourse ? (
          <Link to="/recommend" className="mb-3 block rounded-2xl bg-white p-3">
            <span className="flex items-center justify-between gap-2">
              <span className="font-bold">{topCourse.name}</span>
              <ChevronRight size={18} className="shrink-0 text-ink-muted" aria-hidden />
            </span>
            <span className="mt-0.5 block text-xs text-ink-soft">
              {slotRange(topCourse.recommended_time.start, topCourse.recommended_time.end)} · {topCourse.total_score.toFixed(0)}점
            </span>
            <span className="mt-1.5 block text-sm text-ink">{topCourse.reason.llm_summary ?? topCourse.reason.summary}</span>
          </Link>
        ) : (
          <p className="mb-3 text-sm text-ink-soft">성향과 날씨를 분석해 오늘 가장 좋은 코스 3곳을 골라 드려요.</p>
        )}
        <LinkButton to="/recommend" variant="accent" className="w-full">
          <Sparkles size={18} aria-hidden />
          추천 시작
        </LinkButton>
      </Card>
    </div>
  );
}

function WeatherStat({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="rounded-2xl bg-cream px-1 py-2">
      <dt className="flex items-center justify-center gap-0.5 text-[11px] text-ink-muted">
        <span aria-hidden>{icon}</span>
        {label}
      </dt>
      <dd className="mt-0.5 text-xs font-semibold">{value}</dd>
    </div>
  );
}
