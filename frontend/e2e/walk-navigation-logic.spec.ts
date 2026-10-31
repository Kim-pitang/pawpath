import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import {
  FINISH_M,
  INITIAL_TRACKING,
  advanceTracking,
  buildRoute,
  distanceM,
  formatDistance,
  guidanceFor,
  locate,
  pointAt,
  sliceRoute,
  toleranceFor,
  type LatLng,
  type RouteModel,
} from '../src/lib/navigation';

// 브라우저 없이 안내 계산만 검증한다. 위도 0.001도는 약 111m다.
const EAST_THEN_NORTH: LatLng[] = [
  [37.55, 126.9],
  [37.55, 126.903],
  [37.553, 126.903],
];
const EAST_THEN_SOUTH: LatLng[] = [
  [37.55, 126.9],
  [37.55, 126.903],
  [37.547, 126.903],
];
const OUT_AND_BACK: LatLng[] = [
  [37.55, 126.9],
  [37.553, 126.9],
  [37.55, 126.9],
];
const LOOP: LatLng[] = [
  [37.55, 126.9],
  [37.55, 126.903],
  [37.553, 126.903],
  [37.553, 126.9],
  [37.55, 126.9],
];

/** 경로를 일정 간격으로 따라 걸었을 때의 진행도 기록. */
function walk(route: RouteModel, stepMeters = 15): number[] {
  const history: number[] = [];
  let progress = 0;
  for (let meters = 0; meters <= route.total; meters += stepMeters) {
    progress = locate(route, pointAt(route, meters), progress).progress;
    history.push(progress);
  }
  return history;
}

test('길이가 0인 경로에서도 계산이 멈추지 않는다', () => {
  // 출발점에 이미 서 있으면 출발점까지의 경로는 같은 점 두 개다.
  const here: LatLng = [37.55, 126.9];
  const route = buildRoute([here, here]);
  expect(route.total).toBe(0);
  expect(route.turns).toEqual([]);
  expect(locate(route, here, 0)).toEqual({ progress: 0, offset: 0, point: here });
  const away = locate(route, [37.551, 126.9], 0);
  expect(away.progress).toBe(0);
  expect(away.offset).toBeGreaterThan(100);
  expect(guidanceFor(route, 0).kind).toBe('arrive');
  expect(buildRoute([here]).total).toBe(0);
  expect(sliceRoute(route, 0, 100)).toHaveLength(2);
});

test('왼쪽과 오른쪽 회전을 구분한다', () => {
  expect(buildRoute(EAST_THEN_NORTH).turns.map((turn) => turn.kind)).toEqual(['left']);
  expect(buildRoute(EAST_THEN_SOUTH).turns.map((turn) => turn.kind)).toEqual(['right']);
});

test('왕복 코스의 반환점을 유턴으로 인식한다', () => {
  const route = buildRoute(OUT_AND_BACK);
  expect(route.turns).toHaveLength(1);
  expect(route.turns[0].kind).toBe('uturn');
  expect(route.turns[0].at).toBeCloseTo(route.total / 2, 0);
});

test('완만한 굴곡은 회전으로 안내하지 않는다', () => {
  const gentle: LatLng[] = [
    [37.55, 126.9],
    [37.5502, 126.902],
    [37.55, 126.904],
    [37.5502, 126.906],
  ];
  expect(buildRoute(gentle).turns).toEqual([]);
});

test('길을 건너며 살짝 꺾이는 곳은 회전으로 안내하지 않는다', () => {
  const jog: LatLng[] = [
    [37.55, 126.9],
    [37.55, 126.902],
    [37.55008, 126.90203],
    [37.55008, 126.905],
  ];
  expect(buildRoute(jog).turns).toEqual([]);
});

test('진행도는 걷는 동안 되돌아가지 않는다', () => {
  for (const points of [EAST_THEN_NORTH, OUT_AND_BACK, LOOP]) {
    const history = walk(buildRoute(points));
    expect(history).toEqual([...history].sort((a, b) => a - b));
  }
});

test('왕복 코스에서 반환점 전에 복귀 구간으로 건너뛰지 않는다', () => {
  const route = buildRoute(OUT_AND_BACK);
  const half = route.total / 2;
  let progress = 0;
  for (let meters = 0; meters <= half - 20; meters += 15) {
    progress = locate(route, pointAt(route, meters), progress).progress;
    expect(progress).toBeLessThanOrEqual(half);
  }
});

test('왕복 코스의 복귀 구간을 걸으면 끝까지 진행된다', () => {
  const route = buildRoute(OUT_AND_BACK);
  const history = walk(route);
  expect(history[history.length - 1]).toBeGreaterThan(route.total - 20);
});

test('순환 코스는 출발 지점에서 끝난 것으로 치지 않는다', () => {
  const route = buildRoute(LOOP);
  const first = advanceTracking(route, INITIAL_TRACKING, LOOP[0], 5, 1000);
  expect(first.progress).toBeLessThan(5);
  expect(first.finished).toBe(false);
  expect(first.startedAt).toBe(1000);
  expect(advanceTracking(route, first, LOOP[0], 5, 2000).finished).toBe(false);
});

test('복귀 경로가 아주 짧으면 첫 측정에서 바로 도착한다', () => {
  // 출발점 근처에서 복귀를 고르면 다음 위치 변화 없이도 끝나야 한다.
  const near: LatLng[] = [
    [37.55, 126.9],
    [37.55009, 126.9],
  ];
  const route = buildRoute(near);
  expect(advanceTracking(route, INITIAL_TRACKING, near[0], 5, 1000, true).finished).toBe(true);
  // 순환 코스 규칙은 그대로다.
  expect(advanceTracking(route, INITIAL_TRACKING, near[0], 5, 1000).finished).toBe(false);
});

