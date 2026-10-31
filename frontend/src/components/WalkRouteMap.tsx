import L from 'leaflet';
import { useEffect, useRef } from 'react';
import type { LatLng } from '../lib/navigation';

const ROUTE_COLOR = '#2e8b62';
const END_COLOR = '#d9661a';
const FOLLOW_ZOOM = 17;
const DEFAULT_CENTER: LatLng = [37.556, 126.91];

interface WalkRouteMapProps {
  /** 구간별 경로. 일시정지나 끊긴 구간 사이는 선을 잇지 않는다. */
  segments: LatLng[][];
  position?: LatLng | null;
  accuracy?: number | null;
  /** 기록 중에는 내 위치를 따라가고, 보기만 할 때는 경로 전체를 맞춘다. */
  follow?: boolean;
  showEnd?: boolean;
  onUserPan?: () => void;
  /** 지도를 눌러 점을 고를 때 쓴다. 출발점 지정 화면에서만 넘긴다. */
  onMapClick?: (point: LatLng) => void;
  /** 위치가 바뀔 때마다 지도를 그 위치로 옮긴다. 출발점 지정 화면에서만 켠다. */
  centerOnPosition?: boolean;
}

function endMarker(label: string, point: LatLng, color: string, map: L.Map): L.Marker {
  const marker = L.marker(point, {
    icon: L.divIcon({ html: label, className: 'pp-marker pp-marker-start', iconSize: undefined, iconAnchor: [16, 12] }),
    keyboard: false,
    interactive: false,
  }).addTo(map);
  marker.getElement()?.style.setProperty('background', color);
  return marker;
}

/** 산책 기록, GPX 미리보기, 상세, 공유 화면이 함께 쓰는 경로 지도. */
export default function WalkRouteMap({ segments, position = null, accuracy = null, follow = false, showEnd = true, onUserPan, onMapClick, centerOnPosition = false }: WalkRouteMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layersRef = useRef<{ line: L.Polyline; me: L.Marker; accuracy: L.Circle; start: L.Marker | null; end: L.Marker | null } | null>(null);
  const onUserPanRef = useRef(onUserPan);
  onUserPanRef.current = onUserPan;
  const onMapClickRef = useRef(onMapClick);
  onMapClickRef.current = onMapClick;

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, { center: DEFAULT_CENTER, zoom: 15, zoomControl: false });
    L.control.zoom({ position: 'topright' }).addTo(map);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    map.on('dragstart', () => onUserPanRef.current?.());
    map.on('click', (event: L.LeafletMouseEvent) => onMapClickRef.current?.([event.latlng.lat, event.latlng.lng]));
    layersRef.current = {
      line: L.polyline([], { color: ROUTE_COLOR, weight: 6, lineCap: 'round', className: 'walk-line' }).addTo(map),
      accuracy: L.circle([0, 0], { radius: 0, stroke: false, fillColor: '#3f7cc4', fillOpacity: 0.15, interactive: false }),
      me: L.marker([0, 0], { icon: L.divIcon({ className: 'pp-me', iconSize: [20, 20] }), keyboard: false, interactive: false, zIndexOffset: 1000 }),
      start: null,
      end: null,
    };
    const observer = new ResizeObserver(() => map.invalidateSize());
    observer.observe(containerRef.current);
    mapRef.current = map;
    return () => {
      observer.disconnect();
      map.remove();
      mapRef.current = null;
      layersRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    const layers = layersRef.current;
    if (!map || !layers) return;
    layers.line.setLatLngs(segments);
    const first = segments[0]?.[0];
    const last = segments.at(-1)?.at(-1);
    if (first && !layers.start) layers.start = endMarker('출발', first, ROUTE_COLOR, map);
    else if (first) layers.start?.setLatLng(first);
    else {
      layers.start?.remove();
      layers.start = null;
    }
    if (showEnd && last && !layers.end) layers.end = endMarker('도착', last, END_COLOR, map);
    else if (showEnd && last) layers.end?.setLatLng(last);
    else {
      layers.end?.remove();
      layers.end = null;
    }
    if (!follow && first) map.fitBounds(L.latLngBounds(segments.flat()), { padding: [36, 36] });
  }, [segments, follow, showEnd]);

  useEffect(() => {
    const map = mapRef.current;
    const layers = layersRef.current;
    if (!map || !layers) return;
    if (!position) {
      layers.me.remove();
      layers.accuracy.remove();
      return;
    }
    layers.me.setLatLng(position).addTo(map);
    layers.accuracy.setLatLng(position).setRadius(accuracy ?? 0).addTo(map);
    if (follow) map.setView(position, Math.max(map.getZoom(), FOLLOW_ZOOM), { animate: true });
    else if (centerOnPosition) map.setView(position, Math.max(map.getZoom(), 16));
  }, [position, accuracy, follow, centerOnPosition]);

  return <div ref={containerRef} data-testid="walk-route-map" className="isolate h-full w-full" />;
}
