import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import { GOOGLE_ERRORS } from '../lib/labels';
import { clearDraft, loadDraft } from '../lib/recording';
import GoogleMark from './GoogleMark';
import { ErrorNotice } from './ui';

const LINK_CLASS = 'min-h-10 text-sm font-semibold text-ink-soft underline';

/**
 * 세션이 끝나면 지금 화면 위에 띄운다. 시연 보호자로 넘어가 공용 계정에 저장하는 일을 막고,
 * Google로 다시 로그인하면 보던 주소로 돌아온다. 저장하지 않은 산책 기록은 기기에 남아 기록 화면에서 이어서 저장할 수 있다.
 */
export default function SessionExpiredDialog() {
  const { expired, leaveAccount } = useApp();
  const location = useLocation();
  const navigate = useNavigate();
  const [params] = useSearchParams();

  // 공유 링크는 로그인과 상관없이 보는 화면이다.
  if (!expired || location.pathname.startsWith('/shared/')) return null;
  const googleError = GOOGLE_ERRORS[params.get('error') ?? ''] ?? null;

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
        <p className="text-sm text-ink-soft">Google로 다시 로그인하면 보던 화면으로 돌아와요. 저장하지 않은 산책 기록은 이 기기에 남아 있어요.</p>
        {googleError && <ErrorNotice message={googleError} />}

        {expired.googleEnabled ? (
          <a
            href={api.googleStartUrl(location.pathname === '/login' ? '/' : location.pathname + location.search)}
            className="inline-flex min-h-12 items-center justify-center gap-3 rounded-2xl border border-line bg-white px-5 text-sm font-bold text-ink transition hover:bg-cream"
          >
            <GoogleMark />
            Google로 다시 로그인
          </a>
        ) : (
          <ErrorNotice message="이 서버에는 지금 Google 로그인이 설정되어 있지 않아요." />
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
