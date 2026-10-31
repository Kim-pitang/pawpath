import { PawPrint, Settings } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import ProfileAvatar from '../components/ProfileAvatar';
import { Card, Chip, EmptyState, ErrorNotice, LinkButton, Loading, PageTitle, SectionTitle } from '../components/ui';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import { dateTimeLabel } from '../lib/format';
import type { FamilyOverview, ProfileBrief } from '../lib/types';

/** 대표 계정의 가족 전체 활동. 구성원별 통계와 가족 반려동물, 최근 산책을 함께 본다. */
export default function FamilyPage() {
  const { account } = useApp();
  const location = useLocation();
  const [overview, setOverview] = useState<FamilyOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.familyOverview().then(setOverview).catch((loadError: Error) => setError(loadError.message));
  }, []);

  // 마이페이지의 구성원별 통계 메뉴는 이 카드로 바로 온다.
  const loaded = overview !== null;
  useEffect(() => {
    if (loaded && location.hash === '#members') document.getElementById('members')?.scrollIntoView();
  }, [loaded, location.hash]);

  if (error) return <ErrorNotice message={error} />;
  if (!overview) return <Loading />;

  const { totals, members } = overview;
  const busiest = Math.max(1, ...members.map((member) => member.activity.walk_count));
  const petName = new Map(overview.pets.map((pet) => [pet.id, pet.name]));

  return (
    <div className="flex flex-col gap-4">
      <PageTitle sub={`${account?.user?.name ?? '시연 보호자'} 계정의 프로필 ${overview.profile_count}개가 함께 남긴 기록이에요. 시연용 산책은 통계에서 뺐어요.`}>가족 산책 기록</PageTitle>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="family-totals">
        <Stat label="가족 산책" value={`${totals.walk_count}번`} />
        <Stat label="총 거리" value={`${totals.total_distance_km.toFixed(1)}km`} />
        <Stat label="총 시간" value={`${totals.total_minutes}분`} />
        <Stat label="저장한 산책길" value={`${totals.saved_walk_count}개`} />
      </div>

      <div className="grid items-start gap-4 md:grid-cols-2">
        <Card>
          <SectionTitle
            action={
              account?.authenticated ? (
                <Link to="/profiles?manage=1" className="flex items-center gap-1 text-xs font-semibold text-leaf-600">
                  <Settings size={13} aria-hidden />
                  관리
                </Link>
              ) : undefined
            }
          >
            <span id="members" className="scroll-mt-20">구성원별 산책 통계</span>
          </SectionTitle>
          <ul className="flex flex-col gap-4" aria-label="구성원별 산책 통계">
            {members.map(({ profile, activity, last_active_at }) => (
              <li key={profile.id} data-testid="family-member">
                <div className="flex items-center gap-3">
                  <ProfileAvatar avatar={profile.avatar_key} size="sm" />
                  <div className="min-w-0 flex-1">
                    <p className="flex items-center gap-1.5 font-bold">
                      <span className="truncate">{profile.name}</span>
                      {profile.is_default && <Chip tone="leaf">대표</Chip>}
                      {profile.deleted && <Chip>지운 프로필</Chip>}
                    </p>
                    <p className="text-xs text-ink-soft">
                      산책 {activity.walk_count}번 · {activity.total_distance_km.toFixed(1)}km · {activity.total_minutes}분 · 산책길 {activity.saved_walk_count}개
                    </p>
                  </div>
                </div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-cream-deep" aria-hidden>
                  <div className="h-full rounded-full bg-leaf-500" style={{ width: `${(activity.walk_count / busiest) * 100}%` }} />
                </div>
                <p className="mt-1 text-xs text-ink-muted">
                  {activity.last_walk_at ? `마지막 산책 ${dateTimeLabel(activity.last_walk_at)}` : '아직 산책 기록이 없어요'}
                  {last_active_at && !profile.deleted && ` · 마지막 이용 ${dateTimeLabel(last_active_at)}`}
                </p>
              </li>
            ))}
          </ul>
        </Card>

        <Card>
          <SectionTitle action={<Link to="/pets" className="text-xs font-semibold text-leaf-600">관리</Link>}>가족 반려동물</SectionTitle>
          {overview.pets.length === 0 ? (
            <EmptyState title="아직 등록된 반려동물이 없어요">
              <LinkButton to="/pets/new" variant="ghost">반려동물 등록하기</LinkButton>
            </EmptyState>
          ) : (
            <ul className="flex flex-col divide-y divide-line">
              {overview.pets.map((pet) => (
                <li key={pet.id} className="flex items-center justify-between gap-2 py-2.5 first:pt-0 last:pb-0">
                  <span className="flex min-w-0 items-center gap-2">
                    <PawPrint size={16} className="shrink-0 text-carrot-500" aria-hidden />
                    <span className="truncate font-semibold">{pet.name}</span>
                    <span className="truncate text-xs text-ink-muted">{pet.breed}</span>
                  </span>
                  <span className="shrink-0 text-xs text-ink-soft">가족 산책 {pet.walk_count}번</span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 text-xs text-ink-muted">반려동물은 가족이 함께 써요. 어느 프로필에서나 고를 수 있고, 피드백으로 배운 취향도 함께 쌓여요.</p>
        </Card>

        <Card className="md:col-span-2">
          <SectionTitle>최근 가족 산책</SectionTitle>
          {overview.recent_walks.length === 0 ? (
            <EmptyState title="아직 가족 산책 기록이 없어요">
              <LinkButton to="/recommend" variant="ghost">오늘의 추천 보기</LinkButton>
            </EmptyState>
          ) : (
            <ul className="flex flex-col divide-y divide-line" aria-label="최근 가족 산책">
              {overview.recent_walks.map((walk) => (
                <li key={walk.id} className="flex items-center gap-3 py-2.5 first:pt-0 last:pb-0">
                  <Who profile={walk.profile ?? null} />
                  <div className="min-w-0 flex-1">
                    <p className="flex items-center gap-1.5 truncate text-sm font-semibold">
                      {walk.course_name}
                      {walk.is_simulated && <Chip>시연용</Chip>}
                    </p>
                    <p className="text-xs text-ink-soft">
                      {walk.profile?.name ?? '알 수 없음'} · {petName.get(walk.pet_id) ?? '반려동물'} · {dateTimeLabel(walk.started_at)} · {walk.duration_min}분
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

function Who({ profile }: { profile: ProfileBrief | null }) {
  return profile ? <ProfileAvatar avatar={profile.avatar_key} size="sm" /> : <span className="h-10 w-10 shrink-0 rounded-2xl bg-cream-deep" aria-hidden />;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-3xl border border-line bg-white p-4">
      <p className="text-xs text-ink-muted">{label}</p>
      <p className="mt-1 text-xl font-bold">{value}</p>
    </div>
  );
}
