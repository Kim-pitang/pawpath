import { Check, LogOut, Pencil, Plus } from 'lucide-react';
import { useState } from 'react';
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { PawPathMark, Wordmark } from '../components/Logo';
import ProfileAvatar from '../components/ProfileAvatar';
import { Button, ErrorNotice, Loading } from '../components/ui';
import { useApp } from '../context/AppContext';
import { safeNext } from '../lib/navigation-paths';
import { clearDraft, loadDraft } from '../lib/recording';
import type { Profile } from '../lib/types';

const CARD_CLASS = 'group flex flex-col items-center gap-3 rounded-3xl p-3 text-center outline-none transition focus-visible:ring-2 focus-visible:ring-leaf-500';
const AVATAR_HOVER = 'ring-leaf-300 transition group-hover:-translate-y-1 group-hover:ring-4 group-hover:shadow-[0_8px_24px_rgb(120_90_40/0.18)] group-focus-visible:ring-4';

/** 넷플릭스처럼 누구의 산책인지 고르는 화면. manage=1이면 프로필을 고치는 화면이 된다. */
export default function ProfilesPage() {
  const { account, profiles, currentProfile, switchProfile, signOut } = useApp();
  const navigate = useNavigate();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const managing = params.get('manage') === '1';
  const from = safeNext((location.state as { from?: string } | null)?.from);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!account) return <Loading />;
  if (!account.authenticated) return <Navigate to="/login" replace state={{ from: '/profiles' }} />;

  const max = account.max_profiles ?? 5;
  const choose = async (profile: Profile) => {
    setBusy(profile.id);
    setError(null);
    try {
      if (await switchProfile(profile.id)) navigate(from, { replace: true });
      else setBusy(null);
    } catch (chooseError) {
      setError((chooseError as Error).message);
      setBusy(null);
    }
  };

  const logout = async () => {
    if (loadDraft() && !window.confirm('저장하지 않은 산책 기록이 있어요. 로그아웃하면 이 기기에서 지워져요.')) return;
    clearDraft();
    await signOut();
    navigate('/login', { replace: true });
  };

  return (
    <div className="mx-auto flex min-h-dvh max-w-3xl flex-col items-center gap-6 p-4 pb-10">
      <header className="flex w-full items-center gap-2">
        <PawPathMark />
        <Wordmark compact />
      </header>
      <div className="mt-4 text-center md:mt-12">
        <h1 className="font-brand text-3xl text-leaf-800 md:text-4xl">{managing ? '프로필 관리' : '누구의 산책을 기록할까요?'}</h1>
        <p className="mt-2 text-sm text-ink-soft">
          {managing ? '고칠 프로필을 골라 주세요.' : `${account.user?.name ?? ''} 계정의 가족 프로필이에요. 반려동물은 함께 쓰고, 산책 기록은 프로필마다 남아요.`}
        </p>
      </div>
      {error && <ErrorNotice message={error} />}

      <ul className="grid w-full max-w-2xl grid-cols-2 gap-x-3 gap-y-5 sm:grid-cols-3" aria-label="프로필 목록">
        {profiles.map((profile) => {
          const label = (
            <>
              <span className="relative">
                <ProfileAvatar avatar={profile.avatar_key} size="lg" className={AVATAR_HOVER} />
                {managing && (
                  <span className="absolute -right-1 -bottom-1 flex h-8 w-8 items-center justify-center rounded-full border-2 border-cream bg-ink text-white">
                    <Pencil size={15} aria-hidden />
                  </span>
                )}
                {!managing && currentProfile?.id === profile.id && (
                  <span className="absolute -right-1 -bottom-1 flex h-7 w-7 items-center justify-center rounded-full border-2 border-cream bg-leaf-500 text-white">
                    <Check size={15} aria-hidden />
                  </span>
                )}
              </span>
              <span className="flex flex-col items-center gap-1">
                <span className="max-w-full truncate font-bold text-ink group-hover:text-leaf-800">{profile.name}</span>
                {profile.is_default && <span className="rounded-full bg-leaf-50 px-2 py-0.5 text-[11px] font-semibold text-leaf-800">대표</span>}
              </span>
            </>
          );
          return (
            <li key={profile.id} className="min-w-0">
              {managing ? (
                <Link to={`/profiles/${profile.id}/edit`} aria-label={`${profile.name} 프로필 고치기`} className={CARD_CLASS}>
                  {label}
                </Link>
              ) : (
                <button type="button" disabled={busy !== null} onClick={() => void choose(profile)} aria-label={`${profile.name}${profile.is_default ? ' (대표)' : ''}`} className={`${CARD_CLASS} w-full disabled:opacity-60`}>
                  {label}
                </button>
              )}
            </li>
          );
        })}
        {profiles.length < max && (
          <li>
            <Link to="/profiles/new" className={CARD_CLASS}>
              <span className={`flex h-24 w-24 items-center justify-center rounded-3xl border-2 border-dashed border-line bg-white text-ink-muted md:h-28 md:w-28 ${AVATAR_HOVER}`}>
                <Plus size={40} aria-hidden />
              </span>
              <span className="flex flex-col items-center gap-0.5">
                <span className="font-bold text-ink">프로필 추가</span>
                <span className="text-xs text-ink-muted" data-testid="profile-count">
                  {profiles.length}/{max}
                </span>
              </span>
            </Link>
          </li>
        )}
      </ul>
      {profiles.length >= max && <p className="text-sm text-ink-muted">프로필은 대표 프로필을 포함해 {max}개까지 만들 수 있어요.</p>}

      <div className="flex w-full max-w-xs flex-col gap-2">
        <Button variant="ghost" onClick={() => setParams(managing ? {} : { manage: '1' }, { replace: true, state: location.state })}>
          {managing ? '관리 끝내기' : (
            <>
              <Pencil size={16} aria-hidden />
              프로필 관리
            </>
          )}
        </Button>
        {managing && currentProfile && (
          <Link to="/" className="min-h-11 text-center text-sm font-semibold text-ink-soft underline">
            {currentProfile.name}(으)로 돌아가기
          </Link>
        )}
        {!managing && (
          <button type="button" onClick={() => void logout()} className="flex min-h-11 items-center justify-center gap-1.5 text-sm font-semibold text-ink-muted underline">
            <LogOut size={15} aria-hidden />
            로그아웃
          </button>
        )}
      </div>
    </div>
  );
}
