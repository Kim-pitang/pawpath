import { UserRound } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Card, EmptyState } from './ui';

/** 커뮤니티에 글을 남기려면 로그인해야 한다. 로그인한 뒤 지금 화면으로 돌아온다. */
export default function LoginPrompt({ title, children }: { title: string; children?: ReactNode }) {
  const location = useLocation();
  return (
    <Card>
      <EmptyState title={title}>
        {children}
        <Link
          to="/login"
          state={{ from: location.pathname + location.search }}
          className="inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl bg-leaf-500 px-5 text-sm font-bold text-white transition hover:bg-leaf-600"
        >
          <UserRound size={16} aria-hidden />
          로그인 또는 회원가입
        </Link>
      </EmptyState>
    </Card>
  );
}
