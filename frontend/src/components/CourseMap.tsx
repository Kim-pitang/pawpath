import L from 'leaflet';
import { useEffect, useRef } from 'react';
import type { Course } from '../lib/types';

export const RANK_COLORS: Record<number, string> = {
  1: 'var(--color-mango-700)',
  2: 'var(--color-leaf-500)',
  3: 'var(--color-sky-500)',
};
const RANK_HEX: Record<number, string> = { 1: '#9e4c0c', 2: '#2e8b62', 3: '#3f7cc4' };
const OTHER_COURSE_HEX = '#a39d8d';
const SELECTED_COURSE_HEX = '#25784f';

export const FACILITY_MARKERS: Record<string, { glyph: string; color: string }> = {
  park: { glyph: '공', color: '#25784f' },
  dog_park: { glyph: '견', color: '#d9661a' },
  pet_friendly: { glyph: '동', color: '#a34a0f' },
  pet_shop: { glyph: '용', color: '#827d6f' },
  convenience: { glyph: '편', color: '#5f5b50' },
  toilets: { glyph: '화', color: '#3f7cc4' },
  drinking_water: { glyph: '물', color: '#0f7f9a' },
  veterinary: { glyph: '병', color: '#a0569e' },
  bench: { glyph: '벤', color: '#827d6f' },
  waste_basket: { glyph: '쓰', color: '#827d6f' },
  police: { glyph: '경', color: '#2d2a24' },
  surveillance: { glyph: 'C', color: '#2d2a24' },
};

function divIcon(html: string, className: string, size?: [number, number]) {
  return L.divIcon({ html, className, iconSize: size, iconAnchor: size ? [size[0] / 2, size[1] / 2] : undefined });
}

interface CourseMapProps {
  courses: Course[];
  selectedId: number | null;
  rankById: Record<number, number>;
  onSelect: (id: number) => void;
}

export default function CourseMap({ courses, selectedId, rankById, onSelect }: CourseMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.LayerGroup | null>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, { center: [37.556, 126.91], zoom: 14 });
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    mapRef.current = map;
    layerRef.current = L.layerGroup().addTo(map);
    return () => {
      map.remove();
      mapRef.current = null;
      layerRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    const layer = layerRef.current;
    if (!map || !layer || courses.length === 0) return;
    layer.clearLayers();

    // 선택한 코스가 위로 오도록 마지막에 그린다.
    const ordered = [...courses].sort((a, b) => Number(a.id === selectedId) - Number(b.id === selectedId));
    for (const course of ordered) {
      const selected = course.id === selectedId;
      const rank = rankById[course.id];
      const color = rank ? RANK_HEX[rank] : selected ? SELECTED_COURSE_HEX : OTHER_COURSE_HEX;
      const line = L.polyline(course.route, {
        color,
        weight: selected ? 6 : rank ? 4 : 3,
        opacity: selected ? 1 : selectedId === null ? 0.85 : 0.45,
        lineCap: 'round',
        lineJoin: 'round',
        className: `course-line course-${course.id}`,
      }).addTo(layer);
      // 툴팁은 문자열을 HTML로 넣는다. 내 산책길 코스의 이름은 사용자가 쓴 글이라 글자로만 넣는다.
      const tooltip = document.createElement('span');
      tooltip.textContent = course.name;
      line.bindTooltip(tooltip);
      line.on('click', () => onSelect(course.id));
    }

    const selected = courses.find((course) => course.id === selectedId);
    if (selected) {
      L.marker([selected.start_lat, selected.start_lng], {
        icon: divIcon('출발', 'pp-marker pp-marker-start'),
        keyboard: false,
      })
        .addTo(layer)
        .getElement()
        ?.style.setProperty('background', RANK_HEX[rankById[selected.id]] ?? SELECTED_COURSE_HEX);
      for (const facility of selected.facilities) {
        const style = FACILITY_MARKERS[facility.type];
        if (!style) continue;
        const marker = L.marker([facility.lat, facility.lng], {
          icon: divIcon(style.glyph, 'pp-marker', [26, 26]),
          title: facility.name || facility.type,
        }).addTo(layer);
        marker.getElement()?.style.setProperty('background', style.color);
      }
      map.fitBounds(L.latLngBounds(selected.route), { padding: [28, 28] });
    } else {
      map.fitBounds(L.latLngBounds(courses.flatMap((course) => course.route)), { padding: [20, 20] });
    }
  }, [courses, selectedId, rankById, onSelect]);

  return <div ref={containerRef} data-testid="course-map" className="isolate h-[46vh] min-h-72 w-full overflow-hidden rounded-3xl border border-line md:h-[60vh]" />;
}
