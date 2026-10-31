import { Bookmark, Download, Eye, Footprints, Heart, Link2, Lock, Pencil, Star, Trash2, UserRound } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import TrailReviews from '../components/TrailReviews';
import { Button, Card, Chip, EmptyState, ErrorNotice, InfoNotice, LinkButton, Loading } from '../components/ui';
import WalkRouteMap from '../components/WalkRouteMap';
import { useApp } from '../context/AppContext';
import { ApiError, api } from '../lib/api';
import { dateLabel, distanceLabel } from '../lib/format';
import { TRAIL_DIFFICULTY_LABELS, TRAIL_FEATURE_LABELS, TRAIL_SUITABLE_LABELS, TRAIL_VISIBILITY_LABELS } from '../lib/labels';
import type { LatLng } from '../lib/navigation';
import type { TrailDetail, TrailVisibility } from '../lib/types';

const VIEWED_KEY = 'pawpath.trailViewed.';

export default function TrailDetailPage() {
  const { trailId } = useParams();
  const id = Number(trailId);
  const navigate = useNavigate();
  const location = useLocation();
  const { account } = useApp();
  const [trail, setTrail] = useState<TrailDetail | null>(null);
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reacting, setReacting] = useState<'like' | 'bookmark' | null>(null);

  const load = useCallback(async () => {
    setTrail(await api.getTrail(id));
  }, [id]);

  useEffect(() => {
    setTrail(null);
    setLoadError(null);
    load().catch((failure: ApiError) => setLoadError(failure));
  }, [id, load, account?.user?.id]);

  // 조회수는 세션마다 보는 사람별로 한 번만 올린다. 주인이 먼저 열어도 다른 보호자의 조회는 센다.
  // 새로고침과 StrictMode의 이중 실행에 부풀지 않게 먼저 표시해 두고, 누가 보는지 알 때까지 기다린다.
  const viewerKey = account ? (account.user?.id ?? 'guest') : null;
  useEffect(() => {
    if (viewerKey === null || !Number.isFinite(id)) return;
    const key = `${VIEWED_KEY}${id}.${viewerKey}`;
    if (sessionStorage.getItem(key)) return;
    sessionStorage.setItem(key, '1');
    api.viewTrail(id).catch(() => undefined);
  }, [id, viewerKey]);

  // 산책을 마치고 후기 칸으로 바로 왔을 때 지도와 정보를 건너뛴다.
  const loaded = trail !== null;
  useEffect(() => {
    if (loaded && location.hash === '#reviews') document.getElementById('reviews')?.scrollIntoView();
  }, [loaded, location.hash]);

  const route = useMemo(() => (trail?.route ?? []) as LatLng[][], [trail?.route]);

  if (loadError) {
    return (
      <Card>
        <EmptyState title={loadError.status === 404 ? '찾을 수 없는 산책길이에요' : loadError.message}>
          {loadError.status === 404 && <p className="text-sm text-ink-soft">공유가 해제되었거나 작성자가 비공개로 돌렸을 수 있어요.</p>}
          <LinkButton to="/community" variant="ghost">
            커뮤니티로 돌아가기
          </LinkButton>
        </EmptyState>
      </Card>
    );
  }
  if (!trail) return <Loading />;

  const signedIn = account?.authenticated ?? false;
  const goLogin = () => navigate('/login', { state: { from: location.pathname + location.search } });

  /** 누르는 즉시 화면을 바꾸고, 실패하면 되돌린다. */
  const toggleLike = async () => {
    if (!signedIn) return goLogin();
    if (reacting) return;
    const previous = trail;
    const on = !trail.liked;
    setTrail({ ...trail, liked: on, like_count: trail.like_count + (on ? 1 : -1) });
    setReacting('like');
    setError(null);
    try {
      const state = await api.setTrailLike(trail.id, on);
      setTrail((current) => current && { ...current, ...state });
    } catch (failure) {
      setTrail(previous);
      setError((failure as Error).message);
    } finally {
      setReacting(null);
    }
  };

  const toggleBookmark = async () => {
    if (!signedIn) return goLogin();
    if (reacting) return;
    const previous = trail;
    const on = !trail.bookmarked;
    setTrail({ ...trail, bookmarked: on, bookmark_count: trail.bookmark_count + (on ? 1 : -1) });
    setReacting('bookmark');
    setError(null);
    try {
      const state = await api.setTrailBookmark(trail.id, on);
      setTrail((current) => current && { ...current, ...state });
      setNotice(on ? '내 산책길 관리의 저장한 산책길에 담았어요.' : null);
    } catch (failure) {
      setTrail(previous);
      setError((failure as Error).message);
    } finally {
      setReacting(null);
    }
  };

  const startWalk = async () => {
    setBusy(true);
    setError(null);
    try {
      const { course_id } = await api.startTrail(trail.id);
      navigate(`/navigate?course=${course_id}`);
    } catch (failure) {
      setError((failure as Error).message);
      setBusy(false);
    }
  };

  const shareLink = async () => {
    const url = `${window.location.origin}/community/trails/${trail.id}`;
    setError(null);
    if ('share' in navigator) {
      try {
        await navigator.share({ title: `PawPath 산책길: ${trail.title}`, url });
        return;
      } catch (failure) {
        // 사용자가 공유 창을 닫은 경우다. 공유를 못 쓰는 환경이면 복사로 넘어간다.
        if ((failure as Error).name === 'AbortError') return;
      }
    }
    try {
      await navigator.clipboard.writeText(url);
      setNotice('링크를 복사했어요.');
    } catch {
      setNotice(`이 주소를 복사해 주세요: ${url}`);
    }
  };

  const setVisibility = async (visibility: TrailVisibility) => {
    setBusy(true);
    setError(null);
    try {
      setTrail(await api.updateTrail(trail.id, { visibility }));
      setNotice(visibility === 'public' ? '커뮤니티에 다시 공개했어요.' : '비공개로 돌렸어요. 나만 볼 수 있어요.');
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const unshare = async () => {
    if (!window.confirm(`"${trail.title}" 공유를 해제할까요? 좋아요, 저장, 후기가 함께 지워져요. 내 산책길 원본은 남아요.`)) return;
    setBusy(true);
    try {
      await api.deleteTrail(trail.id);
      navigate('/community/my', { replace: true });
    } catch (failure) {
      setError((failure as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <Link to="/community" className="text-sm font-semibold text-ink-soft underline">
        커뮤니티로 돌아가기
      </Link>

      {trail.cover_photo_id && (
        <img
          src={api.trailCoverUrl(trail.id, trail.cover_photo_id)}
          alt={`${trail.title} 대표 이미지`}
          className="aspect-video w-full rounded-3xl border border-line bg-cream-deep object-cover"
          data-testid="trail-hero"
        />
      )}

      <div>
        <h1 className="font-brand text-2xl break-words text-leaf-800" data-testid="trail-title">
          {trail.title}
        </h1>
        <p className="mt-1 flex flex-wrap items-center gap-x-2 text-sm text-ink-soft">
          <span className="inline-flex items-center gap-1 font-semibold" data-testid="trail-author">
            <UserRound size={15} aria-hidden />
            {trail.author_name}
          </span>
          <span>{trail.region}</span>
          <span>{dateLabel(new Date(trail.created_at))} 공유</span>
        </p>
        {trail.description && (
          <p className="mt-2 text-sm break-words whitespace-pre-wrap" data-testid="trail-description">
            {trail.description}
          </p>
        )}
      </div>

      {trail.visibility === 'private' && <InfoNotice>비공개 산책길이에요. 나만 볼 수 있어요.</InfoNotice>}
      {notice && <InfoNotice>{notice}</InfoNotice>}
      {error && <ErrorNotice message={error} />}

      <div className="h-72 overflow-hidden rounded-3xl border border-line md:h-96">
        <WalkRouteMap segments={route} />
      </div>
      <p className="-mt-2 text-xs text-ink-muted">개인정보를 지키려고 실제 출발점과 도착점 주변은 지도와 GPX에서 빼고 공개해요.</p>

      <Card>
        <dl className="grid grid-cols-2 gap-y-3 text-center md:grid-cols-4" data-testid="trail-stats">
          <Stat label="총 거리" value={distanceLabel(trail.distance_m)} />
          <Stat label="예상 시간" value={`약 ${trail.estimated_min}분`} />
          <Stat label="오르막 누적" value={trail.elevation_gain_m === null ? '기록 없음' : `${Math.round(trail.elevation_gain_m)}m`} />
          <Stat label={trail.elevation_gain_m === null ? '난이도(거리 기준)' : '난이도(거리·고도 기준)'} value={TRAIL_DIFFICULTY_LABELS[trail.difficulty]} />
        </dl>
        <dl className="mt-3 grid gap-1 border-t border-line pt-3 text-sm">
          <div className="flex gap-2">
            <dt className="shrink-0 font-semibold text-leaf-800">출발</dt>
            <dd className="min-w-0 text-ink-soft">{trail.start_label ?? '지도의 출발 표시를 확인해 주세요'}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="shrink-0 font-semibold text-carrot-700">도착</dt>
            <dd className="min-w-0 text-ink-soft">{trail.end_label ?? '지도의 도착 표시를 확인해 주세요'}</dd>
          </div>
        </dl>
        {trail.features.length + trail.suitable_for.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5" data-testid="trail-tags">
            {trail.features.map((tag) => (
              <Chip key={tag} tone="leaf">
                {TRAIL_FEATURE_LABELS[tag]}
              </Chip>
            ))}
            {trail.suitable_for.map((tag) => (
              <Chip key={tag} tone="carrot">
                {TRAIL_SUITABLE_LABELS[tag]} 추천
              </Chip>
            ))}
          </div>
        )}
        <p className="mt-3 flex flex-wrap items-center gap-3 text-xs text-ink-soft" data-testid="trail-counters">
          <span className="inline-flex items-center gap-1">
            <Eye size={13} aria-hidden />
            조회 {trail.view_count}
          </span>
          <span className="inline-flex items-center gap-1">
            <Star size={13} aria-hidden />
            {trail.average_rating === null ? '평점 없음' : `평균 ${trail.average_rating.toFixed(1)}점 (${trail.review_count})`}
          </span>
        </p>
      </Card>

      <div className="grid grid-cols-2 gap-2">
        <button
          type="button"
          aria-pressed={trail.liked}
          onClick={() => void toggleLike()}
          data-testid="like-button"
          className={`inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl border px-3 text-sm font-bold transition ${
            trail.liked ? 'border-carrot-500 bg-carrot-50 text-carrot-700' : 'border-line bg-white text-ink hover:bg-cream'
          }`}
        >
          <Heart size={18} className={trail.liked ? 'fill-carrot-500 text-carrot-500' : ''} aria-hidden />
          좋아요 {trail.like_count}
        </button>
        <button
          type="button"
          aria-pressed={trail.bookmarked}
          onClick={() => void toggleBookmark()}
          data-testid="bookmark-button"
          className={`inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl border px-3 text-sm font-bold transition ${
            trail.bookmarked ? 'border-leaf-500 bg-leaf-50 text-leaf-800' : 'border-line bg-white text-ink hover:bg-cream'
          }`}
        >
          <Bookmark size={18} className={trail.bookmarked ? 'fill-leaf-500 text-leaf-500' : ''} aria-hidden />
          저장 {trail.bookmark_count}
        </button>
      </div>
      {!signedIn && account && <p className="-mt-2 text-xs text-ink-muted">좋아요와 저장은 로그인하면 쓸 수 있어요.</p>}

      {trail.can_navigate ? (
        <Button onClick={() => void startWalk()} disabled={busy}>
          <Footprints size={18} aria-hidden />이 산책길로 산책 시작
        </Button>
      ) : (
        <InfoNotice>끊긴 구간이 있어 길 안내를 할 수 없어요. 지도와 GPX로 확인해 주세요.</InfoNotice>
      )}

      <div className="grid grid-cols-2 gap-2">
        <a
          href={api.trailGpxUrl(trail.id)}
          download
          className="inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl border border-line bg-white px-3 text-sm font-bold text-ink hover:bg-cream"
        >
          <Download size={18} aria-hidden />
          GPX 다운로드
        </a>
        <Button variant="ghost" onClick={() => void shareLink()} disabled={trail.visibility === 'private'} className="!px-3">
          <Link2 size={18} aria-hidden />
          링크 공유
        </Button>
      </div>

      {trail.is_mine && trail.owner && (
        <Card>
          <h2 className="mb-1 text-base font-bold">내가 공유한 산책길</h2>
          <p className="mb-3 text-xs text-ink-muted">
            지금 {TRAIL_VISIBILITY_LABELS[trail.visibility]} · 출발점과 도착점 주변 {trail.owner.hide_radius_m}m를 가려요 ·{' '}
            <Link to={`/my-walks/${trail.owner.saved_walk_id}`} className="underline">
              원본 산책길
            </Link>
          </p>
          <div className="grid grid-cols-2 gap-2">
            <LinkButton to={`/community/trails/${trail.id}/edit`} variant="ghost" className="!px-2">
              <Pencil size={16} aria-hidden />
              수정
            </LinkButton>
            <Button variant="ghost" disabled={busy} className="!px-2" onClick={() => void setVisibility(trail.visibility === 'public' ? 'private' : 'public')}>
              <Lock size={16} aria-hidden />
              {trail.visibility === 'public' ? '비공개로 돌리기' : '다시 공개하기'}
            </Button>
          </div>
          <Button variant="ghost" disabled={busy} className="mt-2 w-full" onClick={() => void unshare()}>
            <Trash2 size={16} aria-hidden />
            공유 해제
          </Button>
        </Card>
      )}

      <TrailReviews trail={trail} onChanged={load} />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-ink-muted">{label}</dt>
      <dd className="mt-0.5 text-base font-bold text-ink">{value}</dd>
    </div>
  );
}
