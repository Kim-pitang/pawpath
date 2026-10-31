import { useLocation } from 'react-router-dom';
import { PawPathMark, Wordmark } from '../components/Logo';
import { Card, LinkButton } from '../components/ui';

export default function GoodbyePage() {
  const location = useLocation();
  const retention = (location.state as { retention?: number | null } | null)?.retention;
  return (
    <div className="mx-auto flex min-h-dvh max-w-md flex-col gap-4 p-4">
      <header className="flex items-center gap-2">
        <PawPathMark />
        <Wordmark compact />
      </header>
      <h1 className="font-brand text-2xl text-leaf-800">탈퇴가 끝났어요</h1>
      <Card>
        <p className="text-sm text-ink-soft">계정과 반려동물, 산책 기록, 산책길, 사진을 서버에서 지웠어요. 공유한 링크도 닫혔고 이 기기에 남은 기록도 지웠어요.</p>
        {retention != null && <p className="mt-2 text-sm text-ink-soft">백업에 남은 사본은 {retention}일 안에 사라지고, 백업에서 복구해도 되살아나지 않아요.</p>}
        <LinkButton to="/" variant="ghost" className="mt-4 w-full">
          처음으로
        </LinkButton>
      </Card>
    </div>
  );
}
