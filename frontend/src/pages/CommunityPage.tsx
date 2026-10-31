import { Search, Share2 } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import TrailCard from '../components/TrailCard';
import { Button, Card, ChoiceGroup, EmptyState, ErrorNotice, LinkButton, Loading, PageTitle, SectionTitle } from '../components/ui';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import { formatDistance } from '../lib/navigation';
import { TRAIL_DIFFICULTY_LABELS, TRAIL_SUITABLE_LABELS } from '../lib/labels';
import { GPS_MESSAGES } from '../lib/location';
import { usePaged } from '../lib/usePaged';
import type { TrailDifficulty, TrailNearby, TrailQuery, TrailRecommended, TrailSort, TrailSuitable, TrailSummary } from '../lib/types';

type View = 'all' | 'near' | 'foryou';

const PAGE_SIZE = 12;
const NEARBY_RADIUS_KM = 5;
const SEARCH_DELAY_MS = 300;
const POPULAR_COUNT = 6;
const FILTER_CLASS = 'min-h-11 w-full rounded-2xl border border-line bg-white px-3 text-sm';
const SORT_OPTIONS: { value: TrailSort; label: string }[] = [
  { value: 'recent', label: '최신순' },
  { value: 'popular', label: '인기순' },
  { value: 'rating', label: '평점순' },
];
const SORT_TITLES: Record<TrailSort, string> = { recent: '최신 산책길', popular: '인기순 산책길', rating: '평점순 산책길' };
const DISTANCE_BUCKETS: Record<string, { label: string; min_km?: number; max_km?: number }> = {
  short: { label: '2km 미만', max_km: 2 },
  medium: { label: '2~5km', min_km: 2, max_km: 5 },
  long: { label: '5km 이상', min_km: 5 },
};
const DURATION_BUCKETS: Record<string, { label: string; min_minutes?: number; max_minutes?: number }> = {
  short: { label: '30분 미만', max_minutes: 30 },
  medium: { label: '30~60분', min_minutes: 30, max_minutes: 60 },
  long: { label: '60분 이상', min_minutes: 60 },
};
const SELECT_KEYS = ['region', 'distance', 'duration', 'difficulty', 'suitable'];
const FILTER_KEYS = ['q', ...SELECT_KEYS];

