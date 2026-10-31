import { ChevronDown, Settings, UsersRound } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import ProfileAvatar from './ProfileAvatar';

const ITEM_CLASS = 'flex min-h-11 w-full items-center gap-2.5 rounded-xl px-2.5 text-left text-sm font-semibold text-ink hover:bg-cream';

/** 상단의 현재 프로필. 누르면 다른 프로필로 바꾸거나 프로필을 관리한다. */
export default function ProfileMenu() {
  const { account, currentProfile, profiles, switchProfile } = useApp();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => event.key === 'Escape' && setOpen(false);
    document.addEventListener('pointerdown', close);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('pointerdown', close);
      document.removeEventListener('keydown', escape);
    };
  }, [open]);

  // 화면을 옮기면 메뉴를 닫는다.
  useEffect(() => setOpen(false), [location.pathname]);

  if (!account?.authenticated || !currentProfile) return null;
  const others = profiles.filter((profile) => profile.id !== currentProfile.id);

  const choose = async (id: number) => {
    setBusy(true);
    setError(null);
    try {
      await switchProfile(id);
      setOpen(false);
    } catch (switchError) {
      setError((switchError as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div ref={box} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`지금 프로필 ${currentProfile.name}. 프로필 바꾸기`}
        data-testid="current-profile"
        onClick={() => setOpen((value) => !value)}
        className="flex min-h-9 items-center gap-1.5 rounded-full border border-line bg-white py-1 pr-2.5 pl-1 text-sm font-semibold text-ink"
      >
        <ProfileAvatar avatar={currentProfile.avatar_key} size="xs" />
        <span className="max-w-20 truncate md:max-w-32">{currentProfile.name}</span>
        <ChevronDown size={14} className={`text-ink-muted transition ${open ? 'rotate-180' : ''}`} aria-hidden />
      </button>
      {open && (
        <div role="menu" aria-label="프로필 메뉴" className="absolute right-0 z-40 mt-2 w-60 rounded-2xl border border-line bg-white p-1.5 shadow-[0_8px_24px_rgb(120_90_40/0.16)]">
          {others.length > 0 && <p className="px-2.5 pt-1.5 pb-1 text-xs text-ink-muted">다른 프로필로 바꾸기</p>}
          {others.map((profile) => (
            <button key={profile.id} type="button" role="menuitem" disabled={busy} onClick={() => void choose(profile.id)} className={ITEM_CLASS}>
              <ProfileAvatar avatar={profile.avatar_key} size="xs" />
              <span className="min-w-0 truncate">{profile.name}</span>
            </button>
          ))}
          {error && <p className="px-2.5 py-1 text-xs font-semibold text-carrot-700" role="alert">{error}</p>}
          {others.length > 0 && <hr className="my-1 border-line" />}
          <Link role="menuitem" to="/profiles?manage=1" className={ITEM_CLASS}>
            <Settings size={16} className="text-ink-muted" aria-hidden />
            프로필 관리
          </Link>
          <Link role="menuitem" to="/family" className={ITEM_CLASS}>
            <UsersRound size={16} className="text-ink-muted" aria-hidden />
            가족 산책 기록
          </Link>
        </div>
      )}
    </div>
  );
}
