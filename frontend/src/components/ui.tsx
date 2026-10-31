import { AlertTriangle, Info, PawPrint } from 'lucide-react';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { Link } from 'react-router-dom';

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-lg border border-line bg-white p-5 ${className}`}>{children}</section>;
}

export function SectionTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-2">
      <h2 className="text-base font-bold text-ink">{children}</h2>
      {action}
    </div>
  );
}

export function PageTitle({ children, sub }: { children: ReactNode; sub?: ReactNode }) {
  return (
    <div className="mb-4">
      <h1 className="text-2xl font-bold tracking-[-0.01em] text-ink">{children}</h1>
      {sub && <p className="mt-1 text-sm text-ink-soft">{sub}</p>}
    </div>
  );
}

const BUTTON_STYLES = {
  // 행동은 멍고 오렌지 바탕에 초코 브라운 글자로 칠한다(흰 글자는 대비가 모자라다). accent는 이전 호출부와 맞추려고 남겨 둔 같은 모양이다.
  primary: 'bg-mango-500 text-ink hover:bg-mango-600 disabled:bg-cream-deep disabled:text-ink-soft',
  accent: 'bg-mango-500 text-ink hover:bg-mango-600 disabled:bg-cream-deep disabled:text-ink-soft',
  ghost: 'bg-cream-deep text-ink hover:bg-peach-deep disabled:text-ink-soft',
};
type ButtonVariant = keyof typeof BUTTON_STYLES;
const BUTTON_BASE =
  'inline-flex min-h-12 items-center justify-center gap-2 rounded-md px-5 text-sm font-bold transition-[background-color,transform] active:scale-[0.98] disabled:cursor-not-allowed disabled:active:scale-100';

export function Button({
  variant = 'primary',
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return <button className={`${BUTTON_BASE} ${BUTTON_STYLES[variant]} ${className}`} {...props} />;
}

export function LinkButton({
  to,
  variant = 'primary',
  className = '',
  children,
}: {
  to: string;
  variant?: ButtonVariant;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Link to={to} className={`${BUTTON_BASE} ${BUTTON_STYLES[variant]} ${className}`}>
      {children}
    </Link>
  );
}

export function Chip({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'leaf' | 'carrot' }) {
  const tones = {
    neutral: 'bg-cream-deep text-ink-soft',
    leaf: 'bg-cream-deep text-ink',
    carrot: 'bg-cream-deep text-ink',
  };
  return <span className={`inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-semibold ${tones[tone]}`}>{children}</span>;
}

/** 라디오 그룹처럼 동작하는 칩 선택기. */
export function ChoiceGroup<T extends string | number>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T | null;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <fieldset>
      <legend className="mb-1.5 text-sm font-semibold text-ink">{label}</legend>
      <div className="flex flex-wrap gap-2">
        {options.map((option) => {
          const selected = option.value === value;
          return (
            <button
              key={String(option.value)}
              type="button"
              aria-pressed={selected}
              onClick={() => onChange(option.value)}
              className={`min-h-11 rounded-md border px-4 text-sm font-semibold transition-colors ${
                selected ? 'border-mango-500 bg-cream-deep text-ink' : 'border-line bg-white text-ink-soft hover:bg-cream'
              }`}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

export function Loading({ label = '불러오는 중이에요' }: { label?: string }) {
  return (
    <div className="flex flex-col items-center gap-2 py-12 text-ink-muted" role="status">
      <PawPrint className="animate-bounce text-ink-muted" size={28} aria-hidden />
      <p className="text-sm">{label}</p>
    </div>
  );
}

export function ErrorNotice({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-md bg-[#ffedea] p-3 text-sm text-[#831c1e]" role="alert">
      <AlertTriangle size={18} className="mt-0.5 shrink-0" aria-hidden />
      <span>{message}</span>
    </div>
  );
}

export function InfoNotice({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-md bg-cream-deep p-3 text-sm text-ink">
      <Info size={18} className="mt-0.5 shrink-0" aria-hidden />
      <span>{children}</span>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 py-8 text-center">
      <PawPrint className="text-ink-muted" size={32} aria-hidden />
      <p className="font-semibold text-ink">{title}</p>
      {children}
    </div>
  );
}
