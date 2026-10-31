import { useState } from 'react';
import type { WalkReport } from '../../lib/types';

type Day = WalkReport['daily'][number];

const PLOT_HEIGHT = 96;

/** 요일별 산책 거리 세로 막대. 눌러서 그날 산책을 확인한다. */
export default function DailyColumns({ days }: { days: Day[] }) {
  const [selected, setSelected] = useState<string | null>(null);
  const max = Math.max(1, ...days.map((day) => day.distance_km));
  const shown = days.find((day) => day.date === selected) ?? [...days].reverse().find((day) => day.walk_count > 0) ?? null;

  return (
    <div>
      <div className="flex items-end gap-1 border-b border-line" style={{ height: PLOT_HEIGHT + 22 }} role="list" aria-label="요일별 산책 거리">
        {days.map((day) => {
          const height = day.walk_count ? Math.max(6, (day.distance_km / max) * PLOT_HEIGHT) : 0;
          return (
            <button
              key={day.date}
              type="button"
              role="listitem"
              aria-label={`${day.weekday}요일 ${day.walk_count}번, ${day.distance_km}km`}
              onClick={() => setSelected(day.date)}
              onPointerEnter={() => setSelected(day.date)}
              className="flex h-full min-w-0 flex-1 flex-col items-center justify-end"
            >
              {day.walk_count > 0 && <span className="mb-0.5 text-[11px] font-semibold tabular-nums text-ink">{day.distance_km.toFixed(1)}</span>}
              <span className={`block w-full max-w-6 rounded-t ${shown?.date === day.date ? 'bg-mango-700' : 'bg-mango-500'}`} style={{ height }} />
            </button>
          );
        })}
      </div>
      <div className="mt-1 flex gap-1">
        {days.map((day) => (
          <span key={day.date} className="min-w-0 flex-1 text-center text-[11px] text-ink-muted">
            {day.weekday}
          </span>
        ))}
      </div>
      <p className="mt-1 text-right text-[11px] text-ink-muted">막대 위 숫자는 km</p>

      {shown && (
        <div className="mt-2 rounded-lg bg-cream px-3 py-2 text-sm" aria-live="polite">
          <p className="font-semibold text-ink">
            {shown.date.slice(5).replace('-', '/')} ({shown.weekday}) · {shown.walk_count}번 · {shown.distance_km.toFixed(1)}km · {shown.minutes}분
          </p>
          <ul className="mt-0.5 text-xs text-ink-soft">
            {shown.walks.map((walk) => (
              <li key={walk.id}>
                {walk.course_name} {walk.distance_km.toFixed(1)}km, {walk.duration_min}분
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
