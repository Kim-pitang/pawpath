import { Database } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { SCENARIO_LABELS, WEATHER_SOURCE_LABELS } from '../lib/labels';
import type { WeatherMeta, WeatherScenario } from '../lib/types';

/**
 * 날씨 데이터 출처 태그. 시연용 시나리오면 "시연용 곧 비", 모의 날씨면 "모의 날씨"로 노랗게,
 * 실제 예보면 "실시간 예보"로 회색으로 둔다. 누르면 출처와 안내를 보여 준다.
 */
export default function WeatherSourceTag({ weather, changeLink = false }: { weather: WeatherMeta; changeLink?: boolean }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  const scenario = weather.scenario as WeatherScenario;
  const demo = scenario !== 'live';
  const warn = demo || weather.is_mock;
  const name = demo ? `시연용 ${SCENARIO_LABELS[scenario] ?? ''}`.trim() : weather.is_mock ? '모의 날씨' : '실시간 예보';
  const source = WEATHER_SOURCE_LABELS[weather.source] ?? '시연용 시나리오';

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => ref.current && !ref.current.contains(event.target as Node) && setOpen(false);
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && setOpen(false);
    document.addEventListener('pointerdown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <span ref={ref} className="relative ml-2 inline-block align-middle">
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((value) => !value)}
        className={`inline-flex min-h-6 items-center gap-1 rounded px-1.5 text-xs font-semibold ${warn ? 'bg-[#fffbeb] text-[#92400e]' : 'bg-cream-deep text-ink-soft'}`}
      >
        <Database size={11} aria-hidden />
        {name}
      </button>
      {open && (
        <span
          role="dialog"
          aria-label="날씨 데이터 안내"
          className="pp-pop absolute top-full left-0 z-20 mt-1.5 block w-64 origin-top-left rounded-lg border border-line bg-white p-3 text-left text-sm font-normal text-ink shadow-[0_8px_24px_rgb(66_45_33/0.14)]"
        >
          <span className="block font-semibold">출처: {source}</span>
          <span className="mt-1 block text-ink-soft">{weather.notice ?? '시간별 예보로 점수를 계산했어요. 실시간 강수 감지는 아니에요.'}</span>
          {changeLink && (
            <Link to="/recommend" className="mt-2 inline-block font-semibold underline underline-offset-2">
              날씨 조건 바꾸기
            </Link>
          )}
        </span>
      )}
    </span>
  );
}
