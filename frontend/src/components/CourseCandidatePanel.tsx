import { Undo2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import type { SavedWalkDetail } from '../lib/types';
import { Button, Card, Chip, ErrorNotice, InfoNotice, SectionTitle } from './ui';

/** 저장할 때 자동으로 들어간 추천 후보 상태를 보여 주고, 원하면 뺀다. */
export default function CourseCandidatePanel({ walk, onChange }: { walk: SavedWalkDetail; onChange: (walk: SavedWalkDetail) => void }) {
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const course = walk.course;
  const active = course?.active ?? false;
  const measuring = active && course?.measurement === 'pending';

  // 주변 환경 측정은 서버가 응답 뒤에 하므로, 끝날 때까지 3초마다 다시 읽는다. 2분이 지나면 멈춘다.
  useEffect(() => {
    if (!measuring) return;
    let tries = 0;
    const timer = window.setInterval(() => {
      tries += 1;
      if (tries > 40) window.clearInterval(timer);
      api.getSavedWalk(walk.id).then(onChange).catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [measuring, walk.id, onChange]);

  const run = async (action: () => Promise<SavedWalkDetail>) => {
    setWorking(true);
    setError(null);
    try {
      onChange(await action());
    } catch (actionError) {
      setError((actionError as Error).message);
    } finally {
      setWorking(false);
    }
  };

  return (
    <Card>
      <SectionTitle action={active ? <Chip tone="leaf">추천 후보</Chip> : undefined}>추천 후보</SectionTitle>
      <div className="flex flex-col gap-3" data-testid="course-candidate">
        {active && course ? (
          <>
            <p className="text-sm text-ink-soft">
              저장할 때 추천 후보에 넣었어요. 날씨와 반려동물에 맞으면 추천 목록에 나오고, 지도에서 길 안내도 받을 수 있어요. 이 코스는 나에게만 보여요.
            </p>
            {course.notes.map((note) => (
              <InfoNotice key={note}>{note}</InfoNotice>
            ))}
            <div className="grid grid-cols-2 gap-2">
              <Link
                to={`/map?course=${course.id}`}
                className="inline-flex min-h-12 items-center justify-center rounded-2xl border border-line bg-white px-3 text-sm font-bold text-ink hover:bg-cream"
              >
                지도에서 보기
              </Link>
              <Button variant="ghost" disabled={working} onClick={() => run(() => api.unregisterCourse(walk.id))}>
                <Undo2 size={16} aria-hidden />
                추천 후보에서 빼기
              </Button>
            </div>
            {course.measurement === 'failed' && (
              <Button variant="ghost" disabled={working} onClick={() => run(() => api.registerCourse(walk.id))}>
                환경 다시 측정하기
              </Button>
            )}
          </>
        ) : walk.course_blocked ? (
          <p className="text-sm text-ink-soft" data-testid="course-blocked">
            이 산책길은 추천 후보로 쓸 수 없어요. {walk.course_blocked}
          </p>
        ) : (
          <>
            <p className="text-sm text-ink-soft">추천 후보에서 뺀 산책길이에요. 추천 목록과 지도에 나오지 않아요.</p>
            <Button variant="ghost" disabled={working} onClick={() => run(() => api.registerCourse(walk.id))}>
              <Undo2 size={16} aria-hidden />
              {working ? '되돌리는 중이에요' : '다시 추천 후보로'}
            </Button>
          </>
        )}
        {error && <ErrorNotice message={error} />}
      </div>
    </Card>
  );
}
