export interface HBarItem {
  key: string | number;
  label: string;
  value: number;
  /** 값 옆에 덧붙이는 짧은 설명. */
  note?: string;
  /** 표본이 없어 중립값인 항목은 연하게 그린다. */
  muted?: boolean;
}

/**
 * 0~100점 단일 계열 가로 막대. 값은 막대 끝에 직접 표시하고, 50점 중립선을 함께 그린다.
 */
export default function HBarChart({ items, ariaLabel }: { items: HBarItem[]; ariaLabel: string }) {
  return (
    <ul className="flex flex-col gap-2.5" aria-label={ariaLabel}>
      {items.map((item) => (
        <li key={item.key} className="min-h-6">
          <div className="mb-1 flex items-baseline justify-between gap-2 text-sm">
            <span className="truncate text-ink-soft">{item.label}</span>
            <span className="shrink-0 font-semibold tabular-nums text-ink">
              {item.value.toFixed(0)}점{item.note && <span className="ml-1 font-normal text-ink-muted">{item.note}</span>}
            </span>
          </div>
          <div className="relative h-2.5 rounded-full bg-cream-deep">
            <div
              className={`h-full rounded-r ${item.muted ? 'bg-cream-deep' : 'bg-mango-500'}`}
              style={{ width: `${Math.max(1, Math.min(100, item.value))}%` }}
            />
            <div className="absolute inset-y-[-2px] left-1/2 w-px bg-ink-muted/50" aria-hidden />
          </div>
        </li>
      ))}
    </ul>
  );
}
