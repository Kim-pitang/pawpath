import { toLocalIso } from './format';
import { distanceM, type LatLng } from './navigation';
import type { WalkPointInput } from './types';

/** 이보다 부정확한 좌표는 경로에 넣지 않는다. */
export const MAX_RECORD_ACCURACY_M = 50;
/** 서 있을 때 GPS가 흔들려 거리가 늘지 않게 하는 최소 이동 거리. */
const MIN_MOVE_M = 3;
const MAX_JITTER_M = 10;
/** 사람과 반려동물이 낼 수 없는 속도. 순간 이동으로 본다. */
const MAX_SPEED_MPS = 12;
const JUMP_MIN_M = 30;
/** 튄 좌표가 이만큼 연달아 같은 곳에 찍히면 실제 위치로 받아들인다. */
const OUTLIER_CONFIRM = 3;
const OUTLIER_CLUSTER_M = 40;
/** 위치가 이만큼 끊겼다 돌아오면 사이를 잇지 않는다. 화면이 꺼졌던 경우다. */
const GAP_MS = 60_000;
const STORAGE_KEY = 'pawpath.recording.v1';

export type RecordingStatus = 'recording' | 'paused' | 'stopped';
export type FixOutcome = 'accepted' | 'ignored' | 'low_accuracy' | 'duplicate' | 'jump' | 'rejoined' | 'gap';

export interface RecordedPoint {
  lat: number;
  lng: number;
  alt: number | null;
  acc: number | null;
  t: number;
  segment: number;
}

export interface LocationFix {
  lat: number;
  lng: number;
  altitude: number | null;
  accuracy: number | null;
  t: number;
}

export interface Recording {
  /** 서버의 client_id. 재전송해도 한 번만 저장된다. */
  id: string;
  status: RecordingStatus;
  startedAt: number;
  /** 일시정지를 뺀, 지금까지 끝난 구간의 시간. */
  activeMs: number;
  resumedAt: number | null;
  segment: number;
  points: RecordedPoint[];
  distance: number;
  outliers: RecordedPoint[];
  /** 마지막으로 위치를 받은 시각. 좌표를 버렸어도 갱신한다. */
  lastSeenAt: number;
  gaps: number;
  rejected: { accuracy: number; duplicate: number; jump: number };
}

