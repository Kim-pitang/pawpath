/**
 * 산책 길 안내 계산. 브라우저와 지도에 의존하지 않는 순수 모듈이다.
 *
 * 왕복 코스는 같은 길을 두 번 지나므로 가장 가까운 점만 찾으면 진행도가 앞뒤로 튄다.
 * 그래서 직전 진행도 근처부터 찾고, 진행도는 되돌아가지 않게 한다.
 */
export type LatLng = [number, number];

export type TurnKind = 'left' | 'right' | 'uturn';

export interface Turn {
  at: number;
  kind: TurnKind;
}

export interface RouteModel {
  points: LatLng[];
  cumulative: number[];
  total: number;
  turns: Turn[];
}

export interface Located {
  progress: number;
  offset: number;
  point: LatLng;
}

export interface Guidance {
  kind: 'straight' | 'arrive' | TurnKind;
  headline: string;
  detail: string | null;
}

export interface Tracking {
  progress: number;
  offset: number | null;
  nearest: LatLng | null;
  startedAt: number | null;
  finished: boolean;
}

export const ON_ROUTE_M = 35;
export const MAX_ON_ROUTE_M = 60;
export const MAX_USABLE_ACCURACY_M = 100;
export const FINISH_M = 25;

const BACKTRACK_M = 30;
const LOOKAHEAD_M = 120;
const TIE_M = 3;
const TURN_LOOK_M = 30;
const TURN_GAP_M = 5;
const TURN_MIN_DEGREES = 40;
const UTURN_MIN_DEGREES = 150;
const TURN_MERGE_M = 25;
const TURN_NOW_M = 15;
const TURN_SOON_M = 150;

const TURN_TEXT: Record<TurnKind, string> = {
  left: '왼쪽으로 가세요',
  right: '오른쪽으로 가세요',
  uturn: '돌아서 왔던 길로 가세요',
};

export const INITIAL_TRACKING: Tracking = { progress: 0, offset: null, nearest: null, startedAt: null, finished: false };

const toRadians = (degrees: number) => (degrees * Math.PI) / 180;

export function distanceM(a: LatLng, b: LatLng): number {
  const dLat = toRadians(b[0] - a[0]);
  const dLng = toRadians(b[1] - a[1]);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRadians(a[0])) * Math.cos(toRadians(b[0])) * Math.sin(dLng / 2) ** 2;
  return 2 * 6371000 * Math.asin(Math.sqrt(h));
}

function bearing(a: LatLng, b: LatLng): number {
  const lat1 = toRadians(a[0]);
  const lat2 = toRadians(b[0]);
  const dLng = toRadians(b[1] - a[1]);
  const y = Math.sin(dLng) * Math.cos(lat2);
  const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLng);
  return (Math.atan2(y, x) * 180) / Math.PI;
}

/** 진행 방향 기준 회전각. 양수가 오른쪽이다. */
function signedTurn(from: number, to: number): number {
  return ((to - from + 540) % 360) - 180;
}

function segmentIndexAt(cumulative: number[], meters: number): number {
  let low = 0;
  let high = cumulative.length - 2;
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    if (cumulative[middle] <= meters) low = middle;
    else high = middle - 1;
  }
  return low;
}

function interpolate(points: LatLng[], cumulative: number[], meters: number): LatLng {
  const clamped = Math.max(0, Math.min(cumulative[cumulative.length - 1], meters));
  const index = segmentIndexAt(cumulative, clamped);
  const length = cumulative[index + 1] - cumulative[index];
  const t = length === 0 ? 0 : (clamped - cumulative[index]) / length;
  return [
    points[index][0] + (points[index + 1][0] - points[index][0]) * t,
    points[index][1] + (points[index + 1][1] - points[index][1]) * t,
  ];
}

