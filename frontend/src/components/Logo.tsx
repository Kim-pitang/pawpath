export function PawPathMark({ className = 'h-9 w-9' }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={className} role="img" aria-label="PawPath 로고">
      <ellipse cx="14" cy="27" rx="6.5" ry="8.5" fill="var(--color-carrot-500)" transform="rotate(-18 14 27)" />
      <ellipse cx="26" cy="14" rx="6.5" ry="9" fill="var(--color-carrot-500)" />
      <ellipse cx="42" cy="14" rx="6.5" ry="9" fill="var(--color-carrot-500)" />
      <ellipse cx="53" cy="27" rx="6.5" ry="8.5" fill="var(--color-carrot-500)" transform="rotate(18 53 27)" />
      <path
        d="M34 26c10 0 19 10 19 20 0 8-6 12-13 11-4-.5-8-.5-12 0-7 1-13-3-13-11 0-10 9-20 19-20Z"
        fill="var(--color-leaf-500)"
      />
      <path
        d="M26 55c5-6-5-9 2-15 4-3 10-3 9-8"
        fill="none"
        stroke="var(--color-cream)"
        strokeWidth="3.2"
        strokeLinecap="round"
        strokeDasharray="1 6"
      />
    </svg>
  );
}

export function Wordmark({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex flex-col leading-none">
      <span className={`font-brand text-leaf-800 ${compact ? 'text-xl' : 'text-3xl'}`}>PawPath</span>
      <span className={`mt-0.5 font-brand text-carrot-700 ${compact ? 'text-xs' : 'text-base'}`}>댕댕 산책각</span>
    </span>
  );
}
