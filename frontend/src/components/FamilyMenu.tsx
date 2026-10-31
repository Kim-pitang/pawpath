import { BarChart3, ChevronRight, PawPrint, Settings, UserRoundCog, UsersRound } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import ProfileAvatar from './ProfileAvatar';
import { Card } from './ui';

const ROW_CLASS = 'flex min-h-12 items-center gap-3 py-2 text-sm font-semibold text-ink hover:text-leaf-800';

/** 마이페이지의 가족 계정 메뉴. 로그아웃은 위 계정 카드에 있다. */
export default function FamilyMenu() {
  const { account, currentProfile, profiles } = useApp();
  const signedIn = Boolean(account?.authenticated);
  const items = [
    signedIn && { to: '/profiles?manage=1', icon: UserRoundCog, label: '내 프로필 관리', note: `${profiles.length}/${account?.max_profiles ?? 5}` },
    { to: '/pets', icon: PawPrint, label: '가족 반려동물 관리' },
    { to: '/family', icon: UsersRound, label: '가족 산책 기록' },
    { to: '/family#members', icon: BarChart3, label: '구성원별 산책 통계' },
    signedIn && { to: '/account', icon: Settings, label: '계정 설정' },
  ].filter(Boolean) as { to: string; icon: typeof PawPrint; label: string; note?: string }[];

  return (
    <Card className="!py-3">
      {currentProfile && (
        <div className="flex items-center gap-3 border-b border-line pb-3">
          <ProfileAvatar avatar={currentProfile.avatar_key} size="sm" />
          <div className="min-w-0">
            <p className="text-xs text-ink-muted">지금 프로필</p>
            <p className="truncate font-bold" data-testid="my-profile-name">
              {currentProfile.name}
              {currentProfile.is_default && <span className="ml-1.5 text-xs font-semibold text-leaf-800">대표</span>}
            </p>
          </div>
          {profiles.length > 1 && (
            <Link to="/profiles" className="ml-auto shrink-0 text-xs font-semibold text-leaf-600 underline">
              프로필 바꾸기
            </Link>
          )}
        </div>
      )}
      <nav aria-label="가족 계정 메뉴">
        <ul className="flex flex-col divide-y divide-line">
          {items.map(({ to, icon: Icon, label, note }) => (
            <li key={to}>
              <Link to={to} className={ROW_CLASS}>
                <Icon size={18} className="shrink-0 text-leaf-500" aria-hidden />
                <span className="flex-1">{label}</span>
                {note && <span className="text-xs font-normal text-ink-muted">{note}</span>}
                <ChevronRight size={16} className="text-ink-muted" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </Card>
  );
}