function detectTurns(points: LatLng[], cumulative: number[]): Turn[] {
  const candidates: (Turn & { angle: number })[] = [];
  for (let index = 1; index < points.length - 1; index += 1) {
    const at = cumulative[index];
    if (at <= TURN_GAP_M || at >= cumulative[cumulative.length - 1] - TURN_GAP_M) continue;
    // 꼭짓점 앞뒤 구간의 방향을 비교한다. 길을 건너며 살짝 꺾이는 정도는 앞뒤 방향이 같아 회전이 아니다.
    const incoming = bearing(interpolate(points, cumulative, at - TURN_LOOK_M), interpolate(points, cumulative, at - TURN_GAP_M));
    const outgoing = bearing(interpolate(points, cumulative, at + TURN_GAP_M), interpolate(points, cumulative, at + TURN_LOOK_M));
    const angle = signedTurn(incoming, outgoing);
    const size = Math.abs(angle);
    if (size < TURN_MIN_DEGREES) continue;
    const kind: TurnKind = size >= UTURN_MIN_DEGREES ? 'uturn' : angle < 0 ? 'left' : 'right';
    candidates.push({ at, kind, angle: size });
  }

  const merged: (Turn & { angle: number })[] = [];
  for (const candidate of candidates) {
    const last = merged[merged.length - 1];
    if (last && candidate.at - last.at <= TURN_MERGE_M) {
      if (candidate.angle > last.angle) merged[merged.length - 1] = candidate;
    } else {
      merged.push(candidate);
    }
  }
  return merged.map(({ at, kind }) => ({ at, kind }));
}

export function buildRoute(input: LatLng[]): RouteModel {
  const points = input.length >= 2 ? input : [input[0], input[0]];
  const cumulative = [0];
  for (let index = 1; index < points.length; index += 1) {
    cumulative.push(cumulative[index - 1] + distanceM(points[index - 1], points[index]));
  }
  return { points, cumulative, total: cumulative[cumulative.length - 1], turns: detectTurns(points, cumulative) };
}

export function pointAt(route: RouteModel, meters: number): LatLng {
  return interpolate(route.points, route.cumulative, meters);
}

/** 진행도 구간의 경로 좌표. 지도에 걸은 길과 남은 길을 나눠 그릴 때 쓴다. */
export function sliceRoute(route: RouteModel, from: number, to: number): LatLng[] {
  const start = Math.max(0, Math.min(route.total, from));
  const end = Math.max(start, Math.min(route.total, to));
  const inner = route.points.filter((_, index) => route.cumulative[index] > start && route.cumulative[index] < end);
  return [pointAt(route, start), ...inner, pointAt(route, end)];
}

function project(route: RouteModel, position: LatLng, from: number, to: number): Located | null {
  const cosLat = Math.cos(toRadians(position[0]));
  const toLocal = (point: LatLng): [number, number] => [
    toRadians(point[1] - position[1]) * cosLat * 6371000,
    toRadians(point[0] - position[0]) * 6371000,
  ];

  let best: Located | null = null;
  for (let index = 0; index < route.points.length - 1; index += 1) {
    const segmentStart = route.cumulative[index];
    const segmentEnd = route.cumulative[index + 1];
    const length = segmentEnd - segmentStart;
    if (length === 0 || segmentEnd < from || segmentStart > to) continue;

    const [ax, ay] = toLocal(route.points[index]);
    const [bx, by] = toLocal(route.points[index + 1]);
    const dx = bx - ax;
    const dy = by - ay;
    const raw = (-ax * dx - ay * dy) / (dx * dx + dy * dy);
    const t = Math.max((from - segmentStart) / length, Math.min((to - segmentStart) / length, Math.max(0, Math.min(1, raw))));
    const offset = Math.hypot(ax + dx * t, ay + dy * t);

    // 왕복 구간처럼 거의 같은 거리면 앞쪽을 택해, 반환점에 닿기 전에 건너뛰지 않게 한다.
    if (best === null || offset < best.offset - TIE_M) {
      best = {
        progress: segmentStart + length * t,
        offset,
        point: [
          route.points[index][0] + (route.points[index + 1][0] - route.points[index][0]) * t,
          route.points[index][1] + (route.points[index + 1][1] - route.points[index][1]) * t,
        ],
      };
    }
  }
  return best;
}

