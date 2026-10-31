import { CalendarCheck, Home, Map as MapIcon, PawPrint, Sparkles, UsersRound } from 'lucide-react';
import { Link, Navigate, NavLink, Outlet, useLocation } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { PawPathMark, Wordmark } from './Logo';

const NAV_ITEMS = [
  { to: '/', label: '홈', icon: Home, end: true },
  { to: '/recommend', label: '추천', icon: Sparkles, end: false },
  { to: '/map', label: '지도', icon: MapIcon, end: false },
  { to: '/walk', label: '산책 기록', icon: CalendarCheck, end: false },
  { to: '/community', label: '커뮤니티', icon: UsersRound, end: false },
  { to: '/my', label: '마이', icon: PawPrint, end: false },
];

export default function Layout() {
  const { selectedPet, account, authNotice } = useApp();
  const location = useLocation();
  const here = location.pathname + location.search;

  // 로그인 필수 서버에서 로그인하지 않았으면 로그인 화면으로 보낸다.
  if (account?.auth_required && !account.authenticated) return <Navigate to="/login" replace state={{ from: here }} />;

  return (
    <div className="min-h-dvh pb-24 md:pb-10">
      <header className="sticky top-0 z-30 border-b border-line bg-cream/95 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-2.5">
          <Link to="/" className="flex items-center gap-2" aria-label="PawPath 홈">
            <PawPathMark />
            <Wordmark compact />
          </Link>
          <nav className="hidden items-center gap-1 md:flex" aria-label="주요 메뉴">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `rounded-full px-4 py-2 text-sm font-semibold transition ${
                    isActive ? 'bg-leaf-500 text-white' : 'text-ink-soft hover:bg-leaf-50'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="flex items-center gap-2">
            {account && !account.authenticated && (
              <Link to="/login" state={{ from: here }} className="flex min-h-9 items-center px-1 text-sm font-semibold text-leaf-800 underline">
                로그인
              </Link>
            )}
            {selectedPet && (
              <Link
                to="/pets"
                className="flex min-h-9 items-center gap-1.5 rounded-full border border-line bg-white px-3 text-sm font-semibold text-ink"
              >
                <PawPrint size={15} className="text-carrot-500" aria-hidden />
                {selectedPet.name}
              </Link>
            )}
          </div>
        </div>
      </header>

      {authNotice && (
        <div className="mx-auto max-w-md px-4 pt-3 md:max-w-5xl">
          <div className="flex items-center justify-between gap-2 rounded-2xl bg-carrot-50 p-3 text-sm text-carrot-700" role="alert" data-testid="auth-notice">
            <span>{authNotice}</span>
            <Link to="/login" state={{ from: here }} className="shrink-0 font-bold underline">
              로그인
            </Link>
          </div>
        </div>
      )}

      <main className="mx-auto max-w-md px-4 pt-4 md:max-w-5xl">
        <Outlet />
      </main>

      <nav
        className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-white/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
        aria-label="주요 메뉴"
      >
        <div className="mx-auto grid max-w-md grid-cols-6">
          {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] font-semibold ${
                  isActive ? 'text-leaf-600' : 'text-ink-muted'
                }`
              }
            >
              <Icon size={21} aria-hidden />
              {label}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  );
}
