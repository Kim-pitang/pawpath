import { ShieldCheck, Trash2 } from 'lucide-react';
import { useEffect, useState, type FormEvent } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import GoogleMark from '../components/GoogleMark';
import { Button, Card, ErrorNotice, LinkButton, Loading, PageTitle, SectionTitle } from '../components/ui';
import { useApp } from '../context/AppContext';
import { api, ApiError } from '../lib/api';
import { dateTimeLabel } from '../lib/format';
import { GOOGLE_ERRORS } from '../lib/labels';
import { clearDraft } from '../lib/recording';
import type { AccountSummary } from '../lib/types';

const CONFIRM_WORD = '탈퇴';
const INPUT_CLASS = 'mt-1.5 min-h-12 w-full rounded-2xl border border-line bg-white px-4 text-base outline-none focus:border-leaf-500';
const DATA_LABELS: { key: keyof AccountSummary['data']; label: string; unit: string }[] = [
  { key: 'pets', label: '반려동물', unit: '마리' },
  { key: 'walks', label: '산책 기록', unit: '건' },
  { key: 'feedback', label: '피드백', unit: '건' },
  { key: 'recommendations', label: '추천 기록', unit: '건' },
  { key: 'saved_walks', label: '나만의 산책길', unit: '개' },
  { key: 'photos', label: '산책길 사진', unit: '장' },
  { key: 'personal_courses', label: '내 추천 코스', unit: '개' },
  { key: 'shared_walks', label: '공유 중인 산책길', unit: '개' },
  { key: 'community_trails', label: '커뮤니티에 올린 산책길', unit: '개' },
  { key: 'trail_reviews', label: '남긴 후기', unit: '건' },
];

export default function AccountPage() {
  const { account, leaveAccount } = useApp();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [summary, setSummary] = useState<AccountSummary | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [password, setPassword] = useState('');
  const [confirmWord, setConfirmWord] = useState('');
  const [error, setError] = useState<string | null>(GOOGLE_ERRORS[params.get('error') ?? ''] ?? null);
  const [busy, setBusy] = useState(false);
  const signedIn = account?.authenticated ?? false;

  useEffect(() => {
    if (!signedIn) return;
    api.accountSummary().then(setSummary).catch((failure: Error) => setLoadError(failure.message));
  }, [signedIn]);

  if (account && !signedIn) return <Navigate to="/login" replace state={{ from: '/account' }} />;
  if (loadError) return <ErrorNotice message={loadError} />;
  if (!summary) return <Loading />;

  const confirmIdentity = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.reauthenticate(password);
      setPassword('');
      setSummary({ ...summary, reauth_required: false });
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.deleteAccount();
      clearDraft();
      // 로그인이 필수인 서버에서도 안내를 볼 수 있도록 상태를 바꾸기 전에 화면을 옮긴다.
      navigate('/goodbye', { replace: true, state: { retention: summary.backup_retention_days } });
      await leaveAccount();
    } catch (failure) {
      setBusy(false);
      setError((failure as Error).message);
      // 화면을 오래 열어 두어 본인 확인이 끝났다. 다시 확인받는다.
      if (failure instanceof ApiError && failure.status === 403) setSummary({ ...summary, reauth_required: true });
    }
  };

  const rows = DATA_LABELS.filter(({ key }) => summary.data[key] > 0);
  return (
    <div className="flex flex-col gap-4">
      <PageTitle>계정 관리</PageTitle>

      <Card>
        <SectionTitle>로그인 유지</SectionTitle>
        <p className="text-sm text-ink-soft" data-testid="session-policy">
          {summary.session_idle_days}일 동안 쓰지 않으면 로그아웃돼요. 계속 써도 {dateTimeLabel(summary.session_expires_at)}에는 다시 로그인해야 해요. 저장하지 않은 기록은 다시 로그인하면 이어서 저장할 수 있어요.
        </p>
      </Card>

      <Card>
        <SectionTitle>계정 탈퇴</SectionTitle>
        <p className="text-sm text-ink-soft">탈퇴하면 계정과 아래 데이터를 바로 지워요. 되돌릴 수 없어요.</p>
        {rows.length > 0 ? (
          <dl className="mt-3 flex flex-col divide-y divide-line" data-testid="deletion-summary">
            {rows.map(({ key, label, unit }) => (
              <div key={key} className="flex justify-between py-2 text-sm">
                <dt className="text-ink-soft">{label}</dt>
                <dd className="font-semibold">
                  {summary.data[key]}
                  {unit}
                </dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="mt-3 text-sm text-ink-muted">지금은 계정 정보 말고 지울 데이터가 없어요.</p>
        )}
        <ul className="mt-3 flex list-disc flex-col gap-1 pl-4 text-xs text-ink-muted">
          {summary.data.shared_walks + summary.data.community_trails > 0 && <li>공유 링크와 공개 목록, 커뮤니티에서도 바로 사라져요.</li>}
          {summary.backup_retention_days !== null && <li>백업에 남은 사본은 {summary.backup_retention_days}일 안에 사라지고, 백업에서 복구해도 되살아나지 않아요.</li>}
          {summary.provider === 'google' && <li>Google 계정은 그대로예요. PawPath 연결은 Google 계정 설정에서 해제할 수 있어요.</li>}
        </ul>
        {summary.data.saved_walks > 0 && (
          <LinkButton to="/my-walks" variant="ghost" className="mt-3 w-full">
            산책길을 먼저 GPX로 내려받기
          </LinkButton>
        )}

        <div className="mt-4 border-t border-line pt-4">
          {error && (
            <div className="mb-3">
              <ErrorNotice message={error} />
            </div>
          )}
          {summary.reauth_required ? (
            summary.provider === 'google' ? (
              <>
                <p className="mb-3 text-sm font-semibold">탈퇴하려면 본인을 다시 확인해 주세요.</p>
                <a
                  href={api.googleReauthUrl()}
                  className="inline-flex min-h-12 w-full items-center justify-center gap-3 rounded-2xl border border-line bg-white px-5 text-sm font-bold text-ink transition hover:bg-cream"
                >
                  <GoogleMark />
                  Google로 본인 확인
                </a>
              </>
            ) : (
              <form onSubmit={confirmIdentity} className="flex flex-col gap-3" noValidate>
                <label className="text-sm font-semibold">
                  탈퇴하려면 비밀번호를 다시 입력해 주세요
                  <input className={INPUT_CLASS} type="password" value={password} maxLength={128} autoComplete="current-password" onChange={(event) => setPassword(event.target.value)} />
                </label>
                <Button type="submit" variant="ghost" disabled={busy || !password}>
                  <ShieldCheck size={18} aria-hidden />
                  {busy ? '확인 중이에요' : '본인 확인'}
                </Button>
              </form>
            )
          ) : (
            <form onSubmit={remove} className="flex flex-col gap-3" noValidate>
              <label className="text-sm font-semibold">
                계속하려면 &ldquo;{CONFIRM_WORD}&rdquo;를 입력해 주세요
                <input className={INPUT_CLASS} value={confirmWord} maxLength={10} autoComplete="off" onChange={(event) => setConfirmWord(event.target.value)} />
              </label>
              <Button type="submit" variant="accent" disabled={busy || confirmWord.trim() !== CONFIRM_WORD}>
                <Trash2 size={18} aria-hidden />
                {busy ? '지우는 중이에요' : '계정과 데이터 모두 지우기'}
              </Button>
            </form>
          )}
        </div>
      </Card>
    </div>
  );
}
