import { useEffect, useMemo, useState } from 'react';
import PreferenceRanking from '../components/charts/PreferenceRanking';
import HBarChart from '../components/charts/HBarChart';
import ScoreTrendChart from '../components/charts/ScoreTrendChart';
import TimePreferenceCards from '../components/charts/TimePreferenceCards';
import AccountCard from '../components/AccountCard';
import { Card, EmptyState, ErrorNotice, InfoNotice, LinkButton, Loading, PageTitle, SectionTitle } from '../components/ui';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import { dateTimeLabel } from '../lib/format';
import type { Insights } from '../lib/types';

export default function MyPage() {
  const { selectedPet, petsLoaded } = useApp();
  const [insights, setInsights] = useState<Insights | null>(null);
  const [error, setError] = useState<string | null>(null);
  const petId = selectedPet?.id;

  useEffect(() => {
    if (!petId) return;
    let active = true;
    setInsights(null);
    // 계정이 바뀌어 반려동물이 달라지면 이전 오류를 남기지 않는다.
    setError(null);
    api
      .insights(petId)
      .then((result) => active && setInsights(result))
      .catch((loadError: Error) => active && setError(loadError.message));
    return () => {
      active = false;
    };
  }, [petId]);

  // 날씨가 다르면 점수 변화의 원인을 알 수 없으므로, 최신 추천과 같은 날씨 조건끼리만 비교한다.
  const trend = useMemo(() => {
    const history = insights?.recommendation_history ?? [];
    const latest = history[history.length - 1];
    return latest ? history.filter((record) => record.scenario === latest.scenario) : [];
  }, [insights]);

  if (petsLoaded && !selectedPet) {
    return (
      <div className="flex flex-col gap-4">
        <AccountCard />
        <Card>
          <EmptyState title="먼저 반려동물을 등록해 주세요">
            <LinkButton to="/pets/new">반려동물 등록하기</LinkButton>
          </EmptyState>
        </Card>
      </div>
    );
  }
  if (error) return <ErrorNotice message={error} />;
  if (!insights) return <Loading />;

  const { stats } = insights;
  const hasWalks = stats.walk_count > 0 || stats.simulated_walk_count > 0;
  const hasFeedback = stats.feedback_count > 0;
  const preferenceRanking = [...insights.courses].filter((c) => c.feedback_count > 0).sort((a, b) => b.affinity - a.affinity);

  return (
    <div className="flex flex-col gap-4">
      <PageTitle sub="산책이 쌓일수록 추천이 똑똑해져요.">{insights.pet_name}의 산책 리포트</PageTitle>
      <AccountCard />

      <div className="grid grid-cols-2 gap-2">
        <LinkButton to="/report" variant="ghost" className="!px-2">
          주간 활동 리포트 보기
        </LinkButton>
        <LinkButton to="/my-walks" variant="ghost" className="!px-2">
          나의 산책길
        </LinkButton>
      </div>
      {stats.simulated_walk_count > 0 && (
        <InfoNotice>시연용 산책 {stats.simulated_walk_count}건은 아래 활동 통계에서 제외했어요. 피드백 학습에는 반영돼요.</InfoNotice>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="산책 횟수" value={`${stats.walk_count}번`} />
        <Stat label="총 거리" value={`${stats.total_distance_km.toFixed(1)}km`} />
        <Stat label="총 시간" value={`${stats.total_minutes}분`} />
        <Stat label="평균 만족도" value={stats.average_pet_rating === null ? '기록 없음' : `${stats.average_pet_rating}점`} />
      </div>

      {!hasWalks && (
        <Card>
          <EmptyState title="산책을 다녀오면 분석이 시작돼요">
            <LinkButton to="/recommend">오늘의 추천 보기</LinkButton>
          </EmptyState>
        </Card>
      )}

      <div className="grid items-start gap-4 md:grid-cols-2">
        {hasWalks && (
          <Card>
            <SectionTitle>자주 이용한 코스</SectionTitle>
            <ul className="flex flex-col divide-y divide-line">
              {insights.courses.slice(0, 5).map((course) => (
                <li key={course.course_id} className="flex items-center justify-between gap-2 py-2.5 first:pt-0 last:pb-0">
                  <span className="min-w-0 truncate text-sm font-semibold">{course.course_name}</span>
                  <span className="shrink-0 text-xs text-ink-soft">
                    {course.visit_count}번
                    {course.average_pet_rating !== null && ` · 평균 ${course.average_pet_rating}점`}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        )}

        {hasFeedback && (
          <Card>
            <SectionTitle>코스 선호도</SectionTitle>
            <HBarChart
              ariaLabel="코스별 선호도"
              items={preferenceRanking.map((course) => ({
                key: course.course_id,
                label: course.course_name,
                value: course.affinity,
              }))}
            />
            <p className="mt-2 text-xs text-ink-muted">세로선은 중립값 50점이에요.</p>
          </Card>
        )}

        {insights.attributes_learned && (
          <Card>
            <SectionTitle>{insights.pet_name}의 취향 분석</SectionTitle>
            <PreferenceRanking key={insights.pet_id} insights={insights} />
          </Card>
        )}

        {hasFeedback && (
          <Card>
            <SectionTitle>시간대 선호</SectionTitle>
            <TimePreferenceCards key={insights.pet_id} items={insights.time_preferences} />
          </Card>
        )}

        {trend.length >= 2 ? (
          <Card>
            <SectionTitle>추천 결과 변화</SectionTitle>
            <ScoreTrendChart history={trend} />
            <p className="mt-2 text-xs text-ink-muted">같은 날씨 조건에서 받은 추천끼리 비교했어요.</p>
          </Card>
        ) : (
          hasFeedback && (
            <Card>
              <SectionTitle>추천 결과 변화</SectionTitle>
              <p className="text-sm text-ink-soft">같은 날씨 조건에서 추천을 두 번 이상 받으면 변화가 그려져요.</p>
              <LinkButton to="/recommend" variant="ghost" className="mt-3 w-full">다시 추천받기</LinkButton>
            </Card>
          )
        )}

        {hasFeedback && (
          <Card>
            <SectionTitle>피드백 기록</SectionTitle>
            <ul className="flex flex-col divide-y divide-line">
              {[...insights.affinity_history].reverse().slice(0, 6).map((item) => (
                <li key={item.feedback_id} className="py-2.5 first:pt-0 last:pb-0">
                  <div className="flex items-center justify-between gap-2 text-sm">
                    <span className="min-w-0 truncate font-semibold">{item.course_name}</span>
                    <span className="shrink-0 tabular-nums text-ink">
                      {item.before.toFixed(0)} → {item.after.toFixed(0)}점
                    </span>
                  </div>
                  <p className="text-xs text-ink-muted">
                    {dateTimeLabel(item.created_at)} · {insights.pet_name} 만족도 {item.pet_rating}점
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

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-line bg-white p-4">
      <p className="text-xs text-ink-muted">{label}</p>
      <p className="mt-1 text-xl font-bold">{value}</p>
    </div>
  );
}
