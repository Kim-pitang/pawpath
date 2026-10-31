import { CheckCircle2, Footprints, Home, Locate, Map as MapIcon, PawPrint, Sparkles, X } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { useApp } from '../context/AppContext';

const SIDE_TABS = [
  { to: '/', label: '홈', icon: Home, end: true },
  { to: '/recommend', label: '추천', icon: Sparkles, end: false },
  { to: '/map', label: '지도', icon: MapIcon, end: false },
  { to: '/my', label: '마이', icon: PawPrint, end: false },
];

// 산책 기록과 나의 산책길 화면에 있을 때는 가운데 산책 버튼이 고른 상태로 보인다.
const WALK_PATHS = ['/walk', '/my-walks', '/public-walks'];

/** 휴대폰 아래 메뉴. 가장 자주 하는 일(산책 나가기)을 가운데 버튼에 두고, 누르면 시작 방법을 고르는 시트가 올라온다. */
export default function WalkActionNav() {
  const { selectedPet } = useApp();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const onWalk = WALK_PATHS.some((path) => location.pathname.startsWith(path));

  // 시트에서 고른 화면으로 넘어가면 시트를 닫는다.
  useEffect(() => setOpen(false), [location.pathname]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && setOpen(false);
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open]);

  const renderTab = ({ to, label, icon: Icon, end }: (typeof SIDE_TABS)[number]) => (
    <NavLink
      key={to}
      to={to}
      end={end}
      className={({ isActive }) =>
        `pp-press flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-semibold ${
          isActive ? 'text-mango-700' : 'text-ink-soft'
        }`
      }
    >
      <Icon size={21} aria-hidden />
      {label}
    </NavLink>
  );

  return (
    <>
      {open && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-labelledby="walk-sheet-title">
          <button type="button" aria-label="닫기" className="pp-scrim absolute inset-0 bg-ink/40" onClick={() => setOpen(false)} />
          <div className="pp-sheet absolute inset-x-0 bottom-0 rounded-t-xl bg-white px-4 pt-3 pb-[max(1rem,env(safe-area-inset-bottom))] shadow-[0_-8px_24px_rgb(66_45_33/0.16)]">
            <div className="mx-auto max-w-md">
              <div className="mb-2 flex items-center justify-between">
                <h2 id="walk-sheet-title" className="text-lg font-bold text-ink">
                  어떻게 걸을까요?
                </h2>
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  aria-label="닫기"
                  className="pp-press flex h-10 w-10 items-center justify-center rounded-full text-ink-soft hover:bg-cream"
                >
                  <X size={20} aria-hidden />
                </button>
              </div>
              <ul className="flex flex-col gap-2 pb-2">
                <SheetOption
                  to="/recommend"
                  icon={<Sparkles size={20} aria-hidden />}
                  title="추천 코스로 산책"
                  note={`오늘 ${selectedPet?.name ?? '우리 아이'}에게 맞춘 TOP 3 중에서 골라요`}
                  primary
                />
                <SheetOption to="/record" icon={<Locate size={20} aria-hidden />} title="내 길로 GPS 기록" note="걷는 길을 그대로 기록하고 사진을 남겨요" />
                <SheetOption to="/walk" icon={<CheckCircle2 size={20} aria-hidden />} title="다녀온 산책 기록" note="완료 처리와 지난 산책을 볼 수 있어요" />
              </ul>
            </div>
          </div>
        </div>
      )}

      <nav className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-white pb-[env(safe-area-inset-bottom)] md:hidden" aria-label="주요 메뉴">
        <div className="mx-auto flex max-w-md items-end">
          {SIDE_TABS.slice(0, 2).map(renderTab)}
          <div className="flex flex-1 justify-center">
            <button
              type="button"
              aria-haspopup="dialog"
              aria-expanded={open}
              aria-current={onWalk ? 'page' : undefined}
              onClick={() => setOpen(true)}
              className={`pp-press -mt-5 mb-1.5 flex h-16 w-16 flex-col items-center justify-center rounded-full border-4 border-cream text-[11px] font-bold text-ink ${
                onWalk ? 'bg-mango-600' : 'bg-mango-500 hover:bg-mango-600'
              }`}
            >
              <Footprints size={22} aria-hidden />
              산책
            </button>
          </div>
          {SIDE_TABS.slice(2).map(renderTab)}
        </div>
      </nav>
    </>
  );
}

function SheetOption({ to, icon, title, note, primary = false }: { to: string; icon: ReactNode; title: string; note: string; primary?: boolean }) {
  return (
    <li>
      <Link
        to={to}
        className={`pp-press flex min-h-16 items-center gap-3 rounded-lg px-4 py-3 ${primary ? 'bg-mango-500 hover:bg-mango-600' : 'bg-cream-deep hover:bg-peach-deep'}`}
      >
        <span className="text-ink">{icon}</span>
        <span className="min-w-0">
          <span className="block text-base font-bold text-ink">{title}</span>
          <span className="block text-sm text-ink">{note}</span>
        </span>
      </Link>
    </li>
  );
}
