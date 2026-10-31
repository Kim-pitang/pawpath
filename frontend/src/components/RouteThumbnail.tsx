const SIZE = 72;
const PADDING = 8;

/** 목록용 경로 그림. 지도 타일을 받지 않아 카드가 많아도 가볍다. */
export default function RouteThumbnail({ segments, label, size = SIZE }: { segments: number[][][]; label: string; size?: number }) {
  const points = segments.flat();
  if (points.length === 0) return <div style={{ width: size, height: size }} className="shrink-0 rounded-2xl bg-cream-deep" />;

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
    <svg viewBox={`0 0 ${SIZE} ${SIZE}`} width={size} height={size} role="img" aria-label={label} className="shrink-0 rounded-2xl bg-leaf-50" data-testid="route-thumbnail">
      {segments.map((segment, index) => (
        <polyline
          key={index}
          points={segment.map((point) => project(point).map((value) => value.toFixed(1)).join(',')).join(' ')}
          fill="none"
          stroke="#2e8b62"
          strokeWidth={2.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ))}
      <circle cx={endX} cy={endY} r={3.5} fill="#d9661a" stroke="#fff" strokeWidth={1.5} />
      <circle cx={startX} cy={startY} r={3.5} fill="#175239" stroke="#fff" strokeWidth={1.5} />
    </svg>
  );
}
