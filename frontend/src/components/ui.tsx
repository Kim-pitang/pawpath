import { AlertTriangle, Info, PawPrint } from 'lucide-react';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { Link } from 'react-router-dom';

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-3xl border border-line bg-white p-5 shadow-[0_2px_10px_rgb(120_90_40/0.06)] ${className}`}>{children}</section>;
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
      <h1 className="font-brand text-2xl text-leaf-800">{children}</h1>
      {sub && <p className="mt-1 text-sm text-ink-soft">{sub}</p>}
    </div>
  );
}

const BUTTON_STYLES = {
  primary: 'bg-leaf-500 text-white hover:bg-leaf-600 disabled:bg-leaf-100 disabled:text-ink-muted',
  accent: 'bg-carrot-500 text-white hover:bg-carrot-700 disabled:bg-carrot-100 disabled:text-ink-muted',
  ghost: 'border border-line bg-white text-ink hover:bg-cream disabled:text-ink-muted',
};
type ButtonVariant = keyof typeof BUTTON_STYLES;
const BUTTON_BASE =
  'inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl px-5 text-sm font-bold transition disabled:cursor-not-allowed';

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
  onClick,
  children,
}: {
  to: string;
  variant?: ButtonVariant;
  className?: string;
  onClick?: () => void;
  children: ReactNode;
}) {
  return (
    <Link to={to} onClick={onClick} className={`${BUTTON_BASE} ${BUTTON_STYLES[variant]} ${className}`}>
      {children}
    </Link>
  );
}

export function Chip({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'leaf' | 'carrot' }) {
  const tones = {
    neutral: 'bg-cream-deep text-ink-soft',
    leaf: 'bg-leaf-50 text-leaf-800',
    carrot: 'bg-carrot-50 text-carrot-700',
  };
  return <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ${tones[tone]}`}>{children}</span>;
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
              className={`min-h-11 rounded-2xl border px-4 text-sm font-semibold transition ${
                selected ? 'border-leaf-500 bg-leaf-500 text-white' : 'border-line bg-white text-ink-soft hover:bg-leaf-50'
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
      <PawPrint className="animate-bounce text-carrot-500" size={28} aria-hidden />
      <p className="text-sm">{label}</p>
    </div>
  );
}

export function ErrorNotice({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-2xl bg-carrot-50 p-3 text-sm text-carrot-700" role="alert">
      <AlertTriangle size={18} className="mt-0.5 shrink-0" aria-hidden />
      <span>{message}</span>
    </div>
  );
}

export function InfoNotice({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-2xl bg-leaf-50 p-3 text-sm text-leaf-800">
      <Info size={18} className="mt-0.5 shrink-0" aria-hidden />
      <span>{children}</span>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 py-8 text-center">
      <PawPrint className="text-carrot-300" size={36} aria-hidden />
      <p className="font-semibold text-ink">{title}</p>
      {children}
    </div>
  );
}
