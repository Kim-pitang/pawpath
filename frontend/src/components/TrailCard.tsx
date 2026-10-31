import { Heart, Star } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import { distanceLabel } from '../lib/format';
import type { TrailSummary } from '../lib/types';
import RouteThumbnail from './RouteThumbnail';

const THUMB_SIZE = 88;

/** 커뮤니티 카드. 대표 이미지가 없으면 지도 타일을 받지 않는 경로 그림을 쓴다. */
export default function TrailCard({ trail, footer, className = '' }: { trail: TrailSummary; footer?: ReactNode; className?: string }) {
  return (
    <div className={`flex flex-col gap-2 rounded-3xl border border-line bg-white p-3 ${className}`} data-testid="trail-card">
      <Link to={`/community/trails/${trail.id}`} className="flex items-center gap-3 rounded-2xl transition hover:bg-leaf-50">
        {trail.cover_photo_id ? (
          <img
            src={api.trailCoverUrl(trail.id, trail.cover_photo_id)}
            alt={`${trail.title} 대표 이미지`}
            loading="lazy"
            width={THUMB_SIZE}
            height={THUMB_SIZE}
            className="shrink-0 rounded-2xl bg-cream-deep object-cover"
            style={{ width: THUMB_SIZE, height: THUMB_SIZE }}
            data-testid="trail-cover"
          />
        ) : (
          <RouteThumbnail segments={trail.preview} label={`${trail.title} 경로`} size={THUMB_SIZE} />
        )}
        <div className="min-w-0 flex-1">
          <h3 className="truncate font-bold" data-testid="trail-card-title">
            {trail.title}
          </h3>
          <p className="mt-0.5 truncate text-xs text-ink-soft">
            {trail.author_name} · {trail.region}
          </p>
          <p className="mt-1 text-sm font-semibold text-ink">
            {distanceLabel(trail.distance_m)} · 약 {trail.estimated_min}분
          </p>
          <p className="mt-1 flex items-center gap-3 text-xs text-ink-soft">
            <span className="inline-flex items-center gap-1" aria-label={`좋아요 ${trail.like_count}개`}>
              <Heart size={13} className={trail.liked ? 'fill-carrot-500 text-carrot-500' : ''} aria-hidden />
              {trail.like_count}
            </span>
            <span className="inline-flex items-center gap-1">
              <Star size={13} className={trail.average_rating === null ? '' : 'fill-carrot-300 text-carrot-300'} aria-hidden />
              {trail.average_rating === null ? '후기 없음' : `${trail.average_rating.toFixed(1)} (${trail.review_count})`}
            </span>
          </p>
        </div>
      </Link>
      {footer}
    </div>
  );
}
