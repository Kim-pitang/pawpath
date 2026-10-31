import { expect, test } from '@playwright/test';
import {
  addFix,
  elapsedMs,
  MAX_RECORD_ACCURACY_M,
  pauseRecording,
  recordingSegments,
  recoverRecording,
  resumeRecording,
  startRecording,
  stopRecording,
  toWalkPoints,
  type LocationFix,
  type Recording,
} from '../src/lib/recording';

const T0 = new Date('2026-10-31T16:00:00').getTime();
// 위도 0.0001도는 약 11m다.
const fix = (index: number, seconds: number, overrides: Partial<LocationFix> = {}): LocationFix => ({
  lat: 37.4882 + index * 0.0001,
  lng: 127.0647,
  altitude: null,
  accuracy: 5,
  t: T0 + seconds * 1000,
  ...overrides,
});

function walked(count: number, stepSeconds = 10): Recording {
  let recording = startRecording('rec-test-0001', T0);
  for (let index = 0; index < count; index += 1) recording = addFix(recording, fix(index, index * stepSeconds)).recording;
  return recording;
}

test('정상적으로 걸으면 지점과 거리가 쌓인다', () => {
  const recording = walked(5);
  expect(recording.points).toHaveLength(5);
  expect(recording.distance).toBeGreaterThan(40);
  expect(recording.distance).toBeLessThan(50);
  expect(recordingSegments(recording)).toHaveLength(1);
});

test('정확도가 낮은 좌표는 버리고 세어 둔다', () => {
  const { recording, outcome } = addFix(walked(2), fix(2, 20, { accuracy: MAX_RECORD_ACCURACY_M + 1 }));
  expect(outcome).toBe('low_accuracy');
  expect(recording.points).toHaveLength(2);
  expect(recording.rejected.accuracy).toBe(1);
});

test('정확도 값이 없는 좌표는 받아들인다', () => {
  expect(addFix(walked(2), fix(2, 20, { accuracy: null })).outcome).toBe('accepted');
});

test('같은 자리의 좌표와 작은 흔들림은 거리를 늘리지 않는다', () => {
  const base = walked(2);
  const same = addFix(base, fix(1, 20));
  expect(same.outcome).toBe('duplicate');
  expect(same.recording.distance).toBe(base.distance);
  // 정확도가 낮을수록 흔들림으로 보는 범위가 넓다.
  const jitter = addFix(base, fix(1.5, 20, { accuracy: 30 }));
  expect(jitter.outcome).toBe('duplicate');
  expect(jitter.recording.points).toHaveLength(2);
});

test('시각이 뒤로 가거나 같은 좌표는 버린다', () => {
  expect(addFix(walked(2), fix(5, 5)).outcome).toBe('duplicate');
  expect(addFix(walked(2), fix(5, 10)).outcome).toBe('duplicate');
});

test('순간 이동한 좌표는 경로와 거리에 넣지 않는다', () => {
  const base = walked(2);
  const { recording, outcome } = addFix(base, fix(500, 11));
  expect(outcome).toBe('jump');
  expect(recording.points).toHaveLength(2);
  expect(recording.distance).toBe(base.distance);
  // 튄 좌표 뒤에 원래 길로 돌아오면 이어서 기록한다.
  const back = addFix(recording, fix(2, 20));
  expect(back.outcome).toBe('accepted');
  expect(back.recording.outliers).toHaveLength(0);
});

test('튄 위치가 연달아 같은 곳이면 실제 위치로 보고 새 구간을 시작한다', () => {
  let recording = walked(2);
  expect(addFix(recording, fix(500, 11)).outcome).toBe('jump');
  recording = addFix(recording, fix(500, 11)).recording;
  recording = addFix(recording, fix(500.5, 12)).recording;
  const { recording: moved, outcome } = addFix(recording, fix(501, 13));
  expect(outcome).toBe('rejoined');
  expect(moved.segment).toBe(1);
  expect(moved.points.at(-1)?.segment).toBe(1);
  expect(moved.distance).toBeLessThan(20);
});

test('서로 다른 곳으로 튀는 좌표는 끝까지 받아들이지 않는다', () => {
  let recording = walked(2);
  for (const [index, seconds] of [[500, 11], [900, 12], [1500, 13], [2300, 14]]) {
    const result = addFix(recording, fix(index, seconds));
    expect(result.outcome).toBe('jump');
    recording = result.recording;
  }
  expect(recording.points).toHaveLength(2);
});

test('화면이 꺼져 위치가 끊겼다 돌아오면 사이를 잇지 않고 거리에서 뺀다', () => {
  const base = walked(2);
  const { recording, outcome } = addFix(base, fix(60, 600));
  expect(outcome).toBe('gap');
  expect(recording.gaps).toBe(1);
  expect(recording.segment).toBe(1);
  expect(recording.distance).toBe(base.distance);
  expect(recordingSegments(recording)).toHaveLength(2);
});

test('오래 서 있어도 위치를 계속 받았다면 끊긴 것으로 보지 않는다', () => {
  let recording = walked(2);
  for (let seconds = 20; seconds <= 300; seconds += 20) recording = addFix(recording, fix(1, seconds)).recording;
  const { recording: moved, outcome } = addFix(recording, fix(2, 310));
  expect(outcome).toBe('accepted');
  expect(moved.gaps).toBe(0);
  expect(moved.segment).toBe(0);
});

test('일시정지 중의 이동과 시간은 기록하지 않고, 재개하면 새 구간으로 시작한다', () => {
  const before = pauseRecording(walked(3), T0 + 30_000);
  expect(before.status).toBe('paused');
  expect(elapsedMs(before, T0 + 500_000)).toBe(30_000);
  expect(addFix(before, fix(50, 100)).outcome).toBe('ignored');

  const resumed = resumeRecording(before, T0 + 600_000);
  expect(elapsedMs(resumed, T0 + 610_000)).toBe(40_000);
  const first = addFix(resumed, fix(100, 601));
  expect(first.outcome).toBe('accepted');
  expect(first.recording.distance).toBe(before.distance);
  const second = addFix(first.recording, fix(101, 611));
  expect(second.recording.distance).toBeGreaterThan(before.distance);
  expect(recordingSegments(second.recording)).toHaveLength(2);
});

test('아무 지점 없이 일시정지했다 재개하면 구간이 늘지 않는다', () => {
  const started = startRecording('rec-test-0001', T0);
  expect(resumeRecording(pauseRecording(started, T0 + 1000), T0 + 2000).segment).toBe(0);
});

test('종료하면 시간이 멈추고 좌표를 더 받지 않는다', () => {
  const stopped = stopRecording(walked(3), T0 + 40_000);
  expect(stopped.status).toBe('stopped');
  expect(elapsedMs(stopped, T0 + 999_000)).toBe(40_000);
  expect(addFix(stopped, fix(9, 50)).outcome).toBe('ignored');
});

test('새로고침 뒤 복구하면 닫혀 있던 시간은 빼고 일시정지 상태가 된다', () => {
  const recovered = recoverRecording(walked(4));
  expect(recovered.status).toBe('paused');
  expect(recovered.resumedAt).toBeNull();
  expect(recovered.activeMs).toBe(30_000);
  expect(recovered.points).toHaveLength(4);
  expect(recoverRecording(recovered)).toBe(recovered);
});

test('저장용 지점에는 위경도, 정확도, 시각, 구간이 들어간다', () => {
  const [first] = toWalkPoints(walked(2));
  expect(first).toEqual({ latitude: 37.4882, longitude: 127.0647, altitude: null, accuracy: 5, recorded_at: '2026-10-31T16:00:00', segment: 0 });
});
