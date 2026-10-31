import { LogIn, UserPlus } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import GoogleMark from '../components/GoogleMark';
import { PawPathMark, Wordmark } from '../components/Logo';
import { Button, Card, ChoiceGroup, ErrorNotice, InfoNotice } from '../components/ui';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import { GOOGLE_ERRORS } from '../lib/labels';
import { safeNext } from '../lib/navigation-paths';

type Mode = 'login' | 'signup';
const MODE_OPTIONS: { value: Mode; label: string }[] = [
  { value: 'login', label: '로그인' },
  { value: 'signup', label: '회원가입' },
];
const INPUT_CLASS = 'mt-1.5 min-h-12 w-full rounded-2xl border border-line bg-white px-4 text-base outline-none focus:border-leaf-500';
const LOGIN_ID_PATTERN = /^[a-z0-9][a-z0-9_.-]{2,29}$/;
const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const isEmail = (value: string) => value.includes('@');

function signupProblem(loginId: string, password: string, name: string): string | null {
  if (isEmail(loginId)) {
    if (!EMAIL_PATTERN.test(loginId) || loginId.length > 254) return '이메일 주소를 다시 확인해 주세요.';
  } else if (!LOGIN_ID_PATTERN.test(loginId)) {
    return '아이디는 3~30자의 영문 소문자, 숫자, 점(.), 밑줄(_), 하이픈(-)으로 만들고 영문이나 숫자로 시작해 주세요.';
  }
  if (password.length < 8) return '비밀번호는 8자 이상으로 정해 주세요.';
  if (!name.trim()) return '이름을 입력해 주세요.';
  return null;
}

export default function LoginPage() {
  const { account, refreshAccount } = useApp();
  const navigate = useNavigate();
  const location = useLocation();
  const from = safeNext((location.state as { from?: string } | null)?.from);
  const [params] = useSearchParams();
  const googleError = GOOGLE_ERRORS[params.get('error') ?? ''] ?? null;
  const [mode, setMode] = useState<Mode>('login');
  const [loginId, setLoginId] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // 보내는 중에는 아래에서 직접 화면을 옮긴다. 가입하면 프로필 설정으로, 프로필이 여럿이면 선택 화면으로 간다.
  if (account?.authenticated && !busy) return <Navigate to={from} replace />;

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
      else await api.signup({ ...(isEmail(id) ? { email: id } : { login_id: id }), password, name: name.trim() });
      const next = await refreshAccount();
      if (mode === 'signup') navigate(`/profiles/setup?next=${encodeURIComponent(from)}`, { replace: true });
      else if (next.profile_required) navigate('/profiles', { replace: true, state: { from } });
      else navigate(from, { replace: true });
    } catch (submitError) {
      setError((submitError as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto flex min-h-dvh max-w-md flex-col gap-4 p-4">
      <header className="flex items-center gap-2">
        <PawPathMark />
        <Wordmark compact />
      </header>
      <h1 className="font-brand text-2xl text-leaf-800">{mode === 'login' ? '로그인' : '회원가입'}</h1>
      {account?.auth_required && <InfoNotice>이 서버는 로그인해야 쓸 수 있어요.</InfoNotice>}
      {googleError && !error && <ErrorNotice message={googleError} />}

      <Card>
        {account?.google_enabled && (
          <div className="mb-4 flex flex-col gap-4">
            <a
              href={api.googleStartUrl(from)}
              className="inline-flex min-h-12 items-center justify-center gap-3 rounded-2xl border border-line bg-white px-5 text-sm font-bold text-ink transition hover:bg-cream"
            >
              <GoogleMark />
              Google로 계속하기
            </a>
            <div className="flex items-center gap-3 text-xs text-ink-muted">
              <span className="h-px flex-1 bg-line" />
              또는 이메일이나 아이디로
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
            아이디 또는 이메일
            <input className={INPUT_CLASS} value={loginId} maxLength={254} autoComplete="username" autoCapitalize="none" inputMode="email" onChange={(event) => setLoginId(event.target.value)} />
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
              <p className="text-xs text-ink-muted">이메일이나 아이디(영문 소문자와 숫자로 3자 이상)로 가입해요. 비밀번호는 8자 이상이에요. 가족은 한 계정에서 프로필을 나눠 써요.</p>
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
