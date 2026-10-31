import { signed } from '../../lib/format';

export interface DivergingItem {
  key: string;
  label: string;
  value: number;
}

/** 0을 중심으로 좋아함(그린, +)과 덜 좋아함(오렌지, −)을 나눠 그린다. 부호로도 구분한다. */
export default function DivergingBars({ items, ariaLabel }: { items: DivergingItem[]; ariaLabel: string }) {
  const max = Math.max(5, ...items.map((item) => Math.abs(item.value)));
  return (
    <ul className="flex flex-col gap-1.5" aria-label={ariaLabel}>
      {items.map((item) => {
        const share = (Math.abs(item.value) / max) * 50;
        return (
          <li key={item.key} className="grid min-h-6 grid-cols-[4.5rem_1fr_3rem] items-center gap-2 text-sm">
            <span className="truncate text-ink-soft">{item.label}</span>
            <div className="relative h-3">
              <div className="absolute inset-y-[-3px] left-1/2 w-px bg-ink-muted/50" aria-hidden />
              <div
                className={`absolute top-0 h-full ${item.value >= 0 ? 'rounded-r bg-mango-500' : 'rounded-l bg-ink-muted'}`}
                style={item.value >= 0 ? { left: '50%', width: `${share}%` } : { right: '50%', width: `${share}%` }}
              />
            </div>
            <span className="text-right font-semibold tabular-nums text-ink">{signed(item.value)}</span>
          </li>
        );
      })}
    </ul>
  );
}
