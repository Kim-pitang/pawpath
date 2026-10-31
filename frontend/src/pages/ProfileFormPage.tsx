import { Trash2 } from 'lucide-react';
import { useEffect, useState, type FormEvent } from 'react';
import { Link, Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { MungoMark, Wordmark } from '../components/Logo';
import ProfileAvatar, { AVATARS, AVATAR_KEYS } from '../components/ProfileAvatar';
import { Button, Card, ErrorNotice, InfoNotice, Loading } from '../components/ui';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import { dateTimeLabel } from '../lib/format';
import { safeNext } from '../lib/navigation-paths';
import type { AvatarKey, ProfileDetail } from '../lib/types';

type Mode = 'new' | 'edit' | 'setup';
const INPUT_CLASS = 'mt-1.5 min-h-12 w-full rounded-2xl border border-line bg-white px-4 text-base outline-none focus:border-leaf-500';
const TITLES: Record<Mode, string> = { new: '프로필 추가', edit: '프로필 고치기', setup: '내 프로필을 정해 주세요' };

/** 프로필을 만들거나 고친다. setup은 가입 직후 대표 프로필의 이름과 아바타를 정하는 단계다. */
export default function ProfileFormPage({ mode }: { mode: Mode }) {
  const { account, profiles, currentProfile, refreshAccount } = useApp();
  const navigate = useNavigate();
  const { profileId } = useParams();
  const [params] = useSearchParams();
  const next = safeNext(params.get('next'));
  const target = mode === 'edit' ? profiles.find((profile) => profile.id === Number(profileId)) : mode === 'setup' ? currentProfile : undefined;
  // 계정을 이미 읽었으면 처음부터 프로필 값으로 그려 깜박이지 않게 한다.
  const [name, setName] = useState(target?.name ?? '');
  const [avatar, setAvatar] = useState<AvatarKey>(target?.avatar_key ?? 'paw');
  const [detail, setDetail] = useState<ProfileDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(mode !== 'new' && Boolean(target));

  useEffect(() => {
    if (ready || !account?.authenticated) return;
    if (mode === 'new') {
      // 아직 아무도 쓰지 않은 아바타로 시작한다.
      const used = new Set(profiles.map((profile) => profile.avatar_key));
      setAvatar(AVATAR_KEYS.find((key) => !used.has(key)) ?? 'paw');
      setReady(true);
    } else if (target) {
      setName(target.name);
      setAvatar(target.avatar_key);
      setReady(true);
    }
  }, [account, mode, profiles, ready, target]);

  // 고치는 화면에는 이 프로필의 이용 통계를 함께 보여 준다.
  useEffect(() => {
    if (mode !== 'edit' || !target) return;
    api.getProfile(target.id).then(setDetail).catch(() => undefined);
  }, [mode, target]);

  if (!account) return <Loading />;
  if (!account.authenticated) return <Navigate to="/login" replace />;
  // 지웠거나 다른 계정의 프로필이다. 서버도 다른 계정의 프로필은 없는 것처럼 답한다.
  if (mode !== 'new' && !target) return <Navigate to={mode === 'setup' ? next : '/profiles?manage=1'} replace />;
  const max = account.max_profiles ?? 5;
  if (mode === 'new' && profiles.length >= max) return <Navigate to="/profiles" replace />;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      setError('프로필 이름을 입력해 주세요.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (mode === 'new') await api.createProfile({ name: trimmed, avatar_key: avatar });
      else if (target && (trimmed !== target.name || avatar !== target.avatar_key)) await api.updateProfile(target.id, { name: trimmed, avatar_key: avatar });
      await refreshAccount();
      navigate(mode === 'setup' ? next : mode === 'new' ? '/profiles' : '/profiles?manage=1', { replace: true });
    } catch (submitError) {
      setError((submitError as Error).message);
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!target || target.is_default) return;
    if (!window.confirm(`${target.name} 프로필을 지울까요? 이 프로필의 산책 기록과 산책길은 가족 기록에 남고, 반려동물은 그대로예요.`)) return;
    setBusy(true);
    setError(null);
    try {
      await api.deleteProfile(target.id);
      await refreshAccount();
      navigate('/profiles?manage=1', { replace: true });
    } catch (deleteError) {
      setError((deleteError as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto flex min-h-dvh max-w-md flex-col gap-4 p-4">
      <header className="flex items-center gap-2">
        <MungoMark />
        <Wordmark compact />
      </header>
      <div>
        <h1 className="font-brand text-2xl text-leaf-800">{TITLES[mode]}</h1>
        {mode === 'new' && (
          <p className="mt-1 text-sm text-ink-soft">
            가족이 따로 로그인하지 않고 같은 계정을 나눠 써요. 대표 프로필을 포함해 {max}개까지 만들 수 있어요. 지금 {profiles.length}개예요.
          </p>
        )}
        {mode === 'setup' && <p className="mt-1 text-sm text-ink-soft">산책 기록에 남을 이름과 아바타예요. 가족이 함께 쓰면 나중에 프로필을 더 만들 수 있어요.</p>}
      </div>

      <Card>
        <form onSubmit={submit} className="flex flex-col gap-5" noValidate>
          <div className="flex justify-center">
            <ProfileAvatar avatar={avatar} size="lg" />
          </div>
          <label className="text-sm font-semibold">
            프로필 이름
            <input className={INPUT_CLASS} value={name} maxLength={30} autoComplete="nickname" onChange={(event) => setName(event.target.value)} placeholder="예: 엄마, 아빠, 지우" />
          </label>
          <fieldset>
            <legend className="mb-1.5 text-sm font-semibold text-ink">아바타</legend>
            <div className="grid grid-cols-4 gap-2">
              {AVATAR_KEYS.map((key) => (
                <button
                  key={key}
                  type="button"
                  aria-label={AVATARS[key].label}
                  aria-pressed={avatar === key}
                  onClick={() => setAvatar(key)}
                  className={`flex min-h-16 items-center justify-center rounded-2xl border-2 transition ${avatar === key ? 'border-leaf-500 bg-leaf-50' : 'border-transparent hover:bg-cream'}`}
                >
                  <ProfileAvatar avatar={key} size="md" />
                </button>
              ))}
            </div>
          </fieldset>
          {error && <ErrorNotice message={error} />}
          <Button type="submit" disabled={busy || !name.trim()}>
            {busy ? '저장 중이에요' : mode === 'new' ? '프로필 만들기' : mode === 'setup' ? '시작하기' : '저장하기'}
          </Button>
        </form>
      </Card>

      {mode === 'edit' && target && (
        <Card>
          {detail && (
            <dl className="mb-4 grid grid-cols-3 text-center" data-testid="profile-activity">
              <Stat label="산책" value={`${detail.activity.walk_count}번`} />
              <Stat label="거리" value={`${detail.activity.total_distance_km.toFixed(1)}km`} />
              <Stat label="산책길" value={`${detail.activity.saved_walk_count}개`} />
            </dl>
          )}
          {detail?.activity.last_walk_at && <p className="mb-3 text-xs text-ink-muted">마지막 산책 {dateTimeLabel(detail.activity.last_walk_at)}</p>}
          {target.is_default ? (
            <InfoNotice>대표 프로필은 지울 수 없어요. 가족의 모든 기록을 관리하는 프로필이에요.</InfoNotice>
          ) : (
            <p className="mb-3 text-xs text-ink-muted">지워도 이 프로필이 남긴 산책 기록과 산책길은 가족 기록에 남아요.</p>
          )}
          <Button variant="ghost" className="mt-3 w-full" onClick={() => void remove()} disabled={busy || target.is_default}>
            <Trash2 size={16} aria-hidden />
            프로필 삭제
          </Button>
        </Card>
      )}

      {mode === 'setup' ? (
        <Link to={next} replace className="min-h-11 text-center text-sm font-semibold text-ink-soft underline">
          나중에 정할게요
        </Link>
      ) : (
        <Link to={mode === 'new' ? '/profiles' : '/profiles?manage=1'} className="min-h-11 text-center text-sm font-semibold text-ink-soft underline">
          취소
        </Link>
      )}
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
