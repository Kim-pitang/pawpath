import { useApp } from '../context/AppContext';
import { SCENARIO_LABELS } from '../lib/labels';
import type { WeatherScenario } from '../lib/types';

// '지금 비'는 산책 중 날씨 변화를 시연할 때만 쓰므로 추천 화면에 두지 않는다.
const SCENARIOS: WeatherScenario[] = ['live', 'rain_later', 'heatwave', 'cold', 'heavy_rain'];

/** 실제 날씨와 시연용 시나리오를 고른다. 시나리오 결과에는 항상 시연용 표시가 붙는다. */
export default function WeatherScenarioPicker() {
  const { scenario, setScenario } = useApp();
  return (
    <div>
      <p className="mb-1.5 text-xs font-semibold text-ink-muted">날씨 조건 (실제 날씨 외에는 시연용이에요)</p>
      <div className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1">
        {SCENARIOS.map((key) => (
          <button
            key={key}
            type="button"
            aria-pressed={scenario === key}
            onClick={() => setScenario(key)}
            className={`min-h-9 shrink-0 rounded-full border px-3.5 text-sm font-semibold transition ${
              scenario === key
                ? key === 'live'
                  ? 'border-leaf-500 bg-leaf-500 text-white'
                  : 'border-carrot-500 bg-carrot-500 text-white'
                : 'border-line bg-white text-ink-soft'
            }`}
          >
            {SCENARIO_LABELS[key]}
          </button>
        ))}
      </div>
    </div>
  );
}
