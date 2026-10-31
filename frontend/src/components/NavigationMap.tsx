import L from 'leaflet';
import { useEffect, useRef } from 'react';
import { sliceRoute, type LatLng, type RouteModel } from '../lib/navigation';
import type { Facility, NearbyPlace } from '../lib/types';
import { FACILITY_MARKERS } from './CourseMap';

const REMAINING_COLOR = '#2e8b62';
const NEXT_COLOR = '#d9661a';
const WALKED_COLOR = '#a39d8d';
const NEXT_SEGMENT_M = 250;
const FOLLOW_ZOOM = 17;

interface NavigationMapProps {
  route: RouteModel;
  progress: number;
  position: LatLng | null;
  accuracy: number | null;
  /** 코스에 들어오기 전 출발점까지의 경로. */
  approach: LatLng[] | null;
  /** 코스를 벗어났을 때 돌아갈 지점. */
  rejoinPoint: LatLng | null;
  facilities: Facility[];
  /** 내 위치를 따라가지 않을 때 한눈에 보여 줄 범위. 값이 바뀔 때만 지도를 맞춘다. */
  overview: LatLng[] | null;
  /** 켜 두었을 때 지도에 함께 표시할 주변 시설. */
  places: NearbyPlace[];
  follow: boolean;
  onUserPan: () => void;
}

export default function NavigationMap({
  route,
  progress,
  position,
  accuracy,
  approach,
  rejoinPoint,
  facilities,
  overview,
  places,
  follow,
  onUserPan,
}: NavigationMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layersRef = useRef<{
    walked: L.Polyline;
    remaining: L.Polyline;
    next: L.Polyline;
    approach: L.Polyline;
    rejoin: L.Polyline;
    me: L.Marker;
    accuracy: L.Circle;
    places: L.LayerGroup;
  } | null>(null);
  const onUserPanRef = useRef(onUserPan);
  onUserPanRef.current = onUserPan;

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, { zoomControl: false });
    L.control.zoom({ position: 'topright' }).addTo(map);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    map.fitBounds(L.latLngBounds(route.points), { padding: [28, 28] });
    map.on('dragstart', () => onUserPanRef.current());

    layersRef.current = {
      accuracy: L.circle([0, 0], { radius: 0, stroke: false, fillColor: '#3f7cc4', fillOpacity: 0.15, interactive: false }),
      walked: L.polyline([], { color: WALKED_COLOR, weight: 6, opacity: 0.85, lineCap: 'round', className: 'nav-walked' }).addTo(map),
      remaining: L.polyline([], { color: REMAINING_COLOR, weight: 6, lineCap: 'round', className: 'nav-remaining' }).addTo(map),
      next: L.polyline([], { color: NEXT_COLOR, weight: 7, lineCap: 'round', className: 'nav-next' }).addTo(map),
      approach: L.polyline([], { color: NEXT_COLOR, weight: 5, dashArray: '2 10', lineCap: 'round', className: 'nav-approach' }).addTo(map),
      rejoin: L.polyline([], { color: NEXT_COLOR, weight: 4, dashArray: '2 8', lineCap: 'round', className: 'nav-rejoin' }).addTo(map),
      places: L.layerGroup().addTo(map),
      me: L.marker([0, 0], { icon: L.divIcon({ className: 'pp-me', iconSize: [20, 20] }), keyboard: false, interactive: false, zIndexOffset: 1000 }),
    };

    L.marker(route.points[0], {
      // iconSize를 비워야 Leaflet 기본 크기(12px) 대신 글자에 맞는 너비가 된다.
      icon: L.divIcon({ html: '출발', className: 'pp-marker pp-marker-start', iconSize: undefined, iconAnchor: [16, 12] }),
      keyboard: false,
      interactive: false,
    })
      .addTo(map)
      .getElement()
      ?.style.setProperty('background', REMAINING_COLOR);

    for (const facility of facilities) {
      const style = FACILITY_MARKERS[facility.type];
      if (!style) continue;
      L.marker([facility.lat, facility.lng], {
        icon: L.divIcon({ html: style.glyph, className: 'pp-marker', iconSize: [26, 26] }),
        title: facility.name || facility.type,
      })
        .addTo(map)
        .getElement()
        ?.style.setProperty('background', style.color);
    }

    // 안내 패널 높이가 바뀌어도 지도가 빈 칸 없이 채워지게 한다.
    const observer = new ResizeObserver(() => map.invalidateSize());
    observer.observe(containerRef.current);
    mapRef.current = map;

    return () => {
      observer.disconnect();
      map.remove();
      mapRef.current = null;
      layersRef.current = null;
    };
    // 코스가 바뀌면 페이지가 새 지도를 만든다(key). 시설과 경로는 처음 한 번만 그린다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const layers = layersRef.current;
    if (!layers) return;
    layers.walked.setLatLngs(sliceRoute(route, 0, progress));
    layers.remaining.setLatLngs(sliceRoute(route, progress, route.total));
    layers.next.setLatLngs(sliceRoute(route, progress, progress + NEXT_SEGMENT_M));
  }, [route, progress]);

  useEffect(() => {
    layersRef.current?.approach.setLatLngs(approach ?? []);
  }, [approach]);

  useEffect(() => {
    if (overview && overview.length >= 2) mapRef.current?.fitBounds(L.latLngBounds(overview), { padding: [36, 36] });
  }, [overview]);

  useEffect(() => {
    const layer = layersRef.current?.places;
    if (!layer) return;
    layer.clearLayers();
    for (const place of places) {
      const style = FACILITY_MARKERS[place.type];
      if (!style) continue;
      const marker = L.marker([place.lat, place.lng], {
        icon: L.divIcon({ html: style.glyph, className: 'pp-marker pp-place', iconSize: [26, 26] }),
        title: place.name,
      }).addTo(layer);
      marker.bindTooltip(`${place.name} (경로에서 ${place.distance_m}m)`);
      marker.getElement()?.style.setProperty('background', style.color);
    }
  }, [places]);

  useEffect(() => {
    layersRef.current?.rejoin.setLatLngs(position && rejoinPoint ? [position, rejoinPoint] : []);
  }, [position, rejoinPoint]);

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
  }, [position, accuracy, follow]);

  return <div ref={containerRef} data-testid="navigation-map" className="isolate h-full w-full" />;
}
