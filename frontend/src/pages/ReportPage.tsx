import { ArrowDown, ArrowUp, Minus } from 'lucide-react';
import { useEffect, useState } from 'react';
import DailyColumns from '../components/charts/DailyColumns';
import RatingLine from '../components/charts/RatingLine';
import { Card, EmptyState, ErrorNotice, InfoNotice, LinkButton, Loading, PageTitle, SectionTitle } from '../components/ui';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import type { WalkReport } from '../lib/types';

export default function ReportPage() {
  const { selectedPet, petsLoaded } = useApp();
  const [weekOffset, setWeekOffset] = useState(0);
  const [report, setReport] = useState<WalkReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const petId = selectedPet?.id;

  useEffect(() => {
    if (!petId) return;
    let active = true;
    api
      .walkReport(petId, weekOffset)
      .then((result) => {
        if (!active) return;
        setReport(result);
        setError(null);
      })
      .catch((loadError: Error) => active && setError(loadError.message));
    return () => {
      active = false;
    };
  }, [petId, weekOffset]);

  if (petsLoaded && !selectedPet) {
    return (
      <Card>
        <EmptyState title="먼저 반려동물을 등록해 주세요">
          <LinkButton to="/pets/new">반려동물 등록하기</LinkButton>
        </EmptyState>
      </Card>
    );
  }
  if (error) return <ErrorNotice message={error} />;
  if (!report) return <Loading />;

  const { summary, change, recommendation_vs_actual: compared } = report;
  const period = `${report.week.start.slice(5).replace('-', '/')} ~ ${report.week.end.slice(5).replace('-', '/')}`;

  return (
    <div className="flex flex-col gap-4">
      <PageTitle sub={period}>{report.pet_name}의 주간 리포트</PageTitle>

      <div className="flex gap-1.5" role="group" aria-label="기간 선택">
        {[
          { offset: 0, label: '이번 주' },
          { offset: -1, label: '지난주' },
          { offset: -2, label: '2주 전' },
        ].map((option) => (
          <button
            key={option.offset}
            type="button"
            aria-pressed={weekOffset === option.offset}
            onClick={() => setWeekOffset(option.offset)}
            className={`min-h-9 rounded-full border px-3.5 text-sm font-semibold ${
              weekOffset === option.offset ? 'border-leaf-500 bg-leaf-500 text-white' : 'border-line bg-white text-ink-soft'
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>

      {report.simulated_walks_excluded > 0 && (
        <InfoNotice>이 주의 시연용 산책 {report.simulated_walks_excluded}건은 통계에서 제외했어요. 실제 산책만 집계해요.</InfoNotice>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="산책 횟수" value={`${summary.walk_count}번`} change={change.walk_count} unit="번" />
        <Stat label="누적 거리" value={`${summary.total_distance_km.toFixed(1)}km`} change={change.total_distance_km} unit="km" />
        <Stat label="누적 시간" value={`${summary.total_minutes}분`} change={change.total_minutes} unit="분" />
        <Stat label="평균 산책 시간" value={summary.average_minutes === null ? '기록 없음' : `${summary.average_minutes}분`} />
      </div>

      {summary.walk_count === 0 ? (
        <Card>
          <EmptyState title="이 주에는 실제 산책 기록이 없어요">
            <LinkButton to="/recommend">오늘의 추천 보기</LinkButton>
          </EmptyState>
        </Card>
      ) : (
        <Card>
          <SectionTitle>일별 산책 기록</SectionTitle>
          <DailyColumns days={report.daily} />
        </Card>
      )}

      <div className="grid items-start gap-4 md:grid-cols-2">
        {report.satisfaction_trend.length > 0 && (
          <Card>
            <SectionTitle>만족도 변화</SectionTitle>
            {report.satisfaction_trend.length === 1 ? (
              <p className="text-sm text-ink-soft">
                {report.satisfaction_trend[0].course_name} {report.satisfaction_trend[0].pet_rating}점. 피드백이 두 번 이상 쌓이면 그래프가 그려져요.
              </p>
            ) : (
              <RatingLine points={report.satisfaction_trend} />
            )}
          </Card>
        )}

        {report.favorite_courses.length > 0 && (
          <Card>
            <SectionTitle>선호 코스</SectionTitle>
            <ul className="flex flex-col divide-y divide-line" aria-label="선호 코스">
              {report.favorite_courses.map((course) => (
                <li key={course.course_id} className="flex items-center justify-between gap-2 py-2.5 first:pt-0 last:pb-0">
                  <span className="min-w-0 truncate text-sm font-semibold">{course.course_name}</span>
                  <span className="shrink-0 text-xs text-ink-soft">
                    {course.visit_count}번{course.average_pet_rating !== null && ` · 평균 ${course.average_pet_rating}점`}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        )}

        {compared.walks.length > 0 && (
          <Card>
            <SectionTitle>추천과 실제 선택</SectionTitle>
            <p className="mb-2 text-sm text-ink-soft">
              추천을 받고 나선 산책 {compared.walks.length}번 중 1위 코스 {compared.followed_top_count}번, TOP 3 안 {compared.in_top_three_count}번
            </p>
            <ul className="flex flex-col divide-y divide-line text-sm" aria-label="추천과 실제 선택 비교">
              {compared.walks.map((walk) => (
                <li key={walk.walk_id} className="py-2 first:pt-0 last:pb-0">
                  <p className="font-semibold">{walk.chosen}</p>
                  <p className="text-xs text-ink-soft">
                    {walk.followed_top ? '추천 1위를 선택' : walk.chosen_rank ? `추천 ${walk.chosen_rank}위를 선택 (1위: ${walk.recommended_top})` : `추천 밖 코스를 선택 (1위: ${walk.recommended_top})`}
                  </p>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value, change, unit }: { label: string; value: string; change?: { difference: number; percent: number | null }; unit?: string }) {
  const difference = change?.difference ?? 0;
  const Icon = difference > 0 ? ArrowUp : difference < 0 ? ArrowDown : Minus;
  const size = Math.abs(difference);
  return (
    <div className="rounded-3xl border border-line bg-white p-4">
      <p className="text-xs text-ink-muted">{label}</p>
      <p className="mt-1 text-xl font-bold">{value}</p>
      {change && (
        <p className="mt-1 flex items-center gap-0.5 text-xs text-ink-soft">
          <Icon size={12} aria-hidden />
          지난주보다 {difference === 0 ? '같아요' : `${Number.isInteger(size) ? size : size.toFixed(1)}${unit} ${difference > 0 ? '많아요' : '적어요'}`}
        </p>
      )}
    </div>
  );
}