test('경로를 따라 끝까지 걸으면 완주한다', () => {
  const route = buildRoute(LOOP);
  let tracking = INITIAL_TRACKING;
  for (let meters = 0; meters <= route.total; meters += 20) {
    tracking = advanceTracking(route, tracking, pointAt(route, meters), 5, meters);
  }
  tracking = advanceTracking(route, tracking, pointAt(route, route.total), 5, 99999);
  expect(tracking.finished).toBe(true);
});

test('코스 밖에서는 시작하지 않고 코스에 들어오면 시작한다', () => {
  const route = buildRoute(EAST_THEN_NORTH);
  const away = advanceTracking(route, INITIAL_TRACKING, [37.56, 126.9], 5, 1000);
  expect(away.startedAt).toBeNull();
  expect(away.offset).toBeGreaterThan(500);
  expect(away.progress).toBe(0);
  const joined = advanceTracking(route, away, EAST_THEN_NORTH[0], 5, 2000);
  expect(joined.startedAt).toBe(2000);
});

test('코스를 벗어나도 진행도를 유지하고 돌아오면 이어진다', () => {
  const route = buildRoute(EAST_THEN_NORTH);
  const before = locate(route, pointAt(route, 100), 80);
  const off = locate(route, [37.5512, 126.901], before.progress);
  expect(off.offset).toBeGreaterThan(100);
  expect(off.progress).toBe(before.progress);
  const back = locate(route, pointAt(route, 130), off.progress);
  expect(back.offset).toBeLessThan(1);
  expect(back.progress).toBeCloseTo(130, 0);
});

test('중간에 합류하면 그 지점부터 안내한다', () => {
  const route = buildRoute(EAST_THEN_NORTH);
  const located = locate(route, pointAt(route, 400), 0);
  expect(located.progress).toBeCloseTo(400, 0);
});

test('GPS 오차가 큰 측정값은 진행도에 쓰지 않는다', () => {
  const route = buildRoute(EAST_THEN_NORTH);
  const tracking = advanceTracking(route, INITIAL_TRACKING, pointAt(route, 300), 250, 1000);
  expect(tracking).toEqual(INITIAL_TRACKING);
});

test('이탈 판단 범위는 GPS 정확도에 따라 정해진 범위 안에서 변한다', () => {
  expect(toleranceFor(null)).toBe(35);
  expect(toleranceFor(5)).toBe(35);
  expect(toleranceFor(50)).toBe(50);
  expect(toleranceFor(90)).toBe(60);
});

test('회전까지의 거리에 따라 안내 문구가 바뀐다', () => {
  const route = buildRoute(EAST_THEN_NORTH);
  const turnAt = route.turns[0].at;
  expect(guidanceFor(route, turnAt - 200).headline).toBe('약 200m 쭉 가세요');
  expect(guidanceFor(route, turnAt - 200).detail).toBe('그다음 왼쪽으로 가세요');
  expect(guidanceFor(route, turnAt - 100).headline).toBe('약 100m 앞에서 왼쪽으로 가세요');
  expect(guidanceFor(route, turnAt - 10).headline).toBe('지금 왼쪽으로 가세요');
  expect(guidanceFor(route, turnAt - 10).kind).toBe('left');
  expect(guidanceFor(route, turnAt + 50).headline).toContain('쭉 가세요');
  expect(guidanceFor(route, route.total - 10).kind).toBe('arrive');
});

test('유턴 안내 문구', () => {
  const route = buildRoute(OUT_AND_BACK);
  expect(guidanceFor(route, route.turns[0].at - 50).headline).toBe('약 50m 앞에서 돌아서 왔던 길로 가세요');
});

test('구간을 잘라도 시작과 끝 진행도가 맞다', () => {
  const route = buildRoute(EAST_THEN_NORTH);
  const piece = sliceRoute(route, 100, 400);
  expect(distanceM(piece[0], pointAt(route, 100))).toBeLessThan(0.5);
  expect(distanceM(piece[piece.length - 1], pointAt(route, 400))).toBeLessThan(0.5);
  expect(sliceRoute(route, 100, 99999).at(-1)).toEqual(pointAt(route, route.total));
});

test('모든 지역의 실제 코스를 걸어도 진행도가 역행하지 않고 끝까지 간다', () => {
  const read = (file: string): { code: string; route: LatLng[] }[] => JSON.parse(readFileSync(`../backend/app/data/${file}`, 'utf8'));
  const courses = [...read('courses.json'), ...read('courses_gaepo.json')];
  expect(courses.length).toBeGreaterThanOrEqual(16);
  for (const course of courses) {
    const route = buildRoute(course.route);
    let progress = 0;
    for (let meters = 0; meters <= route.total; meters += 5) {
      const next = locate(route, pointAt(route, meters), progress).progress;
      expect(next, course.code).toBeGreaterThanOrEqual(progress);
      // 같은 길을 되돌아오는 구간에서만 잠시 늦을 수 있다.
      expect(meters - next, course.code).toBeLessThan(50);
      progress = next;
    }
    expect(route.total - locate(route, pointAt(route, route.total), progress).progress, course.code).toBeLessThan(FINISH_M);
  }
});

test('거리 표기', () => {
  expect(formatDistance(4)).toBe('10m');
  expect(formatDistance(123)).toBe('120m');
  expect(formatDistance(999)).toBe('1000m');
  expect(formatDistance(1534)).toBe('1.5km');
});
