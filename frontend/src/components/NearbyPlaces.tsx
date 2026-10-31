import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import type { NearbyResult } from '../lib/types';

/** 코스 주변 시설 목록. OSM 기록이라 없는 것처럼 보여도 실제로는 있을 수 있음을 함께 알린다. */
export default function NearbyPlaces({ courseId }: { courseId: number }) {
  const [result, setResult] = useState<NearbyResult | null>(null);
  const [failed, setFailed] = useState(false);
  const [filter, setFilter] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setResult(null);
    setFilter(null);
    setFailed(false);
    api
      .nearbyPlaces(courseId, 300)
      .then((data) => active && setResult(data))
      .catch(() => active && setFailed(true));
    return () => {
      active = false;
    };
  }, [courseId]);

  if (failed) return <p className="mt-3 text-xs text-ink-muted">주변 시설을 불러오지 못했어요.</p>;
  if (!result) return null;

  const labels = Array.from(new Set(result.places.map((place) => place.label)));
  const shown = filter ? result.places.filter((place) => place.label === filter) : result.places;

  return (
    <div className="mt-4 border-t border-line pt-3" data-testid="nearby-places">
      <h3 className="text-sm font-bold">코스 주변 시설 ({result.radius_m}m 안)</h3>
      {result.places.length === 0 ? (
        <p className="mt-1 text-sm text-ink-soft">기록된 시설이 없어요.</p>
      ) : (
        <>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {labels.map((label) => (
              <button
                key={label}
                type="button"
                aria-pressed={filter === label}
                onClick={() => setFilter(filter === label ? null : label)}
                className={`min-h-8 rounded-full border px-2.5 text-xs font-semibold ${
                  filter === label ? 'border-ink bg-cream-deep text-ink' : 'border-line text-ink-soft'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <ul className="mt-2 flex max-h-56 flex-col divide-y divide-line overflow-y-auto text-sm">
            {shown.map((place) => (
              <li key={`${place.type}-${place.lat}-${place.lng}`} className="py-1.5">
                <p className="flex items-baseline justify-between gap-2">
                  <span className="min-w-0 truncate font-semibold">{place.name}</span>
                  <span className="shrink-0 text-xs tabular-nums text-ink-muted">경로에서 {place.distance_m}m</span>
                </p>
                <p className="text-xs text-ink-soft">{place.label}</p>
                {place.note && <p className="text-xs text-carrot-700">{place.note}</p>}
              </li>
            ))}
          </ul>
        </>
      )}
      <p className="mt-2 text-xs text-ink-muted">
        출처: {result.source}{result.collected_on ? ` (${result.collected_on} 수집)` : ''}. {result.notice}
      </p>
    </div>
  );
}
