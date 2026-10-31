import { CheckCircle2, Footprints, PawPrint, Star, TrendingUp } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { Button, Card, Chip, ChoiceGroup, EmptyState, ErrorNotice, LinkButton, PageTitle, SectionTitle } from '../components/ui';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import { dateTimeLabel } from '../lib/format';
import { DIFFICULTY_LABELS } from '../lib/labels';
import type { Course, Difficulty, Feedback, Walk } from '../lib/types';

export default function WalkPage() {
  const { selectedPet, petsLoaded, invalidateRecommendations, refreshPets } = useApp();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [courses, setCourses] = useState<Course[]>([]);
  const [courseId, setCourseId] = useState<number | null>(Number(params.get('course')) || null);
  const [walks, setWalks] = useState<Walk[]>([]);
  // 길 안내를 마치고 넘어오면 방금 끝낸 산책의 피드백부터 받는다.
  const [activeWalk, setActiveWalk] = useState<Walk | null>((location.state as { walk?: Walk } | null)?.walk ?? null);
  const [result, setResult] = useState<Feedback | null>(null);
  const [duration, setDuration] = useState(30);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const recommendationId = Number(params.get('recommendation')) || null;
  const petId = selectedPet?.id;

  useEffect(() => {
    // 새로고침 때 이미 끝낸 피드백 폼이 다시 열리지 않도록 전달 값을 지운다.
    if (location.state) navigate(location.pathname + location.search, { replace: true, state: null });
  }, [location, navigate]);

  const loadWalks = useCallback(async () => {
    if (petId) setWalks(await api.listWalks(petId));
  }, [petId]);

  useEffect(() => {
    api.listCourses().then(setCourses).catch((loadError: Error) => setError(loadError.message));
  }, []);

  useEffect(() => {
    loadWalks().catch((loadError: Error) => setError(loadError.message));
  }, [loadWalks]);

  const course = courses.find((item) => item.id === courseId);
  useEffect(() => {
    if (course) setDuration(course.duration_min);
  }, [course]);

  const completeWalk = async () => {
    if (!petId || !courseId) return;
    setSaving(true);
    setError(null);
    try {
      const walk = await api.createWalk({
        pet_id: petId,
        course_id: courseId,
        recommendation_id: recommendationId,
        duration_min: duration,
      });
      setActiveWalk(walk);
      setResult(null);
      setCourseId(null);
      await loadWalks();
    } catch (saveError) {
      setError((saveError as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const onFeedbackDone = async (feedback: Feedback) => {
    setResult(feedback);
    setActiveWalk(null);
    invalidateRecommendations();
    await Promise.all([loadWalks(), refreshPets()]);
  };

  if (petsLoaded && !selectedPet) {
    return (
      <Card>
        <EmptyState title="먼저 반려동물을 등록해 주세요">
          <LinkButton to="/pets/new">반려동물 등록하기</LinkButton>
        </EmptyState>
      </Card>
    );
  }

  const pending = walks.filter((walk) => !walk.feedback && walk.id !== activeWalk?.id);

  return (
    <div className="flex flex-col gap-4">
      <PageTitle sub="피드백이 다음 추천을 바꿔요.">산책 기록</PageTitle>
      {error && <ErrorNotice message={error} />}

      {result && <FeedbackResult feedback={result} petName={selectedPet?.name ?? ''} onSeeChange={() => navigate('/recommend')} />}

      {activeWalk && selectedPet ? (
        <FeedbackForm walk={activeWalk} petName={selectedPet.name} onDone={onFeedbackDone} />
      ) : (
        !result && (
          <Card>
            <SectionTitle>산책 완료 처리</SectionTitle>
            <label className="text-sm font-semibold">
              다녀온 코스
              <select
                aria-label="다녀온 코스"
                className="mt-1.5 min-h-12 w-full rounded-2xl border border-line bg-white px-3 text-base"
                value={courseId ?? ''}
                onChange={(event) => setCourseId(Number(event.target.value) || null)}
              >
                <option value="">코스를 골라 주세요</option>
                {courses.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} ({item.distance_km.toFixed(1)}km)
                  </option>
                ))}
              </select>
            </label>
            {course && (
              <label className="mt-4 block text-sm font-semibold">
                실제 산책 시간: <span className="text-leaf-600">{duration}분</span>
                <input
                  type="range"
                  min={5}
                  max={120}
                  step={5}
                  value={duration}
                  onChange={(event) => setDuration(Number(event.target.value))}
                  className="mt-2 w-full accent-[var(--color-leaf-500)]"
                />
              </label>
            )}
            <Button className="mt-4 w-full" onClick={completeWalk} disabled={!courseId || saving}>
              <CheckCircle2 size={18} aria-hidden />
              {saving ? '저장 중이에요' : '산책 완료'}
            </Button>
          </Card>
        )
      )}

      {pending.length > 0 && !activeWalk && (
        <Card>
          <SectionTitle>피드백을 기다리는 산책</SectionTitle>
          <ul className="flex flex-col gap-2">
            {pending.map((walk) => (
              <li key={walk.id}>
                <button
                  type="button"
                  onClick={() => {
                    setActiveWalk(walk);
                    setResult(null);
                  }}
                  className="flex min-h-12 w-full items-center justify-between gap-2 rounded-2xl bg-carrot-50 px-3 text-left text-sm"
                >
                  <span className="font-semibold">{walk.course_name}</span>
                  <span className="shrink-0 text-xs font-semibold text-carrot-700">피드백 남기기</span>
                </button>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card>
        <SectionTitle>지난 산책</SectionTitle>
        {walks.length === 0 ? (
          <EmptyState title="아직 산책 기록이 없어요">
            <LinkButton to="/recommend" variant="ghost">오늘의 추천 보기</LinkButton>
          </EmptyState>
        ) : (
          <ul className="flex flex-col divide-y divide-line">
            {walks.map((walk) => (
              <li key={walk.id} className="py-3 first:pt-0 last:pb-0">
                <div className="flex items-center justify-between gap-2">
                  <p className="flex items-center gap-1.5 font-semibold">
                    {walk.course_name}
                    {walk.is_simulated && <Chip>시연용</Chip>}
                  </p>
                  {walk.feedback ? (
                    <Chip tone="leaf">
                      <PawPrint size={12} aria-hidden />
                      {walk.feedback.pet_rating}점
                    </Chip>
                  ) : (
                    <Chip tone="carrot">피드백 전</Chip>
                  )}
                </div>
                <p className="text-xs text-ink-soft">
                  {dateTimeLabel(walk.started_at)} · {walk.duration_min}분 · {walk.distance_km.toFixed(1)}km
                </p>
                {walk.feedback?.memo && <p className="mt-1 text-sm text-ink-soft">{walk.feedback.memo}</p>}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function Rating({ label, value, onChange, icon }: { label: string; value: number | null; onChange: (value: number) => void; icon: 'paw' | 'star' }) {
  const Icon = icon === 'paw' ? PawPrint : Star;
  return (
    <fieldset>
      <legend className="mb-1.5 text-sm font-semibold">{label}</legend>
      <div className="flex gap-1">
        {[1, 2, 3, 4, 5].map((score) => {
          const on = value !== null && score <= value;
          return (
            <button
              key={score}
              type="button"
              aria-label={`${label} ${score}점`}
              aria-pressed={value === score}
              onClick={() => onChange(score)}
              className={`flex h-12 flex-1 items-center justify-center rounded-2xl border transition ${
                on ? 'border-carrot-500 bg-carrot-50 text-carrot-500' : 'border-line bg-white text-ink-muted'
              }`}
            >
              <Icon size={22} fill={on ? 'currentColor' : 'none'} aria-hidden />
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

function FeedbackForm({ walk, petName, onDone }: { walk: Walk; petName: string; onDone: (feedback: Feedback) => void | Promise<void> }) {
  const [walkRating, setWalkRating] = useState<number | null>(null);
  const [petRating, setPetRating] = useState<number | null>(null);
  const [weatherRating, setWeatherRating] = useState<number | null>(null);
  const [difficulty, setDifficulty] = useState<Difficulty | null>(null);
  const [revisit, setRevisit] = useState<boolean | null>(null);
  const [memo, setMemo] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const complete = walkRating && petRating && weatherRating && difficulty && revisit !== null;

  const submit = async () => {
    if (!complete) return;
    setSaving(true);
    setError(null);
    try {
      const feedback = await api.submitFeedback({
        walk_id: walk.id,
        walk_rating: walkRating,
        pet_rating: petRating,
        difficulty,
        weather_rating: weatherRating,
        would_revisit: revisit,
        memo: memo.trim(),
      });
      await onDone(feedback);
    } catch (submitError) {
      setError((submitError as Error).message);
      setSaving(false);
    }
  };

  return (
    <Card className="border-carrot-100">
      <SectionTitle>{walk.course_name}, 어땠나요?</SectionTitle>
      <div className="flex flex-col gap-5">
        <Rating label="산책 만족도" value={walkRating} onChange={setWalkRating} icon="star" />
        <Rating label={`${petName} 만족도`} value={petRating} onChange={setPetRating} icon="paw" />
        <ChoiceGroup
          label="산책 난이도"
          value={difficulty}
          options={(Object.keys(DIFFICULTY_LABELS) as Difficulty[]).map((value) => ({ value, label: DIFFICULTY_LABELS[value] }))}
          onChange={setDifficulty}
        />
        <Rating label="날씨 만족도" value={weatherRating} onChange={setWeatherRating} icon="star" />
        <ChoiceGroup
          label="이 코스에 또 갈까요?"
          value={revisit === null ? null : revisit ? 'yes' : 'no'}
          options={[
            { value: 'yes', label: '또 갈래요' },
            { value: 'no', label: '다른 곳이 좋아요' },
          ]}
          onChange={(value) => setRevisit(value === 'yes')}
        />
        <label className="text-sm font-semibold">
          추가 메모
          <textarea
            value={memo}
            maxLength={500}
            rows={2}
            onChange={(event) => setMemo(event.target.value)}
            placeholder="오늘 산책에서 기억하고 싶은 점"
            className="mt-1.5 w-full rounded-2xl border border-line p-3 text-base outline-none focus:border-leaf-500"
          />
        </label>
        {error && <ErrorNotice message={error} />}
        <Button onClick={submit} disabled={!complete || saving}>
          {saving ? '저장 중이에요' : '피드백 남기기'}
        </Button>
      </div>
    </Card>
  );
}

function FeedbackResult({ feedback, petName, onSeeChange }: { feedback: Feedback; petName: string; onSeeChange: () => void }) {
  const delta = feedback.affinity_after - feedback.affinity_before;
  return (
    <Card className="border-leaf-300 bg-leaf-50">
      <p className="flex items-center gap-1.5 font-bold text-leaf-800">
        <TrendingUp size={19} aria-hidden />
        {petName}의 취향을 배웠어요
      </p>
      <p className="mt-2 text-sm text-ink">
        {feedback.course_name} 선호도가{' '}
        <strong data-testid="affinity-change">
          {feedback.affinity_before.toFixed(0)}점에서 {feedback.affinity_after.toFixed(0)}점
        </strong>
        으로 {delta >= 0 ? '올랐어요' : '내려갔어요'}. 다음 추천부터 바로 반영돼요.
      </p>
      <Button className="mt-3 w-full" onClick={onSeeChange}>
        <Footprints size={16} aria-hidden />
        달라진 추천 보기
      </Button>
    </Card>
  );
}
