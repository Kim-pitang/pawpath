import { LogOut, UserRound } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { clearDraft, loadDraft } from '../lib/recording';
import { Button, Card, LinkButton } from './ui';

/** 로그아웃하고 홈으로 간다. 머리글 계정 메뉴와 마이 화면이 함께 쓴다. */
export function useLogout() {
  const { signOut } = useApp();
  const navigate = useNavigate();
  return async () => {
    // 같은 기기를 다른 사람이 쓸 수 있으므로, 저장하지 않은 기록도 함께 지운다.
    if (loadDraft() && !window.confirm('저장하지 않은 산책 기록이 있어요. 로그아웃하면 이 기기에서 지워져요.')) return;
    clearDraft();
    await signOut();
    navigate('/');
  };
}

export default function AccountCard() {
  const { account } = useApp();
  const logout = useLogout();
  if (!account) return null;

  if (account.authenticated && account.user) {
    const { user } = account;
    const google = user.provider === 'google';
    return (
      <Card className="flex items-center justify-between gap-3" >
        <div className="flex min-w-0 items-center gap-2">
          <UserRound size={20} className="shrink-0 text-mango-700" aria-hidden />
          <div className="min-w-0">
            <p className="text-xs text-ink-muted">{google ? 'Google 계정으로 로그인' : '로그인 계정'}</p>
            <p className="truncate font-bold" data-testid="account-name">
              {user.name} <span className="font-normal text-ink-soft">({google ? (user.email ?? 'Google') : user.login_id})</span>
            </p>
          </div>
        </div>
        <Button variant="ghost" onClick={logout} className="shrink-0 !px-3">
          <LogOut size={16} aria-hidden />
          로그아웃
        </Button>
      </Card>
    );
  }

  return (
    <Card>
      <p className="text-sm text-ink-soft">로그인하지 않고 시연 보호자로 쓰고 있어요. 내 반려동물과 산책길을 따로 관리하려면 로그인해 주세요.</p>
      <LinkButton to="/login" variant="ghost" className="mt-3 w-full">
        <UserRound size={16} aria-hidden />
        로그인 또는 회원가입
      </LinkButton>
    </Card>
  );
}
