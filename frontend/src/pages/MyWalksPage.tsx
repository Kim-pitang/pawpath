import { FileUp, Footprints, Globe } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import GuestNotice from '../components/GuestNotice';
import RouteThumbnail from '../components/RouteThumbnail';
import { Card, Chip, ChoiceGroup, EmptyState, ErrorNotice, LinkButton, Loading, PageTitle } from '../components/ui';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import { dateTimeLabel, distanceLabel, durationLabel } from '../lib/format';
import { VISIBILITY_LABELS, WALK_SOURCE_LABELS } from '../lib/labels';
import type { SavedWalkSort, SavedWalkSummary, Visibility } from '../lib/types';

const SORT_OPTIONS: { value: SavedWalkSort; label: string }[] = [
  { value: 'recent', label: '최근 기록순' },
  { value: 'distance', label: '거리순' },
];
const FILTER_CLASS = 'min-h-11 w-full rounded-2xl border border-line bg-white px-3 text-sm';

export default function MyWalksPage() {
  const { pets } = useApp();
  const [walks, setWalks] = useState<SavedWalkSummary[] | null>(null);
  const [sort, setSort] = useState<SavedWalkSort>('recent');
  const [petId, setPetId] = useState<number | null>(null);
  const [visibility, setVisibility] = useState<Visibility | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    setError(null);
    api
      .listSavedWalks({ sort, petId, visibility })
      .then((items) => current && setWalks(items))
      .catch((loadError: Error) => current && setError(loadError.message));
    return () => {
      current = false;
    };
  }, [sort, petId, visibility]);

  const filtered = petId !== null || visibility !== null;

  return (
    <div className="flex flex-col gap-4">
      <PageTitle sub="직접 걸은 길을 모아 두고 GPX 파일이나 링크로 나눌 수 있어요.">나의 산책길</PageTitle>
      <div className="grid grid-cols-2 gap-2">
        <LinkButton to="/record">
          <Footprints size={18} aria-hidden />
          산책 기록 시작
        </LinkButton>
        <LinkButton to="/my-walks/import" variant="ghost">
          <FileUp size={18} aria-hidden />
          GPX 가져오기
        </LinkButton>
      </div>

      <GuestNotice />

      <Card className="flex flex-col gap-3">
        <ChoiceGroup label="정렬" value={sort} options={SORT_OPTIONS} onChange={setSort} />
        <div className="grid grid-cols-2 gap-2">
          <select aria-label="반려동물별 보기" className={FILTER_CLASS} value={petId ?? ''} onChange={(event) => setPetId(Number(event.target.value) || null)}>
            <option value="">모든 반려동물</option>
            {pets.map((pet) => (
              <option key={pet.id} value={pet.id}>
                {pet.name}
              </option>
            ))}
          </select>
          <select
            aria-label="공개 범위별 보기"
            className={FILTER_CLASS}
            value={visibility ?? ''}
            onChange={(event) => setVisibility((event.target.value || null) as Visibility | null)}
          >
            <option value="">모든 공개 범위</option>
            {(Object.keys(VISIBILITY_LABELS) as Visibility[]).map((value) => (
              <option key={value} value={value}>
                {VISIBILITY_LABELS[value]}
              </option>
            ))}
          </select>
        </div>
      </Card>

      {error && <ErrorNotice message={error} />}
      {!walks && !error && <Loading />}
      {walks?.length === 0 && (
        <Card>
          <EmptyState title={filtered ? '조건에 맞는 산책길이 없어요' : '아직 저장한 산책길이 없어요'}>
            {!filtered && <p className="text-sm text-ink-soft">산책을 기록하거나 GPX 파일을 가져와 보세요.</p>}
          </EmptyState>
        </Card>
      )}
      {walks && walks.length > 0 && (
        <ul className="flex flex-col gap-3" aria-label="나의 산책길 목록">
          {walks.map((walk) => (
            <li key={walk.id}>
              <Link to={`/my-walks/${walk.id}`} className="flex items-center gap-3 rounded-3xl border border-line bg-white p-3 transition hover:bg-leaf-50" data-testid="saved-walk-card">
                <RouteThumbnail segments={walk.preview} label={`${walk.title} 경로`} />
                <div className="min-w-0 flex-1">
                  <h2 className="truncate font-bold">{walk.title}</h2>
                  <p className="mt-0.5 text-xs text-ink-soft">
                    {walk.has_timestamps ? dateTimeLabel(walk.started_at) : `${dateTimeLabel(walk.started_at)} 가져옴`}
                    {walk.pet_name && ` · ${walk.pet_name}`}
                  </p>
                  <p className="mt-1 text-sm font-semibold text-ink">
                    {distanceLabel(walk.distance_m)} · {durationLabel(walk.duration_sec)}
                  </p>
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    <Chip tone={walk.visibility === 'private' ? 'neutral' : 'leaf'}>{VISIBILITY_LABELS[walk.visibility]}</Chip>
                    <Chip>{WALK_SOURCE_LABELS[walk.source_type]}</Chip>
                  </div>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}

      <Link to="/public-walks" className="flex min-h-11 items-center justify-center gap-1.5 text-sm font-semibold text-leaf-800 underline">
        <Globe size={16} aria-hidden />
        공개된 산책길 둘러보기
      </Link>
    </div>
  );
}
