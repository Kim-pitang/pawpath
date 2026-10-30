import { useMemo, useState, type PointerEvent } from 'react';
import { dateTimeLabel } from '../../lib/format';
import type { Insights } from '../../lib/types';

type History = Insights['recommendation_history'];

const SERIES_COLORS = ['#2e8b62', '#d9661a', '#3f7cc4', '#a0569e'];
const WIDTH = 360;
const HEIGHT = 180;
const MARGIN = { top: 12, right: 12, bottom: 24, left: 30 };
const MAX_SERIES = 4;

interface Series {
  courseId: number;
  name: string;
  color: string;
  points: (number | null)[];
}

function buildSeries(history: History): Series[] {
  // 색은 순위가 아니라 코스에 붙는다. 처음 등장한 순서로 고정한다.
  const order: { id: number; name: string }[] = [];
  for (const record of history) {
    for (const course of record.courses) {
      if (!order.some((entry) => entry.id === course.course_id)) {
        order.push({ id: course.course_id, name: course.name });
      }
    }
  }
  const latestIds = new Set(history[history.length - 1].courses.map((course) => course.course_id));
  const prioritized = [...order].sort((a, b) => Number(latestIds.has(b.id)) - Number(latestIds.has(a.id)));
  const shown = new Set(prioritized.slice(0, MAX_SERIES).map((entry) => entry.id));

  return order
    .filter((entry) => shown.has(entry.id))
    .map((entry, index) => ({
      courseId: entry.id,
      name: entry.name,
      color: SERIES_COLORS[index],
      points: history.map(
        (record) => record.courses.find((course) => course.course_id === entry.id)?.total_score ?? null,
      ),
    }));
}

function linePath(points: (number | null)[], x: (index: number) => number, y: (value: number) => number): string {
  let path = '';
  let drawing = false;
  points.forEach((value, index) => {
    if (value === null) {
      drawing = false;
      return;
    }
    path += `${drawing ? 'L' : 'M'}${x(index).toFixed(1)} ${y(value).toFixed(1)}`;
    drawing = true;
  });
  return path;
}

/** 같은 날씨 조건에서 받은 추천의 코스별 점수 변화. */
export default function ScoreTrendChart({ history }: { history: History }) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const series = useMemo(() => buildSeries(history), [history]);

  const values = series.flatMap((item) => item.points).filter((value): value is number => value !== null);
  const low = Math.max(0, Math.floor((Math.min(...values) - 2) / 10) * 10);
  const high = Math.min(100, Math.ceil((Math.max(...values) + 2) / 10) * 10);
  const innerWidth = WIDTH - MARGIN.left - MARGIN.right;
  const innerHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
  const x = (index: number) => MARGIN.left + (history.length === 1 ? innerWidth / 2 : (index / (history.length - 1)) * innerWidth);
  const y = (value: number) => MARGIN.top + innerHeight - ((value - low) / (high - low || 1)) * innerHeight;
  const ticks = [low, Math.round((low + high) / 2), high];

  const onPointerMove = (event: PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const position = ((event.clientX - rect.left) / rect.width) * WIDTH;
    const ratio = (position - MARGIN.left) / innerWidth;
    setHoverIndex(Math.max(0, Math.min(history.length - 1, Math.round(ratio * (history.length - 1)))));
  };

  const active = hoverIndex ?? history.length - 1;

  return (
    <div>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="w-full touch-pan-y"
        role="img"
        aria-label="추천 회차별 코스 점수 변화"
        onPointerMove={onPointerMove}
        onPointerLeave={() => setHoverIndex(null)}
      >
        {ticks.map((tick) => (
          <g key={tick}>
            <line x1={MARGIN.left} x2={WIDTH - MARGIN.right} y1={y(tick)} y2={y(tick)} stroke="var(--color-line)" />
            <text x={MARGIN.left - 6} y={y(tick) + 3} textAnchor="end" fontSize="10" fill="var(--color-ink-muted)">
              {tick}
            </text>
          </g>
        ))}
        {history.map((record, index) => (
          <text key={record.id} x={x(index)} y={HEIGHT - 8} textAnchor="middle" fontSize="10" fill="var(--color-ink-muted)">
            {history.length <= 8 ? `${index + 1}회` : ''}
          </text>
        ))}
        {hoverIndex !== null && (
          <line x1={x(active)} x2={x(active)} y1={MARGIN.top} y2={HEIGHT - MARGIN.bottom} stroke="var(--color-ink-muted)" strokeWidth="1" />
        )}
        {series.map((item) => (
          <g key={item.courseId}>
            <path d={linePath(item.points, x, y)} fill="none" stroke={item.color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            {item.points.map((value, index) =>
              value !== null && (index === active || item.points.filter((p) => p !== null).length === 1) ? (
                <circle key={index} cx={x(index)} cy={y(value)} r="4.5" fill={item.color} stroke="#fff" strokeWidth="2" />
              ) : null,
            )}
          </g>
        ))}
      </svg>

      <ul className="mt-2 flex flex-col gap-1 text-xs" aria-label="범례">
        {series.map((item) => {
          const value = item.points[active];
          return (
            <li key={item.courseId} className="flex items-center justify-between gap-2">
              <span className="flex min-w-0 items-center gap-1.5 text-ink-soft">
                <span className="h-0.5 w-3.5 shrink-0 rounded" style={{ background: item.color }} aria-hidden />
                <span className="truncate">{item.name}</span>
              </span>
              <span className="shrink-0 font-semibold tabular-nums text-ink">
                {value === null ? '순위 밖' : `${value.toFixed(1)}점`}
              </span>
            </li>
          );
        })}
      </ul>
      <p className="mt-1 text-xs text-ink-muted">
        {active + 1}회차 · {dateTimeLabel(history[active].created_at)} · 피드백 {history[active].feedback_total}건 반영
      </p>

      <details className="mt-2 text-xs text-ink-soft">
        <summary className="cursor-pointer font-semibold">표로 보기</summary>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-left tabular-nums">
            <thead>
              <tr className="text-ink-muted">
                <th className="py-1 pr-2 font-medium">회차</th>
                <th className="py-1 pr-2 font-medium">1위</th>
                <th className="py-1 pr-2 font-medium">2위</th>
                <th className="py-1 font-medium">3위</th>
              </tr>
            </thead>
            <tbody>
              {history.map((record, index) => (
                <tr key={record.id} className="border-t border-line">
                  <td className="py-1 pr-2">{index + 1}</td>
                  {record.courses.map((course) => (
                    <td key={course.course_id} className="py-1 pr-2">
                      {course.name} {course.total_score.toFixed(1)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
