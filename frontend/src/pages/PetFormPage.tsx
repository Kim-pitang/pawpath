import { useEffect, useState, type FormEvent } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Button, Card, ChoiceGroup, ErrorNotice, Loading, PageTitle } from '../components/ui';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import {
  ACTIVITY_LABELS,
  HEAT_LABELS,
  NOVELTY_LABELS,
  PATH_LABELS,
  PERSONALITY_LABELS,
  SIZE_LABELS,
} from '../lib/labels';
import type { Level, NoveltyReaction, PathPreference, Personality, PetInput, Size } from '../lib/types';

function toOptions<T extends string>(labels: Record<T, string>) {
  return (Object.keys(labels) as T[]).map((value) => ({ value, label: labels[value] }));
}

interface FormState {
  name: string;
  breed: string;
  age_years: string;
  weight_kg: string;
  size: Size | null;
  activity_level: Level | null;
  personality: Personality | null;
  path_preference: PathPreference | null;
  heat_sensitivity: Level | null;
  novelty_reaction: NoveltyReaction | null;
}

const EMPTY_FORM: FormState = {
  name: '',
  breed: '',
  age_years: '',
  weight_kg: '',
  size: null,
  activity_level: null,
  personality: null,
  path_preference: null,
  heat_sensitivity: null,
  novelty_reaction: null,
};

const INPUT_CLASS = 'mt-1.5 min-h-12 w-full rounded-2xl border border-line bg-white px-4 text-base outline-none focus:border-leaf-500';

export default function PetFormPage() {
  const { petId } = useParams();
  const navigate = useNavigate();
  const { refreshPets, selectPet, invalidateRecommendations } = useApp();
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [loading, setLoading] = useState(Boolean(petId));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const editing = Boolean(petId);

  useEffect(() => {
    if (!petId) return;
    api
      .getPet(Number(petId))
      .then((pet) =>
        setForm({
          name: pet.name,
          breed: pet.breed,
          age_years: String(pet.age_years),
          weight_kg: String(pet.weight_kg),
          size: pet.size,
          activity_level: pet.activity_level,
          personality: pet.personality,
          path_preference: pet.path_preference,
          heat_sensitivity: pet.heat_sensitivity,
          novelty_reaction: pet.novelty_reaction,
        }),
      )
      .catch((loadError: Error) => setError(loadError.message))
      .finally(() => setLoading(false));
  }, [petId]);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((previous) => ({ ...previous, [key]: value }));

  const complete =
    form.name.trim() &&
    form.breed.trim() &&
    Number(form.age_years) >= 0 &&
    form.age_years !== '' &&
    Number(form.weight_kg) > 0 &&
    form.size &&
    form.activity_level &&
    form.personality &&
    form.path_preference &&
    form.heat_sensitivity &&
    form.novelty_reaction;

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!complete) {
      setError('모든 항목을 입력해 주세요.');
      return;
    }
    setSaving(true);
    setError(null);
    const body: PetInput = {
      name: form.name.trim(),
      breed: form.breed.trim(),
      age_years: Number(form.age_years),
      weight_kg: Number(form.weight_kg),
      size: form.size!,
      activity_level: form.activity_level!,
      personality: form.personality!,
      path_preference: form.path_preference!,
      heat_sensitivity: form.heat_sensitivity!,
      novelty_reaction: form.novelty_reaction!,
    };
    try {
      const saved = editing ? await api.updatePet(Number(petId), body) : await api.createPet(body);
      await refreshPets();
      selectPet(saved.id);
      invalidateRecommendations();
      navigate('/pets');
    } catch (submitError) {
      setError((submitError as Error).message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <Loading />;

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <PageTitle sub="입력한 내용으로 산책 시간과 코스를 추천해요.">
        {editing ? '프로필 수정' : '반려동물 등록'}
      </PageTitle>

      <Card className="grid gap-4 md:grid-cols-2">
        <label className="text-sm font-semibold">
          이름
          <input className={INPUT_CLASS} value={form.name} maxLength={30} onChange={(e) => update('name', e.target.value)} required />
        </label>
        <label className="text-sm font-semibold">
          견종
          <input className={INPUT_CLASS} value={form.breed} maxLength={50} onChange={(e) => update('breed', e.target.value)} required />
        </label>
        <label className="text-sm font-semibold">
          나이 (세)
          <input
            className={INPUT_CLASS}
            type="number"
            inputMode="decimal"
            step="0.5"
            min="0"
            max="35"
            value={form.age_years}
            onChange={(e) => update('age_years', e.target.value)}
            required
          />
        </label>
        <label className="text-sm font-semibold">
          체중 (kg)
          <input
            className={INPUT_CLASS}
            type="number"
            inputMode="decimal"
            step="0.1"
            min="0.1"
            max="120"
            value={form.weight_kg}
            onChange={(e) => update('weight_kg', e.target.value)}
            required
          />
        </label>
      </Card>

      <Card className="flex flex-col gap-5">
        <h2 className="font-bold">산책 성향</h2>
        <ChoiceGroup label="크기" value={form.size} options={toOptions(SIZE_LABELS)} onChange={(v) => update('size', v)} />
        <ChoiceGroup label="평소 활동량" value={form.activity_level} options={toOptions(ACTIVITY_LABELS)} onChange={(v) => update('activity_level', v)} />
        <ChoiceGroup label="성격" value={form.personality} options={toOptions(PERSONALITY_LABELS)} onChange={(v) => update('personality', v)} />
        <ChoiceGroup label="산책 선호도" value={form.path_preference} options={toOptions(PATH_LABELS)} onChange={(v) => update('path_preference', v)} />
        <ChoiceGroup label="더위 민감도" value={form.heat_sensitivity} options={toOptions(HEAT_LABELS)} onChange={(v) => update('heat_sensitivity', v)} />
        <ChoiceGroup label="낯선 환경에 대한 반응" value={form.novelty_reaction} options={toOptions(NOVELTY_LABELS)} onChange={(v) => update('novelty_reaction', v)} />
      </Card>

      {error && <ErrorNotice message={error} />}
      <Button type="submit" disabled={saving || !complete}>
        {saving ? '저장 중이에요' : editing ? '수정 완료' : '등록하기'}
      </Button>
    </form>
  );
}
