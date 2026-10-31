import { useState, type PointerEvent } from 'react';
import type { WalkReport } from '../../lib/types';

type Point = WalkReport['satisfaction_trend'][number];

const WIDTH = 360;
const HEIGHT = 140;
const MARGIN = { top: 12, right: 14, bottom: 8, left: 22 };

/** 피드백 순서대로 본 반려동물 만족도(1~5점). */
export default function RatingLine({ points }: { points: Point[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const innerWidth = WIDTH - MARGIN.left - MARGIN.right;
  const innerHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
  const x = (index: number) => MARGIN.left + (points.length === 1 ? innerWidth / 2 : (index / (points.length - 1)) * innerWidth);
  const y = (rating: number) => MARGIN.top + innerHeight - ((rating - 1) / 4) * innerHeight;
  const path = points.map((point, index) => `${index ? 'L' : 'M'}${x(index).toFixed(1)} ${y(point.pet_rating).toFixed(1)}`).join('');
  const active = hover ?? points.length - 1;

  const onMove = (event: PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = (((event.clientX - rect.left) / rect.width) * WIDTH - MARGIN.left) / innerWidth;
    setHover(Math.max(0, Math.min(points.length - 1, Math.round(ratio * (points.length - 1)))));
  };

  return (
    <div>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="w-full touch-pan-y"
        role="img"
        aria-label="반려동물 만족도 변화"
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
      >
        {[1, 3, 5].map((tick) => (
          <g key={tick}>
            <line x1={MARGIN.left} x2={WIDTH - MARGIN.right} y1={y(tick)} y2={y(tick)} stroke="var(--color-line)" />
            <text x={MARGIN.left - 6} y={y(tick) + 3} textAnchor="end" fontSize="10" fill="var(--color-ink-muted)">
              {tick}
            </text>
          </g>
        ))}
        <path d={path} fill="none" stroke="#2e8b62" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx={x(active)} cy={y(points[active].pet_rating)} r="4.5" fill="#2e8b62" stroke="#fff" strokeWidth="2" />
      </svg>
      <p className="mt-1 text-xs text-ink-soft" aria-live="polite">
        {points[active].date.slice(5).replace('-', '/')} {points[active].course_name} · 만족도 {points[active].pet_rating}점
      </p>
      <details className="mt-1 text-xs text-ink-soft">
        <summary className="cursor-pointer font-semibold">표로 보기</summary>
        <ul className="mt-1 tabular-nums">
          {points.map((point) => (
            <li key={point.feedback_id}>
              {point.date.slice(5).replace('-', '/')} {point.course_name}: {point.pet_rating}점
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
