import { BadgeCheck, ImagePlus, Pencil, Star, Trash2, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import { dateTimeLabel } from '../lib/format';
import { prepareImage } from '../lib/photos';
import { usePaged } from '../lib/usePaged';
import { useApp } from '../context/AppContext';
import type { TrailDetail, TrailReview } from '../lib/types';
import LoginPrompt from './LoginPrompt';
import { Button, Card, Chip, EmptyState, ErrorNotice, InfoNotice, Loading, SectionTitle } from './ui';

const MAX_REVIEW_PHOTOS = 3;
const MAX_CONTENT = 1000;

export function Stars({ value }: { value: number }) {
  return (
    <span className="inline-flex" role="img" aria-label={`별점 ${value}점`}>
      {[1, 2, 3, 4, 5].map((star) => (
        <Star key={star} size={15} className={star <= value ? 'fill-carrot-500 text-carrot-500' : 'text-line'} aria-hidden />
      ))}
    </span>
  );
}

function StarInput({ value, onChange }: { value: number; onChange: (value: number) => void }) {
  return (
    <fieldset>
      <legend className="mb-1 text-sm font-semibold">별점</legend>
      <div className="flex">
        {[1, 2, 3, 4, 5].map((star) => (
          <button key={star} type="button" aria-label={`${star}점`} aria-pressed={star === value} onClick={() => onChange(star)} className="flex h-11 w-11 items-center justify-center">
            <Star size={26} className={star <= value ? 'fill-carrot-500 text-carrot-500' : 'text-ink-muted'} aria-hidden />
          </button>
        ))}
      </div>
    </fieldset>
  );
}

function ReviewForm({
  review,
  onSubmit,
  onCancel,
}: {
  review: TrailReview | null;
  onSubmit: (body: { rating: number; content: string }, photos: Blob[]) => Promise<void>;
  onCancel?: () => void;
}) {
  const [rating, setRating] = useState(review?.rating ?? 0);
  const [content, setContent] = useState(review?.content ?? '');
  const [photos, setPhotos] = useState<{ blob: Blob; url: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const room = MAX_REVIEW_PHOTOS - (review?.photos.length ?? 0) - photos.length;
  const latest = useRef(photos);
  latest.current = photos;
  useEffect(() => () => latest.current.forEach((photo) => URL.revokeObjectURL(photo.url)), []);

  const addPhotos = async (files: FileList | null) => {
    if (!files?.length) return;
    setError(null);
    const added: { blob: Blob; url: string }[] = [];
    try {
      for (const file of Array.from(files).slice(0, room)) {
        const blob = await prepareImage(file);
        added.push({ blob, url: URL.createObjectURL(blob) });
      }
    } catch (prepareError) {
      setError((prepareError as Error).message);
    }
    setPhotos((current) => [...current, ...added]);
  };

  const removePhoto = (url: string) => {
    URL.revokeObjectURL(url);
    setPhotos((current) => current.filter((photo) => photo.url !== url));
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await onSubmit({ rating, content: content.trim() }, photos.map((photo) => photo.blob));
    } catch (submitError) {
      setError((submitError as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-3" data-testid="review-form">
      <StarInput value={rating} onChange={setRating} />
      <label className="text-sm font-semibold">
        후기
        <textarea
          aria-label="후기 내용"
          maxLength={MAX_CONTENT}
          value={content}
          onChange={(event) => setContent(event.target.value)}
          placeholder="길은 어땠나요? 그늘, 노면, 강아지 반응을 알려 주면 다른 보호자에게 도움이 돼요."
          className="mt-1.5 min-h-24 w-full rounded-2xl border border-line bg-white p-4 text-base font-normal outline-none focus:border-leaf-500"
        />
      </label>
      <div className="flex flex-wrap items-center gap-2">
        {photos.map((photo, index) => (
          <div key={photo.url} className="relative">
            <img src={photo.url} alt={`고른 사진 ${index + 1}`} className="h-16 w-16 rounded-2xl object-cover" data-testid="review-pending-photo" />
            <button
              type="button"
              aria-label={`사진 ${index + 1} 빼기`}
              onClick={() => removePhoto(photo.url)}
              className="absolute -top-1.5 -right-1.5 flex h-7 w-7 items-center justify-center rounded-full bg-ink text-white shadow"
            >
              <X size={14} aria-hidden />
            </button>
          </div>
        ))}
        {room > 0 && (
          <label className="flex h-16 w-16 cursor-pointer flex-col items-center justify-center gap-0.5 rounded-2xl border-2 border-dashed border-line text-[11px] font-semibold text-ink-soft hover:bg-leaf-50">
            <ImagePlus size={18} className="text-leaf-500" aria-hidden />
            사진 추가
            <input type="file" accept="image/*" multiple aria-label="후기 사진 고르기" className="sr-only" onChange={(event) => void addPhotos(event.target.files).then(() => (event.target.value = ''))} />
          </label>
        )}
      </div>
      {error && <ErrorNotice message={error} />}
      <div className={`grid gap-2 ${onCancel ? 'grid-cols-2' : ''}`}>
        {onCancel && (
          <Button variant="ghost" onClick={onCancel}>
            취소
          </Button>
        )}
        <Button onClick={() => void submit()} disabled={busy || rating === 0 || !content.trim()}>
          {busy ? '저장 중이에요' : review ? '후기 고치기' : '후기 남기기'}
        </Button>
      </div>
    </div>
  );
}

/** 산책길 상세의 후기 칸. 후기는 보호자마다 하나이고, 이 길을 GPS로 걸은 기록이 있으면 산책 인증이 붙는다. */
export default function TrailReviews({ trail, onChanged }: { trail: TrailDetail; onChanged: () => Promise<void> }) {
  const { account } = useApp();
  const list = usePaged((page) => api.listReviews(trail.id, page), String(trail.id));
  const [editing, setEditing] = useState<number | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const refresh = async () => {
    await Promise.all([list.reload(), onChanged()]);
  };

  const uploadAll = async (reviewId: number, photos: Blob[]) => {
    let failed = 0;
    for (const photo of photos) {
      try {
        await api.uploadReviewPhoto(reviewId, photo);
      } catch {
        failed += 1;
      }
    }
    // 후기는 이미 저장됐으므로 사진 실패로 되돌리지 않는다.
    setProblem(failed ? `사진 ${failed}장을 올리지 못했어요. 후기를 고쳐 다시 올려 주세요.` : null);
  };

  const create = async (body: { rating: number; content: string }, photos: Blob[]) => {
    const review = await api.createReview(trail.id, body);
    await uploadAll(review.id, photos);
    await refresh();
  };

  const change = async (review: TrailReview, body: { rating: number; content: string }, photos: Blob[]) => {
    await api.updateReview(review.id, body);
    await uploadAll(review.id, photos);
    setEditing(null);
    await refresh();
  };

  const remove = async (review: TrailReview) => {
    if (!window.confirm('후기를 지울까요? 되돌릴 수 없어요.')) return;
    try {
      await api.deleteReview(review.id);
      setProblem(null);
      await refresh();
    } catch (deleteError) {
      setProblem((deleteError as Error).message);
    }
  };

  const removePhoto = async (review: TrailReview, photoId: number) => {
    if (!window.confirm('사진을 지울까요?')) return;
    try {
      await api.deleteReviewPhoto(review.id, photoId);
      await refresh();
    } catch (deleteError) {
      setProblem((deleteError as Error).message);
    }
  };

  const signedIn = account?.authenticated ?? false;
  const canWrite = signedIn && !trail.is_mine && !trail.my_review && trail.visibility === 'public';
  const total = list.data?.total ?? trail.review_count;

  return (
    <section id="reviews" className="flex scroll-mt-20 flex-col gap-3" aria-label="후기">
      <SectionTitle>
        후기 <span className="text-sm font-normal text-ink-muted">{total}개</span>
      </SectionTitle>

      {account && !signedIn && !trail.is_mine && <LoginPrompt title="로그인하면 후기를 남길 수 있어요" />}
      {canWrite && (
        <Card>
          <div className="mb-3">
            {trail.walked ? (
              <InfoNotice>이 산책길을 GPS로 걸은 기록이 있어 후기에 산책 인증이 붙어요.</InfoNotice>
            ) : (
              <p className="text-xs text-ink-muted">아직 이 길을 걷지 않았어도 남길 수 있어요. 이 산책길로 산책을 시작해 GPS로 절반 이상 걸으면 산책 인증이 붙어요.</p>
            )}
          </div>
          <ReviewForm review={null} onSubmit={create} />
        </Card>
      )}
      {trail.is_mine && <p className="text-xs text-ink-muted">내가 공유한 산책길에는 후기를 남길 수 없어요.</p>}

      {problem && <ErrorNotice message={problem} />}
      {list.error && <ErrorNotice message={list.error} />}
      {!list.data && !list.error && <Loading />}
      {list.data?.items.length === 0 && (
        <Card>
          <EmptyState title="아직 후기가 없어요" />
        </Card>
      )}
      {list.data && list.data.items.length > 0 && (
        <ul className="flex flex-col gap-3" aria-label="후기 목록">
          {list.data.items.map((review) => (
            <li key={review.id} className="rounded-3xl border border-line bg-white p-4" data-testid="review-item">
              {editing === review.id ? (
                <ReviewForm review={review} onSubmit={(body, photos) => change(review, body, photos)} onCancel={() => setEditing(null)} />
              ) : (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    <Stars value={review.rating} />
                    {review.verified ? (
                      <Chip tone="leaf">
                        <BadgeCheck size={13} aria-hidden />
                        산책 인증
                      </Chip>
                    ) : (
                      <Chip>일반 후기</Chip>
                    )}
                  </div>
                  <p className="mt-2 text-sm break-words whitespace-pre-wrap" data-testid="review-content">
                    {review.content}
                  </p>
                  <p className="mt-2 text-xs text-ink-muted">
                    {review.author_name} · {dateTimeLabel(review.created_at)}
                    {review.edited && ' · 수정됨'}
                  </p>
                </>
              )}
              {review.photos.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {review.photos.map((photo, index) => (
                    <div key={photo.id} className="relative">
                      <a href={api.reviewPhotoUrl(review.id, photo.id)} target="_blank" rel="noreferrer">
                        <img
                          src={api.reviewPhotoUrl(review.id, photo.id)}
                          alt={`후기 사진 ${index + 1}`}
                          loading="lazy"
                          className="h-20 w-20 rounded-2xl bg-cream-deep object-cover"
                          data-testid="review-photo"
                        />
                      </a>
                      {editing === review.id && (
                        <button
                          type="button"
                          aria-label={`후기 사진 ${index + 1} 지우기`}
                          onClick={() => void removePhoto(review, photo.id)}
                          className="absolute top-1 right-1 flex h-8 w-8 items-center justify-center rounded-full bg-white/90 text-ink shadow"
                        >
                          <Trash2 size={14} aria-hidden />
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {review.is_mine && editing !== review.id && (
                <div className="mt-2 grid grid-cols-2 gap-2">
                  <Button variant="ghost" onClick={() => setEditing(review.id)}>
                    <Pencil size={16} aria-hidden />
                    수정
                  </Button>
                  <Button variant="ghost" onClick={() => void remove(review)}>
                    <Trash2 size={16} aria-hidden />
                    삭제
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {list.data?.has_next && (
        <Button variant="ghost" disabled={list.loadingMore} onClick={() => void list.loadMore()}>
          {list.loadingMore ? '불러오는 중이에요' : '후기 더 보기'}
        </Button>
      )}
    </section>
  );
}