export function newClientId(): string {
  return `rec-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`}`;
}

export function startRecording(id: string, now: number): Recording {
  return {
    id,
    status: 'recording',
    startedAt: now,
    activeMs: 0,
    resumedAt: now,
    segment: 0,
    points: [],
    distance: 0,
    outliers: [],
    lastSeenAt: now,
    gaps: 0,
    rejected: { accuracy: 0, duplicate: 0, jump: 0 },
  };
}

const toLatLng = (point: RecordedPoint): LatLng => [point.lat, point.lng];

export function addFix(recording: Recording, fix: LocationFix): { recording: Recording; outcome: FixOutcome } {
  if (recording.status !== 'recording') return { recording, outcome: 'ignored' };
  const seen = { ...recording, lastSeenAt: Math.max(recording.lastSeenAt, fix.t) };
  const reject = (reason: keyof Recording['rejected'], outcome: FixOutcome, extra: Partial<Recording> = {}) => ({
    recording: { ...seen, ...extra, rejected: { ...seen.rejected, [reason]: seen.rejected[reason] + 1 } },
    outcome,
  });

  if (fix.accuracy !== null && fix.accuracy > MAX_RECORD_ACCURACY_M) return reject('accuracy', 'low_accuracy');

  const point: RecordedPoint = { lat: fix.lat, lng: fix.lng, alt: fix.altitude, acc: fix.accuracy, t: fix.t, segment: recording.segment };
  const last = recording.points.at(-1);
  // 첫 지점이거나 일시정지 후 새 구간이면 앞 구간과 잇지 않는다.
  if (!last || last.segment !== recording.segment) {
    return { recording: { ...seen, points: [...recording.points, point], outliers: [] }, outcome: 'accepted' };
  }

  const elapsedMs = fix.t - last.t;
  if (elapsedMs <= 0) return reject('duplicate', 'duplicate');

  if (fix.t - recording.lastSeenAt > GAP_MS) {
    const segment = recording.segment + 1;
    return {
      recording: { ...seen, segment, gaps: recording.gaps + 1, outliers: [], points: [...recording.points, { ...point, segment }] },
      outcome: 'gap',
    };
  }

  const moved = distanceM(toLatLng(last), [fix.lat, fix.lng]);
  if (moved > JUMP_MIN_M && moved / (elapsedMs / 1000) > MAX_SPEED_MPS) {
    const outliers = [...recording.outliers, point].slice(-OUTLIER_CONFIRM);
    const confirmed =
      outliers.length === OUTLIER_CONFIRM && outliers.every((item, index) => index === 0 || distanceM(toLatLng(outliers[index - 1]), toLatLng(item)) <= OUTLIER_CLUSTER_M);
    if (!confirmed) return reject('jump', 'jump', { outliers });
    // 터널이나 실내에서 나온 뒤처럼 위치가 실제로 옮겨간 경우다. 거리는 더하지 않고 새 구간으로 잇는다.
    const segment = recording.segment + 1;
    return {
      recording: { ...seen, segment, outliers: [], points: [...recording.points, { ...point, segment }] },
      outcome: 'rejoined',
    };
  }

  if (moved < Math.max(MIN_MOVE_M, Math.min((fix.accuracy ?? 0) / 2, MAX_JITTER_M))) {
    return reject('duplicate', 'duplicate', { outliers: [] });
  }
  return {
    recording: { ...seen, points: [...recording.points, point], distance: recording.distance + moved, outliers: [] },
    outcome: 'accepted',
  };
}

export function pauseRecording(recording: Recording, now: number): Recording {
  if (recording.status !== 'recording') return recording;
  return { ...recording, status: 'paused', activeMs: elapsedMs(recording, now), resumedAt: null, outliers: [] };
}

export function resumeRecording(recording: Recording, now: number): Recording {
  if (recording.status === 'recording') return recording;
  const last = recording.points.at(-1);
  return {
    ...recording,
    status: 'recording',
    resumedAt: now,
    lastSeenAt: now,
    outliers: [],
    segment: last && last.segment === recording.segment ? recording.segment + 1 : recording.segment,
  };
}

export function stopRecording(recording: Recording, now: number): Recording {
  return { ...pauseRecording(recording, now), status: 'stopped', resumedAt: null };
}

/** 새로고침이나 앱 중단 뒤 불러온 기록. 닫혀 있던 시간은 세지 않고 일시정지 상태로 돌린다. */
export function recoverRecording(recording: Recording): Recording {
  if (recording.status !== 'recording') return recording;
  return pauseRecording(recording, recording.lastSeenAt);
}

export function elapsedMs(recording: Recording, now: number): number {
  return recording.activeMs + (recording.resumedAt === null ? 0 : Math.max(0, now - recording.resumedAt));
}

export function recordingSegments(recording: Recording): LatLng[][] {
  const segments = new Map<number, LatLng[]>();
  for (const point of recording.points) {
    if (!segments.has(point.segment)) segments.set(point.segment, []);
    segments.get(point.segment)!.push(toLatLng(point));
  }
  return [...segments.values()];
}

export function toWalkPoints(recording: Recording): WalkPointInput[] {
  return recording.points.map((point) => ({
    latitude: point.lat,
    longitude: point.lng,
    altitude: point.alt,
    accuracy: point.acc,
    recorded_at: toLocalIso(new Date(point.t)),
    segment: point.segment,
  }));
}

/** 저장 공간이 부족하면 거짓을 돌려준다. 화면에서 알려 줘야 한다. */
export function saveDraft(recording: Recording): boolean {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(recording));
    return true;
  } catch {
    return false;
  }
}

export function loadDraft(): Recording | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const draft = JSON.parse(raw) as Recording;
    return typeof draft.id === 'string' && Array.isArray(draft.points) && typeof draft.status === 'string' ? draft : null;
  } catch {
    return null;
  }
}

export function clearDraft(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // 저장소를 쓸 수 없는 환경이면 지울 것도 없다.
  }
}
