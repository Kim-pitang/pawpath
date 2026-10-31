// 보호자가 준 mungo 앱 아이콘을 그대로 쓴다. 원본 둘레의 흰 여백은 잘라 낸다.
export function MungoMark({ className = 'h-9 w-9' }: { className?: string }) {
  return (
    <span className={`block shrink-0 overflow-hidden rounded-[22%] ${className}`}>
      <img src="/mungo-logo.webp" alt="mungo 로고" className="h-full w-full scale-[1.26] object-cover" draggable={false} />
    </span>
  );
}

export function Wordmark({ compact = false }: { compact?: boolean }) {
  return <span className={`font-brand leading-none text-ink ${compact ? 'text-2xl' : 'text-4xl'}`}>mungo</span>;
}
