import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { useApp } from '../context/AppContext';
import { SCENARIO_LABELS } from '../lib/labels';
import type { WeatherScenario } from '../lib/types';

// '지금 비'는 산책 중 날씨 변화를 시연할 때만 쓰므로 추천 화면에 두지 않는다.
const SCENARIOS: WeatherScenario[] = ['live', 'rain_later', 'heatwave', 'cold', 'heavy_rain'];

/**
 * 실제 날씨와 시연용 시나리오를 한 줄 분할 버튼으로 고른다. 고른 칸으로 흰 바탕이 미끄러지고,
 * 실제 날씨와 시연용 조건 사이에는 틈을 둔다. 시나리오 결과에는 항상 시연용 표시가 붙는다.
 */
export default function WeatherScenarioPicker({ status }: { status?: ReactNode }) {
  const { scenario, setScenario } = useApp();
  const items = useRef<Partial<Record<WeatherScenario, HTMLButtonElement | null>>>({});
  const [box, setBox] = useState({ left: 0, width: 0 });

  useLayoutEffect(() => {
    const element = items.current[scenario];
    if (element) setBox({ left: element.offsetLeft, width: element.offsetWidth });
  }, [scenario]);

  return (
    <div>
      <p className="text-sm font-semibold text-ink">
        날씨 조건
        {status}
      </p>
      <div className="relative mt-2 flex rounded-lg bg-cream-deep p-1" role="group" aria-label="날씨 조건">
        <span
          className="pp-slide absolute top-1 bottom-1 left-0 rounded-md bg-white shadow-[0_1px_2px_rgb(66_45_33/0.12)]"
          style={{ transform: `translateX(${box.left}px)`, width: box.width }}
          aria-hidden
        />
        {SCENARIOS.map((key) => (
          <button
            key={key}
            ref={(element) => {
              items.current[key] = element;
            }}
            type="button"
            aria-pressed={scenario === key}
            onClick={() => setScenario(key)}
            className={`relative min-h-10 flex-1 rounded-md text-sm font-semibold whitespace-nowrap transition-colors ${key === 'live' ? 'mr-1.5' : ''} ${
              scenario === key ? 'text-ink' : 'text-ink-soft hover:text-ink'
            }`}
          >
            {SCENARIO_LABELS[key]}
          </button>
        ))}
      </div>
      <p className="mt-2 text-xs text-ink-soft">실제 날씨 외에는 시연용이에요.</p>
    </div>
  );
}
