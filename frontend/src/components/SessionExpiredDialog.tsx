import { LogIn } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import { GOOGLE_ERRORS } from '../lib/labels';
import { clearDraft, loadDraft } from '../lib/recording';
import GoogleMark from './GoogleMark';
import { Button, ErrorNotice } from './ui';

const LINK_CLASS = 'min-h-10 text-sm font-semibold text-ink-soft underline';

/**
 * 세션이 끝나면 지금 화면 위에 띄운다. 화면을 옮기지 않으므로 쓰던 내용이 그대로 남고,
 * 같은 보호자로 다시 로그인하면 멈춰 있던 저장 요청이 이어서 끝난다.
 */
export default function SessionExpiredDialog() {
  const { expired, refreshAccount, leaveAccount } = useApp();
  const location = useLocation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // 공유 링크는 로그인과 상관없이 보는 화면이다.
  if (!expired || location.pathname.startsWith('/shared/')) return null;
  const googleError = GOOGLE_ERRORS[params.get('error') ?? ''] ?? null;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const account = await api.login({ login_id: expired.login_id ?? '', password });
      // 새 세션은 프로필을 고르지 않은 상태라, 쓰던 프로필이 아직 이 계정에 있으면 다시 고른다. 서버가 소속을 확인한다.
      const previous = expired.profile_id;
      if (account.profile_required && previous && account.profiles?.some((profile) => profile.id === previous)) {
        await api.selectProfile(previous).catch(() => undefined);
      }
      await refreshAccount();
      setPassword('');
    } catch (submitError) {
      setError((submitError as Error).message);
    } finally {
      setBusy(false);
    }
  };

  /** 다른 사람이 쓸 수 있으므로, 로그아웃할 때처럼 앞사람의 저장하지 않은 기록을 지운다. */
  const leave = async (to: string) => {
    if (loadDraft() && !window.confirm('저장하지 않은 산책 기록이 있어요. 계속하면 이 기기에서 지워져요.')) return;
    clearDraft();
    await leaveAccount();
    navigate(to, { replace: true });
  };

  return (
    <div className="fixed inset-0 z-[2000] flex items-end justify-center bg-ink/40 p-4 sm:items-center">
      <div role="dialog" aria-modal="true" aria-labelledby="session-expired-title" className="flex w-full max-w-sm flex-col gap-3 rounded-3xl bg-white p-5 shadow-xl">
        <h2 id="session-expired-title" className="text-lg font-bold text-ink">
          로그인이 만료되었어요
        </h2>
        <p className="text-sm text-ink-soft">다시 로그인하면 보던 화면과 저장하지 않은 기록을 그대로 이어서 쓸 수 있어요.</p>
        {googleError && <ErrorNotice message={googleError} />}

        {expired.provider === 'google' ? (
          expired.googleEnabled ? (
            <a
              href={api.googleStartUrl(location.pathname === '/login' ? '/' : location.pathname + location.search)}
              className="inline-flex min-h-12 items-center justify-center gap-3 rounded-2xl border border-line bg-white px-5 text-sm font-bold text-ink transition hover:bg-cream"
            >
              <GoogleMark />
              Google로 다시 로그인
            </a>
          ) : (
            <ErrorNotice message="이 서버에는 지금 Google 로그인이 설정되어 있지 않아요." />
          )
        ) : (
          <form onSubmit={submit} className="flex flex-col gap-3" noValidate>
            <p className="text-sm">
              <span className="text-ink-muted">{expired.login_id?.includes('@') ? '이메일' : '아이디'}</span> <span className="font-bold" data-testid="expired-login-id">{expired.login_id}</span>
            </p>
            {/* 비밀번호 관리자가 어느 계정인지 알 수 있게 아이디를 함께 둔다. */}
            <input type="text" name="username" autoComplete="username" value={expired.login_id ?? ''} readOnly hidden />
            <label className="text-sm font-semibold">
              비밀번호
              <input
                className="mt-1.5 min-h-12 w-full rounded-2xl border border-line bg-white px-4 text-base outline-none focus:border-leaf-500"
                type="password"
                value={password}
                maxLength={128}
                autoComplete="current-password"
                autoFocus
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
            {error && <ErrorNotice message={error} />}
            <Button type="submit" disabled={busy || !password}>
              <LogIn size={18} aria-hidden />
              {busy ? '확인 중이에요' : '다시 로그인'}
            </Button>
          </form>
        )}

        <button type="button" onClick={() => void leave('/login')} className={LINK_CLASS}>
          다른 계정으로 로그인
        </button>
        {!expired.authRequired && (
          <button type="button" onClick={() => void leave('/')} className={LINK_CLASS}>
            시연 보호자로 둘러보기
          </button>
        )}
      </div>
    </div>
  );
}