/** 현재 위치를 경로 위 진행도로 바꾼다. */
export function locate(route: RouteModel, position: LatLng, previous: number, tolerance = ON_ROUTE_M): Located {
  const nearby = project(route, position, Math.max(0, previous - BACKTRACK_M), Math.min(route.total, previous + LOOKAHEAD_M));
  if (nearby && nearby.offset <= tolerance) {
    return { ...nearby, progress: Math.max(previous, nearby.progress) };
  }

  // 근처에 없으면 지름길로 앞쪽에 합류했는지 보고, 그다음 지나온 쪽에 돌아왔는지 본다.
  const ahead = project(route, position, previous, route.total);
  if (ahead && ahead.offset <= tolerance) return ahead;
  const behind = project(route, position, 0, previous);
  if (behind && behind.offset <= tolerance) return behind;

  const candidates = [ahead, behind].filter((item): item is Located => item !== null);
  // 출발점에 이미 서 있으면 경로 길이가 0이라 후보가 없을 수 있다.
  if (candidates.length === 0) {
    return { progress: previous, offset: distanceM(position, route.points[0]), point: route.points[0] };
  }
  const closest = candidates.reduce((a, b) => (b.offset < a.offset ? b : a));
  return { ...closest, progress: previous };
}

/** GPS가 부정확할수록 코스 이탈 판단을 너그럽게 한다. */
export function toleranceFor(accuracy: number | null): number {
  return Math.max(ON_ROUTE_M, Math.min(MAX_ON_ROUTE_M, accuracy ?? 0));
}

export function advanceTracking(
  route: RouteModel,
  previous: Tracking,
  position: LatLng,
  accuracy: number | null,
  now: number,
): Tracking {
  if (accuracy !== null && accuracy > MAX_USABLE_ACCURACY_M) return previous;
  const tolerance = toleranceFor(accuracy);
  const located = locate(route, position, previous.progress, tolerance);
  const onRoute = located.offset <= tolerance;
  return {
    progress: located.progress,
    offset: located.offset,
    nearest: located.point,
    startedAt: previous.startedAt ?? (onRoute ? now : null),
    // 코스에 들어온 뒤에만 완주로 친다. 시작점과 끝점이 같은 순환 코스에서 출발하자마자 끝나지 않게 한다.
    finished: previous.finished || (onRoute && previous.startedAt !== null && located.progress >= route.total - FINISH_M),
  };
}

function roundDistance(meters: number): number {
  return Math.max(10, Math.round(meters / 10) * 10);
}

export function formatDistance(meters: number): string {
  return meters < 1000 ? `${roundDistance(meters)}m` : `${(meters / 1000).toFixed(1)}km`;
}

export function guidanceFor(route: RouteModel, progress: number, arrivalText = '곧 도착이에요'): Guidance {
  const remaining = route.total - progress;
  if (remaining <= FINISH_M) return { kind: 'arrive', headline: arrivalText, detail: null };

  const turn = route.turns.find((item) => item.at > progress + 2);
  if (!turn) {
    return { kind: 'straight', headline: `약 ${formatDistance(remaining)} 쭉 가세요`, detail: arrivalText };
  }

  const distance = turn.at - progress;
  if (distance <= TURN_NOW_M) return { kind: turn.kind, headline: `지금 ${TURN_TEXT[turn.kind]}`, detail: null };
  if (distance <= TURN_SOON_M) {
    return { kind: turn.kind, headline: `약 ${formatDistance(distance)} 앞에서 ${TURN_TEXT[turn.kind]}`, detail: null };
  }
  return {
    kind: 'straight',
    headline: `약 ${formatDistance(distance)} 쭉 가세요`,
    detail: `그다음 ${TURN_TEXT[turn.kind]}`,
  };
}
