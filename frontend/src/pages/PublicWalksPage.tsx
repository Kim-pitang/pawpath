import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import RouteThumbnail from '../components/RouteThumbnail';
import { Card, EmptyState, ErrorNotice, Loading, PageTitle } from '../components/ui';
import { api } from '../lib/api';
import { distanceLabel, durationLabel } from '../lib/format';
import type { PublicWalk } from '../lib/types';

export default function PublicWalksPage() {
  const [walks, setWalks] = useState<PublicWalk[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listPublicWalks().then(setWalks).catch((loadError: Error) => setError(loadError.message));
  }, []);

  return (
    <div className="flex flex-col gap-4">
      <PageTitle sub="공개로 설정한 산책길이에요. 시각과 반려동물 정보는 보이지 않아요.">공개된 산책길</PageTitle>
      {error && <ErrorNotice message={error} />}
      {!walks && !error && <Loading />}
      {walks?.length === 0 && (
        <Card>
          <EmptyState title="아직 공개된 산책길이 없어요" />
        </Card>
      )}
      {walks && walks.length > 0 && (
        <ul className="flex flex-col gap-3" aria-label="공개된 산책길 목록">
          {walks.map((walk) => (
            <li key={walk.token}>
              <Link to={`/shared/${walk.token}`} className="flex items-center gap-3 rounded-xl border border-line bg-white p-3 transition hover:bg-cream">
                <RouteThumbnail segments={walk.preview} label={`${walk.title} 경로`} />
                <div className="min-w-0 flex-1">
                  <h2 className="truncate font-bold">{walk.title}</h2>
                  <p className="mt-1 text-sm font-semibold text-ink">
                    {distanceLabel(walk.distance_m)} · {durationLabel(walk.duration_sec)}
                  </p>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
