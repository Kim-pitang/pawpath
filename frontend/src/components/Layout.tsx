import { CalendarCheck, Home, Map as MapIcon, PawPrint, UsersRound } from 'lucide-react';
import { Link, Navigate, NavLink, Outlet, useLocation } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import AccountArea from './AccountArea';
import ProfileMenu from './ProfileMenu';
import { MungoMark, Wordmark } from './Logo';
import WalkActionNav from './WalkActionNav';

const NAV_ITEMS = [
  { to: '/', label: '홈', icon: Home, end: true },
  { to: '/community', label: '커뮤니티', icon: UsersRound, end: false },
  { to: '/map', label: '지도', icon: MapIcon, end: false },
  { to: '/walk', label: '산책 기록', icon: CalendarCheck, end: false },
  { to: '/my', label: '마이', icon: PawPrint, end: false },
];

export default function Layout() {
  const { account, profileEpoch } = useApp();
  const location = useLocation();
  const here = location.pathname + location.search;

  // 로그인 필수 서버에서 로그인하지 않았으면 로그인 화면으로 보낸다.
  if (account?.auth_required && !account.authenticated) return <Navigate to="/login" replace state={{ from: here }} />;
  // 프로필이 여럿인데 아직 고르지 않았으면 누구의 산책인지 먼저 고른다.
  if (account?.authenticated && account.profile_required) return <Navigate to="/profiles" replace state={{ from: here }} />;

  return (
    <div className="min-h-dvh pb-24 md:pb-10">
      <header className="sticky top-0 z-30 border-b border-line bg-cream pt-[env(safe-area-inset-top)]">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-2.5">
          <Link to="/" className="flex items-center gap-2" aria-label="mungo 홈">
            <MungoMark />
            <Wordmark compact />
          </Link>
          <nav className="hidden items-center gap-1 md:flex" aria-label="주요 메뉴">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `rounded-md px-3.5 py-2 text-sm font-semibold transition-colors ${
                    isActive ? 'bg-cream-deep text-ink' : 'text-ink-soft hover:text-ink'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="flex items-center gap-1.5"><ProfileMenu /><AccountArea /></div>
        </div>
      </header>


      <main className="mx-auto max-w-md px-4 pt-4 md:max-w-5xl">
        {/* 프로필을 바꾸면 화면을 새로 그려 이전 프로필의 기록과 입력이 남지 않게 한다. */}
        <Outlet key={profileEpoch} />
      </main>

      <WalkActionNav />
    </div>
  );
}
