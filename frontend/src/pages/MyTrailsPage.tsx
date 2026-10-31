import { Lock, Pencil, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import LoginPrompt from '../components/LoginPrompt';
import TrailCard from '../components/TrailCard';
import { Stars } from '../components/TrailReviews';
import { Button, Card, Chip, ChoiceGroup, EmptyState, ErrorNotice, InfoNotice, LinkButton, Loading, PageTitle } from '../components/ui';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import { dateTimeLabel } from '../lib/format';
import { TRAIL_VISIBILITY_LABELS } from '../lib/labels';
import { usePaged } from '../lib/usePaged';
import type { MyTrailReview, TrailSummary, TrailVisibility } from '../lib/types';

type Tab = 'trails' | 'bookmarks' | 'likes' | 'reviews';

const TABS: { value: Tab; label: string }[] = [
  { value: 'trails', label: '공유한 산책길' },
  { value: 'bookmarks', label: '저장한 산책길' },
  { value: 'reviews', label: '작성한 후기' },
  { value: 'likes', label: '좋아요한 산책길' },
];

/** 커뮤니티 활동을 모아 보는 화면. 다른 보호자의 활동은 서버가 애초에 돌려주지 않는다. */
export default function MyTrailsPage() {
  const { account } = useApp();
  const [params, setParams] = useSearchParams();
  const tab = (params.get('tab') as Tab | null) ?? 'trails';

  if (!account) return <Loading />;
  return (
    <div className="flex flex-col gap-4">
      <PageTitle sub="공유한 길의 공개 상태를 바꾸고, 저장한 길과 후기를 모아 봐요.">내 산책길 관리</PageTitle>
      {!account.authenticated ? (
        <LoginPrompt title="로그인하면 공유하고 저장한 산책길을 관리할 수 있어요" />
      ) : (
        <>
          <ChoiceGroup label="보기" value={tab} options={TABS} onChange={(next) => setParams(next === 'trails' ? {} : { tab: next }, { replace: true })} />
          {tab === 'trails' && <SharedTrails />}
          {tab === 'bookmarks' && <ReactedTrails key="bookmarks" load={api.myBookmarks} empty="아직 저장한 산책길이 없어요" hiddenWord="저장한" />}
          {tab === 'likes' && <ReactedTrails key="likes" load={api.myLikes} empty="아직 좋아요한 산책길이 없어요" hiddenWord="좋아요한" />}
          {tab === 'reviews' && <MyReviews />}
        </>
      )}
    </div>
  );
}

function Empty({ title }: { title: string }) {
  return (
    <Card>
      <EmptyState title={title}>
        <LinkButton to="/community" variant="ghost">
          커뮤니티 둘러보기
        </LinkButton>
      </EmptyState>
    </Card>
  );
}

function SharedTrails() {
  const list = usePaged((page) => api.myTrails(page), 'trails');
  const [problem, setProblem] = useState<string | null>(null);
  const [working, setWorking] = useState<number | null>(null);

  const replace = (next: TrailSummary) =>
    list.setData((current) => current && { ...current, items: current.items.map((item) => (item.id === next.id ? next : item)) });

  const setVisibility = async (trail: TrailSummary, visibility: TrailVisibility) => {
    setWorking(trail.id);
    setProblem(null);
    try {
      replace(await api.updateTrail(trail.id, { visibility }));
    } catch (failure) {
      setProblem((failure as Error).message);
    } finally {
      setWorking(null);
    }
  };

  const unshare = async (trail: TrailSummary) => {
    if (!window.confirm(`"${trail.title}" 공유를 해제할까요? 좋아요, 저장, 후기가 함께 지워져요. 내 산책길 원본은 남아요.`)) return;
    setWorking(trail.id);
    setProblem(null);
    try {
      await api.deleteTrail(trail.id);
      await list.reload();
    } catch (failure) {
      setProblem((failure as Error).message);
    } finally {
      setWorking(null);
    }
  };

  if (list.error) return <ErrorNotice message={list.error} />;
  if (!list.data) return <Loading />;
  if (list.data.items.length === 0) {
    return (
      <Card>
        <EmptyState title="아직 공유한 산책길이 없어요">
          <LinkButton to="/community/share">산책길 공유하기</LinkButton>
        </EmptyState>
      </Card>
    );
  }
  return (
    <>
      {problem && <ErrorNotice message={problem} />}
      <ul className="grid grid-cols-1 gap-3 md:grid-cols-2" aria-label="공유한 산책길">
        {list.data.items.map((trail) => (
          <li key={trail.id}>
            <TrailCard
              trail={trail}
              footer={
                <div className="flex flex-col gap-2" data-testid="my-trail-actions">
                  <div>
                    <Chip tone={trail.visibility === 'public' ? 'leaf' : 'neutral'}>{TRAIL_VISIBILITY_LABELS[trail.visibility]}</Chip>
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    <Button variant="ghost" className="!px-1 text-xs" disabled={working === trail.id} onClick={() => void setVisibility(trail, trail.visibility === 'public' ? 'private' : 'public')}>
                      <Lock size={14} aria-hidden />
                      {trail.visibility === 'public' ? '비공개로' : '공개로'}
                    </Button>
                    <LinkButton to={`/community/trails/${trail.id}/edit`} variant="ghost" className="!px-1 text-xs">
                      <Pencil size={14} aria-hidden />
                      수정
                    </LinkButton>
                    <Button variant="ghost" className="!px-1 text-xs" disabled={working === trail.id} onClick={() => void unshare(trail)}>
                      <Trash2 size={14} aria-hidden />
                      공유 해제
                    </Button>
                  </div>
                </div>
              }
            />
          </li>
        ))}
      </ul>
      {list.data.has_next && (
        <Button variant="ghost" disabled={list.loadingMore} onClick={() => void list.loadMore()}>
          더 보기
        </Button>
      )}
    </>
  );
}

function ReactedTrails({ load, empty, hiddenWord }: { load: typeof api.myBookmarks; empty: string; hiddenWord: string }) {
  const list = usePaged((page) => load(page), hiddenWord);
  if (list.error) return <ErrorNotice message={list.error} />;
  if (!list.data) return <Loading />;
  const hidden = list.data.hidden_count;
  return (
    <>
      {hidden > 0 && <InfoNotice>{hiddenWord} 산책길 {hidden}개는 작성자가 비공개로 돌려 지금은 볼 수 없어요. 다시 공개되면 돌아와요.</InfoNotice>}
      {list.data.items.length === 0 ? (
        <Empty title={empty} />
      ) : (
        <ul className="grid grid-cols-1 gap-3 md:grid-cols-2" aria-label={`${hiddenWord} 산책길`}>
          {list.data.items.map((trail) => (
            <li key={trail.id}>
              <TrailCard trail={trail} />
            </li>
          ))}
        </ul>
      )}
      {list.data.has_next && (
        <Button variant="ghost" disabled={list.loadingMore} onClick={() => void list.loadMore()}>
          더 보기
        </Button>
      )}
    </>
  );
}

function MyReviews() {
  const list = usePaged((page) => api.myReviews(page), 'reviews');
  const [problem, setProblem] = useState<string | null>(null);

  const remove = async (review: MyTrailReview) => {
    if (!window.confirm('후기를 지울까요? 되돌릴 수 없어요.')) return;
    setProblem(null);
    try {
      await api.deleteReview(review.id);
      await list.reload();
    } catch (failure) {
      setProblem((failure as Error).message);
    }
  };

  if (list.error) return <ErrorNotice message={list.error} />;
  if (!list.data) return <Loading />;
  if (list.data.items.length === 0) return <Empty title="아직 작성한 후기가 없어요" />;
  return (
    <>
      {problem && <ErrorNotice message={problem} />}
      <ul className="flex flex-col gap-3" aria-label="작성한 후기">
        {list.data.items.map((review) => (
          <li key={review.id} className="rounded-3xl border border-line bg-white p-4" data-testid="my-review">
            {review.trail_available ? (
              <Link to={`/community/trails/${review.trail_id}#reviews`} className="font-bold underline">
                {review.trail_title}
              </Link>
            ) : (
              <p className="text-sm font-semibold text-ink-muted">작성자가 비공개로 돌린 산책길이에요</p>
            )}
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <Stars value={review.rating} />
              {review.verified && <Chip tone="leaf">산책 인증</Chip>}
            </div>
            <p className="mt-2 text-sm break-words whitespace-pre-wrap">{review.content}</p>
            <p className="mt-2 text-xs text-ink-muted">{dateTimeLabel(review.created_at)}</p>
            <Button variant="ghost" className="mt-2 w-full" onClick={() => void remove(review)}>
              <Trash2 size={16} aria-hidden />
              후기 삭제
            </Button>
          </li>
        ))}
      </ul>
      {list.data.has_next && (
        <Button variant="ghost" disabled={list.loadingMore} onClick={() => void list.loadMore()}>
          더 보기
        </Button>
      )}
    </>
  );
}
