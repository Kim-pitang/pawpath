import { LogIn, UserPlus } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { MungoMark, Wordmark } from '../components/Logo';
import { Button, Card, ChoiceGroup, ErrorNotice, InfoNotice } from '../components/ui';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';

type Mode = 'login' | 'signup';
const MODE_OPTIONS: { value: Mode; label: string }[] = [
  { value: 'login', label: '로그인' },
  { value: 'signup', label: '회원가입' },
];
const INPUT_CLASS = 'mt-1.5 min-h-12 w-full rounded-lg border border-line bg-white px-4 text-base outline-none focus:border-ink';
const LOGIN_ID_PATTERN = /^[a-z0-9][a-z0-9_.-]{2,29}$/;
const GOOGLE_ERRORS: Record<string, string> = {
  google_cancelled: 'Google 로그인을 취소했어요.',
  google_failed: 'Google 로그인에 실패했어요. 잠시 뒤 다시 시도해 주세요.',
  google_state: '로그인 요청이 만료되었거나, 시작한 주소와 돌아온 주소가 달라요. 이 화면에서 다시 시도해 주세요.',
  google_unavailable: '이 서버에는 Google 로그인이 설정되어 있지 않아요.',
};

/** Google 브랜드 지침의 G 로고. */
function GoogleMark() {
  return (
    <svg viewBox="0 0 48 48" width="18" height="18" aria-hidden>
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  );
}

function signupProblem(loginId: string, password: string, name: string): string | null {
  if (!LOGIN_ID_PATTERN.test(loginId)) return '아이디는 3~30자의 영문 소문자, 숫자, 점(.), 밑줄(_), 하이픈(-)으로 만들고 영문이나 숫자로 시작해 주세요.';
  if (password.length < 8) return '비밀번호는 8자 이상으로 정해 주세요.';
  if (!name.trim()) return '이름을 입력해 주세요.';
  return null;
}

export default function LoginPage() {
  const { account, refreshAccount, authNotice, clearAuthNotice } = useApp();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? '/';
  const [params] = useSearchParams();
  const googleError = GOOGLE_ERRORS[params.get('error') ?? ''] ?? null;
  const [mode, setMode] = useState<Mode>('login');
  const [loginId, setLoginId] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (account?.authenticated) return <Navigate to={from} replace />;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const id = loginId.trim().toLowerCase();
    const problem = mode === 'signup' ? signupProblem(id, password, name) : null;
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (mode === 'login') await api.login({ login_id: id, password });
      else await api.signup({ login_id: id, password, name: name.trim() });
      clearAuthNotice();
      await refreshAccount();
      navigate(from, { replace: true });
    } catch (submitError) {
      setError((submitError as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto flex min-h-dvh max-w-md flex-col gap-4 p-4">
      <header className="flex items-center gap-2">
        <MungoMark />
        <Wordmark compact />
      </header>
      <h1 className="text-2xl font-bold text-ink">{mode === 'login' ? '로그인' : '회원가입'}</h1>
      {authNotice && <ErrorNotice message={authNotice} />}
      {account?.auth_required && !authNotice && <InfoNotice>이 서버는 로그인해야 쓸 수 있어요.</InfoNotice>}
      {googleError && !error && <ErrorNotice message={googleError} />}

      <Card>
        {account?.google_enabled && (
          <div className="mb-4 flex flex-col gap-4">
            <a
              href={api.googleStartUrl(from)}
              className="inline-flex min-h-12 items-center justify-center gap-3 rounded-lg border border-line bg-white px-5 text-sm font-bold text-ink transition hover:bg-cream"
            >
              <GoogleMark />
              Google로 계속하기
            </a>
            <div className="flex items-center gap-3 text-xs text-ink-muted">
              <span className="h-px flex-1 bg-line" />
              또는 아이디로
              <span className="h-px flex-1 bg-line" />
            </div>
          </div>
        )}
        <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
          <ChoiceGroup
            label="계정"
            value={mode}
            options={MODE_OPTIONS}
            onChange={(next) => {
              setMode(next);
              setError(null);
            }}
          />
          <label className="text-sm font-semibold">
            아이디
            <input className={INPUT_CLASS} value={loginId} maxLength={30} autoComplete="username" autoCapitalize="none" onChange={(event) => setLoginId(event.target.value)} />
          </label>
          <label className="text-sm font-semibold">
            비밀번호
            <input
              className={INPUT_CLASS}
              type="password"
              value={password}
              maxLength={128}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          {mode === 'signup' && (
            <>
              <label className="text-sm font-semibold">
                이름
                <input className={INPUT_CLASS} value={name} maxLength={30} autoComplete="nickname" onChange={(event) => setName(event.target.value)} />
              </label>
              <p className="text-xs text-ink-muted">아이디는 영문 소문자와 숫자로 3자 이상, 비밀번호는 8자 이상이에요.</p>
            </>
          )}
          {error && <ErrorNotice message={error} />}
          <Button type="submit" disabled={busy || !loginId.trim() || !password}>
            {mode === 'login' ? <LogIn size={18} aria-hidden /> : <UserPlus size={18} aria-hidden />}
            {busy ? '확인 중이에요' : mode === 'login' ? '로그인하기' : '가입하고 시작하기'}
          </Button>
        </form>
      </Card>

      {account && !account.auth_required && (
        <Link to="/" className="min-h-11 text-center text-sm font-semibold text-ink-soft underline">
          로그인하지 않고 시연 보호자로 둘러보기
        </Link>
      )}
    </div>
  );
}
