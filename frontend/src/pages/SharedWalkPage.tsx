import { Download } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { MungoMark, Wordmark } from '../components/Logo';
import { Card, EmptyState, Loading } from '../components/ui';
import WalkRouteMap from '../components/WalkRouteMap';
import { api } from '../lib/api';
import { distanceLabel, durationLabel } from '../lib/format';
import type { LatLng } from '../lib/navigation';
import type { SharedWalk } from '../lib/types';

/** 공유 링크로 들어오는 화면. 받는 사람이 앱 메뉴를 몰라도 되도록 공통 메뉴 없이 띄운다. */
export default function SharedWalkPage() {
  const { token = '' } = useParams();
  const [walk, setWalk] = useState<SharedWalk | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getSharedWalk(token).then(setWalk).catch((loadError: Error) => setError(loadError.message));
  }, [token]);

  const route = useMemo(() => (walk?.route ?? []) as LatLng[][], [walk?.route]);

  return (
    <div className="mx-auto flex min-h-dvh max-w-3xl flex-col gap-4 p-4">
      <header className="flex items-center gap-2">
        <MungoMark />
        <Wordmark compact />
      </header>

      {error && (
        <Card>
          <EmptyState title={error}>
            <p className="text-sm text-ink-soft">링크가 해제되었거나 기간이 끝났을 수 있어요. 공유한 분께 다시 요청해 주세요.</p>
          </EmptyState>
        </Card>
      )}
      {!walk && !error && <Loading />}
      {walk && (
        <>
          <h1 className="text-2xl font-bold text-ink" data-testid="shared-title">
            {walk.title}
          </h1>
          <div className="h-80 overflow-hidden rounded-xl border border-line md:h-[28rem]">
            <WalkRouteMap segments={route} />
          </div>
          <Card>
            <dl className="grid grid-cols-2 text-center" data-testid="shared-stats">
              <div>
                <dt className="text-xs text-ink-muted">총 거리</dt>
                <dd className="mt-0.5 text-lg font-bold">{distanceLabel(walk.distance_m)}</dd>
              </div>
              <div>
                <dt className="text-xs text-ink-muted">소요 시간</dt>
                <dd className="mt-0.5 text-lg font-bold">{durationLabel(walk.duration_sec)}</dd>
              </div>
            </dl>
            <p className="mt-3 text-center text-xs text-ink-muted">지도에서 출발과 도착 지점을 볼 수 있어요.</p>
            {walk.memo && (
              <p className="mt-3 whitespace-pre-wrap rounded-lg bg-cream p-3 text-sm text-ink-soft" data-testid="shared-memo">
                {walk.memo}
              </p>
            )}
          </Card>
          <a
            href={api.sharedWalkGpxUrl(token)}
            download
            className="inline-flex min-h-12 items-center justify-center gap-2 rounded-lg border border-line bg-white px-5 text-sm font-bold text-ink hover:bg-cream"
          >
            <Download size={18} aria-hidden />
            GPX 다운로드
          </a>
          <p className="text-center text-xs text-ink-muted">
            <Link to="/" className="underline">mungo 둘러보기</Link>
          </p>
        </>
      )}
    </div>
  );
}
