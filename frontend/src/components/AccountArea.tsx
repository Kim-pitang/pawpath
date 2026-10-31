import { Check, Dog, LogIn, LogOut, Plus, Settings2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { useLogout } from './AccountCard';

/**
 * 머리글 오른쪽 계정 영역. 강아지 아이콘 하나만 두고(로그인하면 짙게 칠해진다),
 * 누르면 반려동물 바꾸기와 계정을 함께 다루는 패널이 열린다.
 */
export default function AccountArea() {
  const { account, pets, selectedPet, selectPet } = useApp();
  const location = useLocation();
  const logout = useLogout();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const here = location.pathname + location.search;
  const user = account?.authenticated ? account.user : null;

  useEffect(() => setOpen(false), [location.pathname]);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && setOpen(false);
    document.addEventListener('pointerdown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  if (!account) return null;

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={user ? `계정 메뉴, ${user.name}` : '계정 메뉴, 시연 보호자'}
        title={user ? user.name : '시연 보호자'}
        onClick={() => setOpen((value) => !value)}
        className={`pp-press flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${
          user ? 'bg-ink text-white hover:bg-black' : 'border border-line bg-white text-ink-soft hover:text-ink'
        }`}
      >
        <Dog size={21} strokeWidth={1.8} aria-hidden />
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="반려동물과 계정"
          className="pp-pop absolute top-full right-0 z-40 mt-2 w-72 origin-top-right overflow-hidden rounded-xl border border-line bg-white shadow-[0_12px_32px_rgb(66_45_33/0.16)]"
        >
          <div className="p-3">
            <div className="flex items-center justify-between px-1 pb-2">
              <p className="text-xs font-semibold text-ink-soft">반려동물</p>
              {pets.length > 0 && (
                <Link to="/pets" className="flex min-h-7 items-center gap-1 text-xs font-semibold text-ink-soft hover:text-ink">
                  <Settings2 size={13} aria-hidden />
                  관리
                </Link>
              )}
            </div>
            {pets.length > 0 && selectedPet ? (
              <ul className="flex flex-col gap-1">
                {pets.map((pet) => {
                  const selected = pet.id === selectedPet.id;
                  return (
                    <li key={pet.id}>
                      <button
                        type="button"
                        aria-pressed={selected}
                        onClick={() => selectPet(pet.id)}
                        className={`flex min-h-12 w-full items-center gap-3 rounded-lg px-2 text-left ${selected ? 'bg-cream-deep' : 'hover:bg-cream'}`}
                      >
                        <span
                          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full font-brand text-base text-ink ${selected ? 'bg-mango-500' : 'bg-cream-deep'}`}
                          aria-hidden
                        >
                          {pet.name.slice(0, 1)}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-semibold text-ink">{pet.name}</span>
                          <span className="block text-xs text-ink-soft">
                            {pet.breed} · {pet.age_years}세 · {pet.weight_kg}kg
                          </span>
                        </span>
                        {selected && <Check size={16} className="shrink-0 text-mango-700" aria-hidden />}
                      </button>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="px-1 pb-1 text-sm text-ink-soft">아직 등록된 반려동물이 없어요.</p>
            )}
            <Link to="/pets/new" className="mt-1 flex min-h-10 items-center gap-2 rounded-lg px-2 text-sm font-semibold text-ink-soft hover:bg-cream hover:text-ink">
              <Plus size={16} aria-hidden />
              반려동물 {pets.length > 0 ? '추가' : '등록'}
            </Link>
          </div>

          <div className="border-t border-line bg-cream p-3">
            {user ? (
              <div className="flex items-center gap-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-ink">{user.name}</p>
                  <p className="truncate text-xs text-ink-soft">
                    {user.provider === 'google' ? `Google · ${user.email ?? '계정'}` : `아이디 ${user.login_id}`}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void logout()}
                  className="pp-press flex min-h-10 shrink-0 items-center gap-1.5 rounded-md bg-white px-3 text-sm font-semibold text-ink hover:bg-cream-deep"
                >
                  <LogOut size={15} aria-hidden />
                  로그아웃
                </button>
              </div>
            ) : (
              <>
                <p className="text-sm text-ink">시연 보호자로 쓰고 있어요.</p>
                <p className="mt-0.5 text-xs text-ink-soft">로그인하면 내 반려동물과 산책길을 따로 모아요.</p>
                <Link
                  to="/login"
                  state={{ from: here }}
                  className="pp-press mt-2.5 flex min-h-10 items-center justify-center gap-1.5 rounded-md bg-mango-500 text-sm font-bold text-ink hover:bg-mango-600"
                >
                  <LogIn size={15} aria-hidden />
                  로그인 또는 회원가입
                </Link>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
