import { Copy, Download, Link2, Pencil, Share2, Trash2, Unlink, UsersRound } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { Button, Card, Chip, ChoiceGroup, ErrorNotice, InfoNotice, LinkButton, Loading, PageTitle, SectionTitle } from '../components/ui';
import WalkDetailsForm, { PRIVACY_WARNING, type WalkDetailsValue } from '../components/WalkDetailsForm';
import CourseCandidatePanel from '../components/CourseCandidatePanel';
import WalkPhotos from '../components/WalkPhotos';
import WalkRouteMap from '../components/WalkRouteMap';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import { dateTimeLabel, distanceLabel, durationLabel, speedLabel } from '../lib/format';
import { TRAIL_VISIBILITY_LABELS, VISIBILITY_LABELS, WALK_SOURCE_LABELS } from '../lib/labels';
import type { LatLng } from '../lib/navigation';
import type { SavedWalkDetail } from '../lib/types';

const EXPIRY_OPTIONS: { value: number; label: string }[] = [
  { value: 0, label: '기한 없음' },
  { value: 7, label: '7일' },
  { value: 30, label: '30일' },
];

const detailsOf = (walk: SavedWalkDetail): WalkDetailsValue => ({
  title: walk.title,
  petId: walk.pet_id,
  memo: walk.memo,
  visibility: walk.visibility,
  shareMemo: walk.share_memo,
});

