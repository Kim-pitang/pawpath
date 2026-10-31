import { CheckCircle2, Footprints, PawPrint, Route, Star, Trash2, TrendingUp } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { Button, Card, Chip, ChoiceGroup, EmptyState, ErrorNotice, LinkButton, PageTitle, SectionTitle } from '../components/ui';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import { dateTimeLabel, toLocalIso } from '../lib/format';
import { DIFFICULTY_LABELS } from '../lib/labels';
import type { Course, Difficulty, Feedback, Walk } from '../lib/types';

/** 지난 산책과 피드백을 기다리는 산책은 이만큼 먼저 보여 주고 나머지는 더 보기로 연다. */
const RECENT_WALKS = 10;
const RECENT_PENDING = 3;
const MINUTE_MS = 60_000;

type When = 'now' | 'earlier';
const WHEN_OPTIONS: { value: When; label: string }[] = [
  { value: 'now', label: '방금 끝났어요' },
  { value: 'earlier', label: '다른 시각에 다녀왔어요' },
];

/** datetime-local 입력 형식(분까지)의 현지 시각. */
const toInputValue = (ms: number) => toLocalIso(new Date(ms)).slice(0, 16);

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
  // 커뮤니티 산책길을 걷고 피드백을 남겼으면 그 길의 후기로 잇는다.
  const [reviewTrailId, setReviewTrailId] = useState<number | null>(null);
  const [duration, setDuration] = useState(30);
  // 출발 시각은 시간대 학습에 쓰여서, 나중에 기록할 때는 실제 시각을 받는다.
  const [when, setWhen] = useState<When>('now');
  const [startedAt, setStartedAt] = useState('');
  const [showAll, setShowAll] = useState(false);
  const [showAllPending, setShowAllPending] = useState(false);
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

  const startMs = when === 'earlier' && startedAt ? new Date(startedAt).getTime() : null;
  const startError =
    when !== 'earlier'
      ? null
      : startMs === null || Number.isNaN(startMs)
        ? '출발 시각을 골라 주세요.'
        : startMs + duration * MINUTE_MS > Date.now()
          ? '아직 끝나지 않은 시각이에요. 출발 시각이나 산책 시간을 확인해 주세요.'
          : null;

  const chooseWhen = (value: When) => {
    setWhen(value);
    // 처음 열면 방금 끝난 산책의 출발 시각을 채워 두고 고치게 한다.
    if (value === 'earlier' && !startedAt) setStartedAt(toInputValue(Date.now() - duration * MINUTE_MS));
  };

  const completeWalk = async () => {
    if (!petId || !courseId || startError) return;
    setSaving(true);
    setError(null);
    try {
      const walk = await api.createWalk({
        pet_id: petId,
        course_id: courseId,
        recommendation_id: recommendationId,
        duration_min: duration,
        started_at: when === 'earlier' ? `${startedAt}:00` : undefined,
      });
      setActiveWalk(walk);
      setResult(null);
      setCourseId(null);
      setWhen('now');
      setStartedAt('');
      // 추천에서 넘겨받은 코스와 추천 번호는 이번 기록에만 쓴다.
      if (params.toString()) navigate('/walk', { replace: true });
      await loadWalks();
    } catch (saveError) {
      setError((saveError as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const removeWalk = async (walk: Walk) => {
    if (!window.confirm(`${dateTimeLabel(walk.started_at)} ${walk.course_name} 기록을 지울까요? 되돌릴 수 없어요.`)) return;
    setError(null);
    try {
      await api.deleteWalk(walk.id);
      if (activeWalk?.id === walk.id) setActiveWalk(null);
      // 방문 수가 추천 점수에 쓰이므로 추천을 다시 받게 한다.
      invalidateRecommendations();
      await loadWalks();
    } catch (deleteError) {
      setError((deleteError as Error).message);
    }
  };

  const onFeedbackDone = async (feedback: Feedback) => {
    setResult(feedback);
    setReviewTrailId(activeWalk?.community_trail_id ?? null);
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
  const shownPending = showAllPending ? pending : pending.slice(0, RECENT_PENDING);
  const shownWalks = showAll ? walks : walks.slice(0, RECENT_WALKS);

  return (
    <div className="flex flex-col gap-4">
      <PageTitle sub="피드백이 다음 추천을 바꿔요.">산책 기록</PageTitle>
      {error && <ErrorNotice message={error} />}

      <div>
        <div className="grid grid-cols-2 gap-2">
          <LinkButton to="/record" className="!px-2">
            <Footprints size={18} aria-hidden />
            GPS로 산책 기록
          </LinkButton>
          <LinkButton to="/my-walks" variant="ghost" className="!px-2">
            <Route size={18} aria-hidden />
            나의 산책길
          </LinkButton>
        </div>
        <p className="mt-2 text-xs text-ink-muted">GPS로 기록한 산책은 나의 산책길에 저장돼요. 이 화면의 기록과 피드백은 추천 학습에 쓰여요.</p>
      </div>

      {result && <FeedbackResult feedback={result} petName={selectedPet?.name ?? ''} onSeeChange={() => navigate('/recommend')} />}
      {result && reviewTrailId && (
        <LinkButton to={`/community/trails/${reviewTrailId}#reviews`} variant="accent">
          이 산책길에 후기 남기기
        </LinkButton>
      )}

      {activeWalk && selectedPet ? (
        <FeedbackForm walk={activeWalk} petName={selectedPet.name} onDone={onFeedbackDone} onDelete={() => removeWalk(activeWalk)} />
      ) : (
        !result && (
          <Card>
            <SectionTitle>GPS 없이 기록하기</SectionTitle>
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
                    {item.name} ({item.distance_km.toFixed(1)}km){item.is_personal ? ' · 내 산책길' : ''}
                  </option>
                ))}
              </select>
            </label>
            {course && (
              <>
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
                <div className="mt-4">
                  <ChoiceGroup label="언제 다녀왔나요?" value={when} options={WHEN_OPTIONS} onChange={chooseWhen} />
                  {when === 'earlier' && (
                    <label className="mt-3 block text-sm font-semibold">
                      출발 시각
                      <input
                        type="datetime-local"
                        value={startedAt}
                        max={toInputValue(Date.now() - duration * MINUTE_MS)}
                        onChange={(event) => setStartedAt(event.target.value)}
                        aria-invalid={Boolean(startError)}
                        aria-describedby={startError ? 'start-error' : undefined}
                        className="mt-1.5 min-h-12 w-full rounded-2xl border border-line bg-white px-3 text-base"
                      />
                    </label>
                  )}
                  {startError && (
                    <p id="start-error" className="mt-2 text-sm font-semibold text-carrot-700">
                      {startError}
                    </p>
                  )}
                </div>
              </>
            )}
            <Button className="mt-4 w-full" onClick={completeWalk} disabled={!courseId || saving || Boolean(startError)}>
              <CheckCircle2 size={18} aria-hidden />
              {saving ? '저장 중이에요' : '산책 완료'}
            </Button>
          </Card>
        )
      )}

      {pending.length > 0 && !activeWalk && (
        <Card>
          <SectionTitle>피드백을 기다리는 산책</SectionTitle>
          <ul className="flex flex-col gap-2" aria-label="피드백을 기다리는 산책">
            {shownPending.map((walk) => (
              <li key={walk.id} className="flex gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setActiveWalk(walk);
                    setResult(null);
                  }}
                  className="flex min-h-12 min-w-0 flex-1 items-center justify-between gap-2 rounded-2xl bg-carrot-50 px-3 py-2 text-left text-sm"
                >
                  <span className="min-w-0">
                    <span className="block truncate font-semibold">{walk.course_name}</span>
                    <span className="block text-xs text-ink-soft">
                      {dateTimeLabel(walk.started_at)} · {walk.duration_min}분
                    </span>
                  </span>
                  <span className="shrink-0 text-xs font-semibold text-carrot-700">피드백 남기기</span>
                </button>
                <button
                  type="button"
                  aria-label={`${dateTimeLabel(walk.started_at)} ${walk.course_name} 기록 지우기`}
                  onClick={() => removeWalk(walk)}
                  className="flex min-h-12 w-12 shrink-0 items-center justify-center rounded-2xl border border-line bg-white text-ink-muted hover:text-carrot-700"
                >
                  <Trash2 size={18} aria-hidden />
                </button>
              </li>
            ))}
          </ul>
          {pending.length > RECENT_PENDING && (
            <button
              type="button"
              onClick={() => setShowAllPending((value) => !value)}
              className="mt-2 min-h-11 w-full rounded-2xl text-sm font-semibold text-carrot-700 hover:bg-carrot-50"
            >
              {showAllPending ? `최근 ${RECENT_PENDING}개만 보기` : `${pending.length - RECENT_PENDING}개 더 보기`}
            </button>
          )}
        </Card>
      )}

      <Card>
        <SectionTitle>지난 산책</SectionTitle>
        {walks.length === 0 ? (
          <EmptyState title="아직 산책 기록이 없어요">
            <LinkButton to="/recommend" variant="ghost">오늘의 추천 보기</LinkButton>
          </EmptyState>
        ) : (
          <>
            <ul className="flex flex-col divide-y divide-line" aria-label="지난 산책">
              {shownWalks.map((walk) => (
                <li key={walk.id} className="py-3 first:pt-0 last:pb-0">
                  <div className="flex items-center justify-between gap-2">
                    <p className="flex items-center gap-1.5 font-semibold">
                      {walk.course_name}
                      {walk.is_simulated && <Chip>시연용</Chip>}
                    </p>
                    {walk.feedback ? (
                      <Chip tone="leaf">
                        <PawPrint size={12} aria-hidden />
                        <span className="sr-only">{selectedPet?.name} 만족도</span>
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
            {walks.length > RECENT_WALKS && (
              <button
                type="button"
                onClick={() => setShowAll((value) => !value)}
                className="mt-3 min-h-11 w-full rounded-2xl text-sm font-semibold text-leaf-800 hover:bg-leaf-50"
              >
                {showAll ? `최근 ${RECENT_WALKS}개만 보기` : `지난 산책 ${walks.length - RECENT_WALKS}개 더 보기`}
              </button>
            )}
          </>
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

function FeedbackForm({
  walk,
  petName,
  onDone,
  onDelete,
}: {
  walk: Walk;
  petName: string;
  onDone: (feedback: Feedback) => void | Promise<void>;
  onDelete: () => void;
}) {
  const [walkRating, setWalkRating] = useState<number | null>(null);
  const [petRating, setPetRating] = useState<number | null>(null);
  const [weatherRating, setWeatherRating] = useState<number | null>(null);
  const [difficulty, setDifficulty] = useState<Difficulty | null>(null);
  const [revisit, setRevisit] = useState<boolean | null>(null);
  const [memo, setMemo] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const complete = walkRating && petRating && weatherRating && difficulty && revisit !== null;
  // 버튼이 왜 눌리지 않는지 알 수 있게 남은 항목을 알려 준다.
  const missing = [
    !walkRating && '산책 만족도',
    !petRating && `${petName} 만족도`,
    !difficulty && '난이도',
    !weatherRating && '날씨 만족도',
    revisit === null && '또 갈지',
  ].filter(Boolean);

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
      <p className="-mt-2 mb-4 text-xs text-ink-soft" data-testid="feedback-walk-time">
        {dateTimeLabel(walk.started_at)} 출발 · {walk.duration_min}분
      </p>
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
        <div>
          <Button className="w-full" onClick={submit} disabled={!complete || saving} aria-describedby={missing.length ? 'feedback-missing' : undefined}>
            {saving ? '저장 중이에요' : '피드백 남기기'}
          </Button>
          {missing.length > 0 && (
            <p id="feedback-missing" className="mt-2 text-center text-xs text-ink-muted">
              아직 고르지 않았어요: {missing.join(', ')}
            </p>
          )}
        </div>
        <button type="button" onClick={onDelete} className="min-h-11 text-sm font-semibold text-ink-muted underline hover:text-carrot-700">
          잘못 기록했어요. 이 기록 지우기
        </button>
      </div>
    </Card>
  );
}

function FeedbackResult({ feedback, petName, onSeeChange }: { feedback: Feedback; petName: string; onSeeChange: () => void }) {
  // 화면에 보이는 점수로 비교해야 '50점에서 50점으로 올랐어요' 같은 문장이 나오지 않는다.
  const before = Math.round(feedback.affinity_before);
  const after = Math.round(feedback.affinity_after);
  return (
    <Card className="border-leaf-300 bg-leaf-50">
      <p className="flex items-center gap-1.5 font-bold text-leaf-800">
        <TrendingUp size={19} aria-hidden />
        {petName}의 취향을 배웠어요
      </p>
      <p className="mt-2 text-sm text-ink">
        {before === after ? (
          <>
            {feedback.course_name} 선호도는 <strong data-testid="affinity-change">{after}점</strong> 그대로예요.
          </>
        ) : (
          <>
            {feedback.course_name} 선호도가{' '}
            <strong data-testid="affinity-change">
              {before}점에서 {after}점
            </strong>
            으로 {after > before ? '올랐어요' : '내려갔어요'}.
          </>
        )}{' '}
        다음 추천부터 바로 반영돼요.
      </p>
      <Button className="mt-3 w-full" onClick={onSeeChange}>
        <Footprints size={16} aria-hidden />
        달라진 추천 보기
      </Button>
    </Card>
  );
}