export default function CommunityPage() {
  const { selectedPet, petsLoaded } = useApp();
  const [params, setParams] = useSearchParams();
  const view = (params.get('view') as View | null) ?? 'all';
  const sort = (params.get('sort') as TrailSort | null) ?? 'recent';
  const q = params.get('q') ?? '';
  const region = params.get('region') ?? '';
  const distance = params.get('distance') ?? '';
  const duration = params.get('duration') ?? '';
  const difficulty = (params.get('difficulty') ?? '') as TrailDifficulty | '';
  const suitable = (params.get('suitable') ?? '') as TrailSuitable | '';
  const hasFilter = FILTER_KEYS.some((key) => (params.get(key) ?? '').trim() !== '');
  // 고른 필터가 있는 주소로 들어오면 펼쳐 두고, 그 뒤로는 보호자가 여닫은 대로 둔다.
  const [filtersOpen, setFiltersOpen] = useState(() => SELECT_KEYS.some((key) => params.get(key)));

  const update = useCallback(
    (changes: Record<string, string>) => {
      setParams(
        (current) => {
          const next = new URLSearchParams(current);
          Object.entries(changes).forEach(([key, value]) => (value ? next.set(key, value) : next.delete(key)));
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  const [text, setText] = useState(q);
  useEffect(() => setText(q), [q]);
  useEffect(() => {
    if (text === q) return;
    const timer = window.setTimeout(() => update({ q: text }), SEARCH_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [text, q, update]);

  const query = useMemo<TrailQuery>(() => {
    const { label: _distance, ...distanceRange } = DISTANCE_BUCKETS[distance] ?? { label: '' };
    const { label: _duration, ...durationRange } = DURATION_BUCKETS[duration] ?? { label: '' };
    return { q: q.trim(), region, difficulty: difficulty || undefined, suitable: suitable || undefined, sort, ...distanceRange, ...durationRange };
  }, [q, region, distance, duration, difficulty, suitable, sort]);

  const list = usePaged((page) => api.listTrails({ ...query, page, size: PAGE_SIZE }), JSON.stringify(query), view === 'all');

  const [regions, setRegions] = useState<{ region: string; count: number }[]>([]);
  const [popular, setPopular] = useState<TrailSummary[]>([]);
  useEffect(() => {
    api.trailRegions().then(setRegions).catch(() => undefined);
    // 인기 영역은 없어도 목록을 볼 수 있으니 오류를 따로 알리지 않는다.
    api
      .listTrails({ sort: 'popular', size: POPULAR_COUNT })
      .then((page) => setPopular(page.items.filter((trail) => trail.like_count + trail.bookmark_count + trail.review_count > 0)))
      .catch(() => undefined);
  }, []);

  const showPopular = view === 'all' && !hasFilter && sort === 'recent' && popular.length > 0;

  return (
    <div className="flex flex-col gap-4">
      <PageTitle sub="다른 보호자가 실제로 걸은 길을 둘러보고 저장해 보세요.">산책길 커뮤니티</PageTitle>

      <div className="grid grid-cols-2 gap-2">
        <LinkButton to="/community/share" variant="accent" className="!px-2">
          <Share2 size={16} aria-hidden />
          산책길 공유
        </LinkButton>
        <LinkButton to="/community/my" variant="ghost" className="!px-2">
          내 산책길 관리
        </LinkButton>
      </div>

      <form
        role="search"
        className="relative"
        onSubmit={(event) => {
          event.preventDefault();
          update({ q: text });
        }}
      >
        <Search size={18} className="absolute top-1/2 left-4 -translate-y-1/2 text-ink-muted" aria-hidden />
        <input
          type="search"
          aria-label="산책길 검색"
          placeholder="산책길 이름이나 지역으로 찾기"
          maxLength={80}
          value={text}
          onChange={(event) => setText(event.target.value)}
          className="min-h-12 w-full rounded-2xl border border-line bg-white pr-4 pl-11 text-base outline-none focus:border-leaf-500"
        />
      </form>

      <ChoiceGroup
        label="보기"
        value={view}
        options={[
          { value: 'all' as View, label: '전체' },
          { value: 'near' as View, label: '내 주변' },
          { value: 'foryou' as View, label: selectedPet ? `${selectedPet.name} 맞춤` : '맞춤 추천' },
        ]}
        onChange={(next) => update({ view: next === 'all' ? '' : next })}
      />

      {view === 'all' && (
        <>
          <details open={filtersOpen} onToggle={(event) => setFiltersOpen(event.currentTarget.open)} className="rounded-3xl border border-line bg-white p-4" data-testid="trail-filters">
            <summary className="min-h-6 cursor-pointer text-sm font-bold">필터</summary>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <select aria-label="지역별 보기" className={FILTER_CLASS} value={region} onChange={(event) => update({ region: event.target.value })}>
                <option value="">모든 지역</option>
                {regions.map((item) => (
                  <option key={item.region} value={item.region}>
                    {item.region} ({item.count})
                  </option>
                ))}
              </select>
              <select aria-label="거리별 보기" className={FILTER_CLASS} value={distance} onChange={(event) => update({ distance: event.target.value })}>
                <option value="">모든 거리</option>
                {Object.entries(DISTANCE_BUCKETS).map(([key, bucket]) => (
                  <option key={key} value={key}>
                    {bucket.label}
                  </option>
                ))}
              </select>
              <select aria-label="시간별 보기" className={FILTER_CLASS} value={duration} onChange={(event) => update({ duration: event.target.value })}>
                <option value="">모든 시간</option>
                {Object.entries(DURATION_BUCKETS).map(([key, bucket]) => (
                  <option key={key} value={key}>
                    {bucket.label}
                  </option>
                ))}
              </select>
              <select aria-label="난이도별 보기" className={FILTER_CLASS} value={difficulty} onChange={(event) => update({ difficulty: event.target.value })}>
                <option value="">모든 난이도</option>
                {(Object.keys(TRAIL_DIFFICULTY_LABELS) as TrailDifficulty[]).map((key) => (
                  <option key={key} value={key}>
                    {TRAIL_DIFFICULTY_LABELS[key]}
                  </option>
                ))}
              </select>
              <select aria-label="추천 대상별 보기" className={`${FILTER_CLASS} col-span-2`} value={suitable} onChange={(event) => update({ suitable: event.target.value })}>
                <option value="">모든 반려견</option>
                {(Object.keys(TRAIL_SUITABLE_LABELS) as TrailSuitable[]).map((key) => (
                  <option key={key} value={key}>
                    {TRAIL_SUITABLE_LABELS[key]}
                  </option>
                ))}
              </select>
            </div>
          </details>
          <ChoiceGroup label="정렬" value={sort} options={SORT_OPTIONS} onChange={(next) => update({ sort: next === 'recent' ? '' : next })} />
        </>
      )}

      {showPopular && (
        <section aria-label="인기 산책길">
          <SectionTitle>인기 산책길</SectionTitle>
          <ul className="-mx-4 flex snap-x scroll-px-4 gap-3 overflow-x-auto px-4 pb-1 md:mx-0 md:scroll-px-0 md:px-0" data-testid="popular-trails">
            {popular.map((trail) => (
              <li key={trail.id} className="w-72 shrink-0 snap-start">
                <TrailCard trail={trail} className="h-full" />
              </li>
            ))}
          </ul>
        </section>
      )}

      {view === 'all' && (
        <section aria-label={SORT_TITLES[sort]}>
          <SectionTitle>{hasFilter ? '찾은 산책길' : SORT_TITLES[sort]}</SectionTitle>
          {list.error && <ErrorNotice message={list.error} />}
          {!list.data && !list.error && <Loading />}
          {list.data?.items.length === 0 && (
            <Card>
              <EmptyState title={hasFilter ? '조건에 맞는 산책길이 없어요' : '아직 공유된 산책길이 없어요'}>
                {hasFilter ? (
                  <Button variant="ghost" onClick={() => update(Object.fromEntries(FILTER_KEYS.map((key) => [key, ''])))}>
                    조건 지우기
                  </Button>
                ) : (
                  <p className="text-sm text-ink-soft">내가 걸은 길을 첫 번째로 공유해 보세요.</p>
                )}
              </EmptyState>
            </Card>
          )}
          {list.data && list.data.items.length > 0 && (
            <>
              <p className="mb-2 text-xs text-ink-muted" data-testid="trail-total">
                {list.data.total}개
              </p>
              <ul className="grid grid-cols-1 gap-3 md:grid-cols-2" aria-label="산책길 목록">
                {list.data.items.map((trail) => (
                  <li key={trail.id}>
                    <TrailCard trail={trail} />
                  </li>
                ))}
              </ul>
              {list.data.has_next && (
                <Button variant="ghost" className="mt-3 w-full" disabled={list.loadingMore} onClick={() => void list.loadMore()}>
                  {list.loadingMore ? '불러오는 중이에요' : '더 보기'}
                </Button>
              )}
            </>
          )}
        </section>
      )}

      {view === 'near' && <NearbyTrails />}
      {view === 'foryou' &&
        (selectedPet ? (
          <RecommendedTrails key={selectedPet.id} petId={selectedPet.id} petName={selectedPet.name} />
        ) : petsLoaded ? (
          <Card>
            <EmptyState title="반려동물을 등록하면 맞춤 산책길을 골라 드려요">
              <LinkButton to="/pets/new">반려동물 등록하기</LinkButton>
            </EmptyState>
          </Card>
        ) : (
          <Loading />
        ))}
    </div>
  );
}

function NearbyTrails() {
  const [trails, setTrails] = useState<TrailNearby[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!window.isSecureContext) {
      setError(GPS_MESSAGES.insecure ?? null);
      return;
    }
    if (!('geolocation' in navigator)) {
      setError(GPS_MESSAGES.unsupported ?? null);
      return;
    }
    let active = true;
    // 내 주변을 고른 순간에만 위치를 읽고, 서버에 보낸 뒤 저장하지 않는다.
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        api
          .nearbyTrails(coords.latitude, coords.longitude, NEARBY_RADIUS_KM)
          .then((items) => active && setTrails(items))
          .catch((loadError: Error) => active && setError(loadError.message));
      },
      (geoError) => active && setError((geoError.code === 1 ? GPS_MESSAGES.denied : GPS_MESSAGES.unavailable) ?? null),
      { timeout: 10000, maximumAge: 60000 },
    );
    return () => {
      active = false;
    };
  }, []);

  if (error) return <ErrorNotice message={error} />;
  if (!trails) return <Loading label="내 위치를 찾고 있어요" />;
  if (trails.length === 0) {
    return (
      <Card>
        <EmptyState title={`${NEARBY_RADIUS_KM}km 안에 공유된 산책길이 없어요`} />
      </Card>
    );
  }
  return (
    <ul className="grid grid-cols-1 gap-3 md:grid-cols-2" aria-label="내 주변 산책길">
      {trails.map((trail) => (
        <li key={trail.id}>
          <TrailCard trail={trail} footer={<p className="px-1 text-xs font-semibold text-leaf-800">내 위치에서 약 {formatDistance(trail.distance_from_me_m)}</p>} />
        </li>
      ))}
    </ul>
  );
}

function RecommendedTrails({ petId, petName }: { petId: number; petName: string }) {
  const [trails, setTrails] = useState<TrailRecommended[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api
      .recommendedTrails(petId)
      .then((items) => active && setTrails(items))
      .catch((loadError: Error) => active && setError(loadError.message));
    return () => {
      active = false;
    };
  }, [petId]);

  if (error) return <ErrorNotice message={error} />;
  if (!trails) return <Loading />;
  if (trails.length === 0) {
    return (
      <Card>
        <EmptyState title="아직 추천할 산책길이 없어요" />
      </Card>
    );
  }
  return (
    <section aria-label="추천 산책길">
      <p className="mb-2 text-xs text-ink-muted">{petName}의 권장 거리, 보호자가 표시한 추천 대상과 특징, 학습된 취향, 평점으로 골랐어요.</p>
      <ul className="grid grid-cols-1 gap-3 md:grid-cols-2" aria-label="추천 산책길 목록">
        {trails.map((trail) => (
          <li key={trail.id}>
            <TrailCard
              trail={trail}
              footer={
                <div className="px-1 text-xs text-ink-soft" data-testid="trail-reasons">
                  <p className="font-semibold text-leaf-800">맞춤 점수 {trail.match_score}점</p>
                  {trail.reasons.map((reason) => (
                    <p key={reason}>{reason}</p>
                  ))}
                </div>
              }
            />
          </li>
        ))}
      </ul>
    </section>
  );
}
