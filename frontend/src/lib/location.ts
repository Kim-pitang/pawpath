import { useEffect, useMemo, useState } from 'react';
import { pointAt, type LatLng, type RouteModel } from './navigation';

export type GpsStatus = 'off' | 'requesting' | 'active' | 'denied' | 'unavailable' | 'insecure' | 'unsupported';

export interface WalkPosition {
  point: LatLng;
  accuracy: number | null;
}

export const GPS_MESSAGES: Partial<Record<GpsStatus, string>> = {
  denied: '위치 권한이 꺼져 있어요. 브라우저 설정에서 이 사이트의 위치 접근을 허용해 주세요.',
  unavailable: '현재 위치를 찾지 못했어요. 하늘이 잘 보이는 곳으로 이동해 보세요.',
  insecure: '이 주소는 HTTPS가 아니라서 브라우저가 위치 정보를 막고 있어요. HTTPS 주소나 localhost로 접속해 주세요.',
  unsupported: '이 브라우저는 위치 정보를 지원하지 않아요.',
};

export function useGeolocation(enabled: boolean): { status: GpsStatus; position: WalkPosition | null } {
  const [state, setState] = useState<{ status: GpsStatus; position: WalkPosition | null }>({
    status: enabled ? 'requesting' : 'off',
    position: null,
  });

  useEffect(() => {
    if (!enabled) {
      setState({ status: 'off', position: null });
      return;
    }
    if (!window.isSecureContext) {
      setState({ status: 'insecure', position: null });
      return;
    }
    if (!('geolocation' in navigator)) {
      setState({ status: 'unsupported', position: null });
      return;
    }

    setState({ status: 'requesting', position: null });
    const watchId = navigator.geolocation.watchPosition(
      ({ coords }) =>
        setState({ status: 'active', position: { point: [coords.latitude, coords.longitude], accuracy: coords.accuracy } }),
      (error) =>
        // 일시적으로 신호를 놓쳐도 마지막 위치는 유지한다. 신호가 돌아오면 감시가 이어서 갱신한다.
        setState((previous) => ({
          status: error.code === error.PERMISSION_DENIED ? 'denied' : 'unavailable',
          position: error.code === error.PERMISSION_DENIED ? null : previous.position,
        })),
      { enableHighAccuracy: true, maximumAge: 2000, timeout: 20000 },
    );
    return () => navigator.geolocation.clearWatch(watchId);
  }, [enabled]);

  return state;
}

const SIMULATION_STEP_M = 20;
const SIMULATION_INTERVAL_MS = 500;

/** 시연용 위치. 실제 GPS 없이 코스를 일정한 속도로 따라 걷는다. */
export function useSimulatedWalk(route: RouteModel | null, active: boolean): WalkPosition | null {
  // 걸은 거리를 경로와 묶어 둔다. 복귀 경로로 바뀐 첫 렌더에 이전 경로의 거리를 쓰면 바로 도착 처리된다.
  const [walked, setWalked] = useState<{ route: RouteModel | null; meters: number }>({ route: null, meters: 0 });
  const meters = walked.route === route ? walked.meters : 0;

  useEffect(() => {
    if (!active || !route) return;
    setWalked({ route, meters: 0 });
    const timer = window.setInterval(
      () => setWalked((value) => ({ route, meters: Math.min(route.total, value.meters + SIMULATION_STEP_M) })),
      SIMULATION_INTERVAL_MS,
    );
    return () => window.clearInterval(timer);
  }, [active, route]);

  return useMemo(
    () => (active && route ? { point: pointAt(route, meters), accuracy: 5 } : null),
    [active, route, meters],
  );
}

/** 산책 중 화면이 꺼지면 위치 갱신이 멈추므로 화면을 켜 둔다. 지원하지 않으면 조용히 넘어간다. */
export function useWakeLock(active: boolean): void {
  useEffect(() => {
    if (!active || !('wakeLock' in navigator)) return;
    let lock: WakeLockSentinel | null = null;
    let cancelled = false;

    const acquire = () =>
      navigator.wakeLock
        .request('screen')
        .then((sentinel) => {
          if (cancelled) void sentinel.release();
          else lock = sentinel;
        })
        .catch(() => undefined);
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') void acquire();
    };

    void acquire();
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      cancelled = true;
      document.removeEventListener('visibilitychange', onVisibilityChange);
      void lock?.release();
    };
  }, [active]);
}