export default function MyWalkDetailPage() {
  const { walkId } = useParams();
  const navigate = useNavigate();
  const photoFailures = (useLocation().state as { photoFailures?: number } | null)?.photoFailures ?? 0;
  const [walk, setWalk] = useState<SavedWalkDetail | null>(null);
  const [editing, setEditing] = useState<WalkDetailsValue | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const id = Number(walkId);

  useEffect(() => {
    api.getSavedWalk(id).then(setWalk).catch((loadError: Error) => setError(loadError.message));
  }, [id]);

  const route = useMemo(() => (walk?.route ?? []) as LatLng[][], [walk?.route]);

  if (!walk) return error ? <ErrorNotice message={error} /> : <Loading />;

  const saveEdit = async () => {
    if (!editing) return;
    setSaving(true);
    setError(null);
    try {
      setWalk(
        await api.updateSavedWalk(id, {
          title: editing.title.trim(),
          pet_id: editing.petId,
          memo: editing.memo,
          visibility: editing.visibility,
          share_memo: editing.shareMemo,
        }),
      );
      setEditing(null);
    } catch (saveError) {
      setError((saveError as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    const shared = walk.community_trail ? ' 커뮤니티에 공유한 글과 좋아요, 저장, 후기도 함께 지워져요.' : '';
    if (!window.confirm(`"${walk.title}"을 삭제할까요? 되돌릴 수 없고, 공유 링크도 함께 사라져요.${shared}`)) return;
    try {
      await api.deleteSavedWalk(id);
      navigate('/my-walks', { replace: true });
    } catch (deleteError) {
      setError((deleteError as Error).message);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <PageTitle sub={walk.has_timestamps ? dateTimeLabel(walk.started_at) : `${dateTimeLabel(walk.started_at)} 가져옴 · 파일에 시각 정보가 없어요`}>
        <span data-testid="walk-title">{walk.title}</span>
      </PageTitle>
      {error && <ErrorNotice message={error} />}
      {photoFailures > 0 && <ErrorNotice message={`사진 ${photoFailures}장을 올리지 못했어요. 아래 사진 칸에서 다시 추가해 주세요.`} />}

      <div className="h-72 overflow-hidden rounded-3xl border border-line md:h-96">
        <WalkRouteMap segments={route} />
      </div>

      <Card>
        <dl className="grid grid-cols-3 text-center" data-testid="walk-stats">
          <Info label="거리" value={distanceLabel(walk.distance_m)} />
          <Info label="시간" value={durationLabel(walk.duration_sec)} />
          <Info label="평균 속도" value={speedLabel(walk.average_speed_mps)} />
        </dl>
        <div className="mt-3 flex flex-wrap gap-1.5">
          <Chip tone={walk.visibility === 'private' ? 'neutral' : 'leaf'}>{VISIBILITY_LABELS[walk.visibility]}</Chip>
          <Chip>{WALK_SOURCE_LABELS[walk.source_type]}</Chip>
          {walk.pet_name && <Chip>{walk.pet_name}</Chip>}
          <Chip>지점 {walk.point_count.toLocaleString()}개</Chip>
        </div>
        {walk.memo && <p className="mt-3 whitespace-pre-wrap rounded-2xl bg-cream p-3 text-sm text-ink-soft">{walk.memo}</p>}
      </Card>

      <WalkPhotos walk={walk} onChange={setWalk} />

      <CourseCandidatePanel walk={walk} onChange={setWalk} />

      <a
        href={api.savedWalkGpxUrl(id)}
        download
        className="inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl bg-leaf-500 px-5 text-sm font-bold text-white transition hover:bg-leaf-600"
      >
        <Download size={18} aria-hidden />
        GPX 다운로드
      </a>

      <CommunityPanel walk={walk} />

      <SharePanel walk={walk} onChange={setWalk} onError={setError} />

      {editing ? (
        <Card>
          <SectionTitle>산책길 수정</SectionTitle>
          <WalkDetailsForm value={editing} onChange={setEditing} />
          <div className="mt-4 grid grid-cols-2 gap-2">
            <Button variant="ghost" onClick={() => setEditing(null)}>
              취소
            </Button>
            <Button onClick={saveEdit} disabled={saving || !editing.title.trim()}>
              {saving ? '저장 중이에요' : '저장하기'}
            </Button>
          </div>
        </Card>
      ) : (
        <div className="grid grid-cols-2 gap-2">
          <Button variant="ghost" onClick={() => setEditing(detailsOf(walk))}>
            <Pencil size={16} aria-hidden />
            수정
          </Button>
          <Button variant="ghost" onClick={remove}>
            <Trash2 size={16} aria-hidden />
            삭제
          </Button>
        </div>
      )}

      <Link to="/my-walks" className="min-h-11 text-center text-sm font-semibold text-ink-soft underline">
        나의 산책길 목록으로
      </Link>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-ink-muted">{label}</dt>
      <dd className="mt-0.5 text-base font-bold text-ink">{value}</dd>
    </div>
  );
}

function CommunityPanel({ walk }: { walk: SavedWalkDetail }) {
  const { account } = useApp();
  const trail = walk.community_trail;
  return (
    <Card>
      <SectionTitle action={trail ? <Chip tone={trail.visibility === 'public' ? 'leaf' : 'neutral'}>{TRAIL_VISIBILITY_LABELS[trail.visibility]}</Chip> : undefined}>산책길 커뮤니티</SectionTitle>
      <div data-testid="community-panel">
        {trail ? (
          <>
            <p className="mb-3 text-sm text-ink-soft">커뮤니티에 공유한 산책길이에요. 출발점과 도착점 주변을 가린 경로만 공개돼요.</p>
            <LinkButton to={`/community/trails/${trail.id}`} variant="ghost" className="w-full">
              <UsersRound size={16} aria-hidden />
              공유한 산책길 보기
            </LinkButton>
          </>
        ) : walk.source_type === 'generated' ? (
          <p className="text-sm text-ink-soft">앱이 만들어 준 경로는 아직 아무도 걷지 않은 길이라 공유할 수 없어요. 이 길을 걸으며 기록하면 그 기록을 공유할 수 있어요.</p>
        ) : account?.authenticated ? (
          <>
            <p className="mb-3 text-sm text-ink-soft">이 길을 다른 보호자와 나눠 보세요. 출발점과 도착점 주변은 가리고, 걸은 시각과 메모는 공개되지 않아요.</p>
            <LinkButton to={`/community/share?walk=${walk.id}`} variant="accent" className="w-full">
              <UsersRound size={16} aria-hidden />
              커뮤니티에 공유하기
            </LinkButton>
          </>
        ) : (
          <p className="text-sm text-ink-soft">
            커뮤니티 공유는{' '}
            <Link to="/login" className="font-bold underline">
              로그인
            </Link>
            한 뒤 쓸 수 있어요.
          </p>
        )}
      </div>
    </Card>
  );
}

function SharePanel({ walk, onChange, onError }: { walk: SavedWalkDetail; onChange: (walk: SavedWalkDetail) => void; onError: (message: string) => void }) {
  const [expiry, setExpiry] = useState(0);
  const [shareMemo, setShareMemo] = useState(walk.share_memo);
  const [working, setWorking] = useState(false);
  const [copied, setCopied] = useState(false);

  const expired = walk.share_expires_at !== null && new Date(walk.share_expires_at).getTime() <= Date.now();
  const active = walk.share_token !== null && !expired;
  const url = active ? `${window.location.origin}/shared/${walk.share_token}` : null;

  const run = async (action: () => Promise<SavedWalkDetail>) => {
    setWorking(true);
    try {
      onChange(await action());
      setCopied(false);
    } catch (error) {
      onError((error as Error).message);
    } finally {
      setWorking(false);
    }
  };

  const copy = async () => {
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      // HTTP 접속처럼 클립보드를 쓸 수 없는 환경에서는 링크를 직접 복사하도록 안내한다.
      onError('자동 복사를 쓸 수 없는 환경이에요. 위 링크를 길게 눌러 복사해 주세요.');
    }
  };

  const nativeShare = async () => {
    if (!url) return;
    try {
      await navigator.share({ title: `PawPath 산책길: ${walk.title}`, url });
    } catch {
      // 사용자가 공유 창을 닫은 경우다.
    }
  };

  return (
    <Card>
      <SectionTitle>산책길 공유</SectionTitle>
      <div className="flex flex-col gap-3">
        <ErrorNotice message={PRIVACY_WARNING} />
        {url ? (
          <>
            <input aria-label="공유 링크" readOnly value={url} onFocus={(event) => event.target.select()} className="min-h-11 w-full rounded-2xl border border-line bg-cream px-3 text-xs" />
            {walk.share_expires_at && <p className="text-xs text-ink-muted">{dateTimeLabel(walk.share_expires_at)}까지 열려요.</p>}
            {copied && <InfoNotice>링크를 복사했어요.</InfoNotice>}
            <div className="grid grid-cols-2 gap-2">
              <Button variant="ghost" onClick={copy}>
                <Copy size={16} aria-hidden />
                링크 복사
              </Button>
              {'share' in navigator ? (
                <Button variant="ghost" onClick={nativeShare}>
                  <Share2 size={16} aria-hidden />
                  공유하기
                </Button>
              ) : (
                <Link
                  to={`/shared/${walk.share_token}`}
                  className="inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl border border-line bg-white px-5 text-sm font-bold text-ink hover:bg-cream"
                >
                  공유 화면 보기
                </Link>
              )}
            </div>
            <Button variant="ghost" disabled={working} onClick={() => run(() => api.unshareSavedWalk(walk.id))}>
              <Unlink size={16} aria-hidden />
              공유 링크 해제
            </Button>
          </>
        ) : (
          <>
            {expired && <InfoNotice>공유 기간이 끝났어요. 새 링크를 만들면 예전 링크는 다시 열리지 않아요.</InfoNotice>}
            <ChoiceGroup label="링크 사용 기간" value={expiry} options={EXPIRY_OPTIONS} onChange={setExpiry} />
            <label className="flex min-h-11 items-center gap-2 text-sm font-semibold">
              <input type="checkbox" className="h-5 w-5 accent-leaf-500" checked={shareMemo} onChange={(event) => setShareMemo(event.target.checked)} />
              공유 화면에 메모도 보여 주기
            </label>
            <Button disabled={working} onClick={() => run(() => api.shareSavedWalk(walk.id, { expires_in_days: expiry || null, share_memo: shareMemo }))}>
              <Link2 size={16} aria-hidden />
              공유 링크 만들기
            </Button>
          </>
        )}
      </div>
    </Card>
  );
}
