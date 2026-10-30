import { useState } from 'react';
import { dayLabel, hourLabel } from '../../lib/format';
import type { Slot } from '../../lib/types';

const PLOT_HEIGHT = 112;

function slotState(slot: Slot, bestStarts: Set<string>) {
  if (slot.excluded_reason) return 'excluded';
  return bestStarts.has(slot.start) ? 'best' : 'available';
}

const COLUMN_COLOR = {
  best: 'bg-carrot-500',
  available: 'bg-leaf-300',
  excluded: 'bg-line',
};

/** 가능 시간대별 점수 세로 막대. 추천 시간은 강조색으로, 제외 시간은 회색으로 그린다. */
export default function SlotColumns({ slots, bestSlots }: { slots: Slot[]; bestSlots: Slot[] }) {
  const [active, setActive] = useState<Slot | null>(null);
  const bestStarts = new Set(bestSlots.map((slot) => slot.start));
  const shown = active ?? bestSlots[0] ?? slots[0];

  return (
    <div>
      <div className="flex items-end gap-0.5" style={{ height: PLOT_HEIGHT + 24 }} role="list" aria-label="시간대별 산책 점수">
        {slots.map((slot) => {
          const state = slotState(slot, bestStarts);
          const height = state === 'excluded' ? 6 : Math.max(6, (slot.score / 100) * PLOT_HEIGHT);
          return (
            <button
              key={slot.start}
              type="button"
              role="listitem"
              onPointerEnter={() => setActive(slot)}
              onPointerLeave={() => setActive(null)}
              onFocus={() => setActive(slot)}
              onBlur={() => setActive(null)}
              onClick={() => setActive(slot)}
              aria-label={`${dayLabel(slot.start)} ${hourLabel(slot.start)} ${slot.excluded_reason ? `제외: ${slot.excluded_reason}` : `${slot.score.toFixed(0)}점`}`}
              className="flex h-full min-w-0 flex-1 flex-col items-center justify-end"
            >
              {state === 'best' && (
                <span className="mb-0.5 text-xs font-bold tabular-nums text-ink">{slot.score.toFixed(0)}</span>
              )}
              <span className={`block w-full max-w-6 rounded-t ${COLUMN_COLOR[state]}`} style={{ height }} />
              <span className="mt-1 text-[11px] tabular-nums text-ink-muted">{new Date(slot.start).getHours()}</span>
            </button>
          );
        })}
      </div>

      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-soft">
        <LegendSwatch className="bg-carrot-500" label="추천 시간" />
        <LegendSwatch className="bg-leaf-300" label="가능 시간" />
        <LegendSwatch className="bg-line" label="날씨로 제외" />
      </div>

      {shown && (
        <p className="mt-2 rounded-2xl bg-cream px-3 py-2 text-xs text-ink-soft" aria-live="polite">
          <strong className="font-semibold text-ink">
            {dayLabel(shown.start)} {hourLabel(shown.start)}
          </strong>{' '}
          {shown.excluded_reason ? `제외: ${shown.excluded_reason}` : `${shown.score.toFixed(0)}점`} · 체감{' '}
          {shown.weather.apparent_temperature.toFixed(0)}°C · 강수 {shown.weather.precipitation_probability.toFixed(0)}% · 바람{' '}
          {shown.weather.wind_speed.toFixed(1)}m/s
        </p>
      )}
    </div>
  );
}

function LegendSwatch({ className, label }: { className: string; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className={`h-2.5 w-2.5 rounded-sm ${className}`} aria-hidden />
      {label}
    </span>
  );
}
