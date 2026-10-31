/** 목록용 경로 그림. 지도 타일을 받지 않아 카드가 많아도 가볍다. 목록은 72px, 추천 카드는 더 크게 쓴다. */
export default function RouteThumbnail({ segments, label, size = 72 }: { segments: number[][][]; label: string; size?: number }) {
  const SIZE = size;
  const PADDING = size / 9;
  const STROKE = Math.max(2.5, size / 32);
  const DOT = Math.max(3.5, size / 24);
  const points = segments.flat();
  if (points.length === 0) return <div style={{ width: SIZE, height: SIZE }} className="shrink-0 rounded-lg bg-cream-deep" />;

  const lats = points.map((point) => point[0]);
  const lngs = points.map((point) => point[1]);
  const midLat = (Math.min(...lats) + Math.max(...lats)) / 2;
  const scaleX = Math.cos((midLat * Math.PI) / 180);
  const width = (Math.max(...lngs) - Math.min(...lngs)) * scaleX;
  const height = Math.max(...lats) - Math.min(...lats);
  const scale = (SIZE - PADDING * 2) / Math.max(width, height, 1e-6);
  const offsetX = (SIZE - width * scale) / 2;
  const offsetY = (SIZE - height * scale) / 2;
  const project = ([lat, lng]: number[]) =>
    [offsetX + (lng - Math.min(...lngs)) * scaleX * scale, SIZE - offsetY - (lat - Math.min(...lats)) * scale] as const;

  const [startX, startY] = project(points[0]);
  const [endX, endY] = project(points[points.length - 1]);

  return (
    <svg viewBox={`0 0 ${SIZE} ${SIZE}`} width={SIZE} height={SIZE} role="img" aria-label={label} className="shrink-0 rounded-lg bg-cream-deep" data-testid="route-thumbnail">
      {segments.map((segment, index) => (
        <polyline
          key={index}
          points={segment.map((point) => project(point).map((value) => value.toFixed(1)).join(',')).join(' ')}
          fill="none"
          stroke="#9e4c0c"
          strokeWidth={STROKE}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ))}
      <circle cx={endX} cy={endY} r={DOT} fill="#f28b38" stroke="#fff" strokeWidth={1.5} />
      <circle cx={startX} cy={startY} r={DOT} fill="#422d21" stroke="#fff" strokeWidth={1.5} />
    </svg>
  );
}
