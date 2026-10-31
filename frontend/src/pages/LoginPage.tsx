import { Link, Navigate, useLocation, useSearchParams } from 'react-router-dom';
import GoogleMark from '../components/GoogleMark';
import { MungoMark, Wordmark } from '../components/Logo';
import { Card, ErrorNotice, InfoNotice } from '../components/ui';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import { GOOGLE_ERRORS } from '../lib/labels';
import { safeNext } from '../lib/navigation-paths';

/** 로그인은 Google로만 한다. 처음 로그인하면 계정이 만들어지고 대표 프로필을 정하는 화면으로 간다. */
export default function LoginPage() {
  const { account } = useApp();
  const location = useLocation();
  const from = safeNext((location.state as { from?: string } | null)?.from);
  const [params] = useSearchParams();
  const googleError = GOOGLE_ERRORS[params.get('error') ?? ''] ?? null;

  if (account?.authenticated) return <Navigate to={from} replace />;

  return (
    <div className="mx-auto flex min-h-dvh max-w-md flex-col gap-4 p-4">
      <header className="flex items-center gap-2">
        <MungoMark />
        <Wordmark compact />
      </header>
      <h1 className="text-2xl font-bold text-ink">로그인</h1>
      {account?.auth_required && <InfoNotice>이 서버는 로그인해야 쓸 수 있어요.</InfoNotice>}
      {googleError && <ErrorNotice message={googleError} />}

      {account && (
        <Card>
          {account.google_enabled ? (
            <div className="flex flex-col gap-3">
              <a
                href={api.googleStartUrl(from)}
                className="inline-flex min-h-12 items-center justify-center gap-3 rounded-lg border border-line bg-white px-5 text-sm font-bold text-ink transition hover:bg-cream"
              >
                <GoogleMark />
                Google로 계속하기
              </a>
              <p className="text-xs text-ink-muted">처음이면 Google 계정으로 바로 가입돼요. 가족은 한 계정에서 프로필을 나눠 써요.</p>
            </div>
          ) : (
            <ErrorNotice message="이 서버에는 지금 Google 로그인이 설정되어 있지 않아요." />
          )}
        </Card>
      )}

      {account && !account.auth_required && (
        <Link to="/" className="min-h-11 text-center text-sm font-semibold text-ink-soft underline">
          로그인하지 않고 시연 보호자로 둘러보기
        </Link>
      )}
    </div>
  );
}
