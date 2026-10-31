import { Check, PawPrint, Pencil, Plus } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Card, Chip, EmptyState, LinkButton, PageTitle } from '../components/ui';
import { useApp } from '../context/AppContext';
import {
  ACTIVITY_LABELS,
  HEAT_LABELS,
  NOVELTY_LABELS,
  PATH_LABELS,
  PERSONALITY_LABELS,
  SIZE_LABELS,
} from '../lib/labels';

export default function PetsPage() {
  const { pets, petsLoaded, selectedPet, selectPet } = useApp();

  return (
    <div>
      <PageTitle sub="가족이 함께 돌보는 아이들이에요. 아이 정보가 추천 점수와 설명에 바로 반영돼요.">반려동물 프로필</PageTitle>
      <div className="grid gap-4 md:grid-cols-2">
        {pets.map((pet) => {
          const selected = selectedPet?.id === pet.id;
          return (
            <Card key={pet.id} className={selected ? 'border-leaf-300' : ''}>
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-3">
                  <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-carrot-50 text-carrot-500">
                    <PawPrint size={24} aria-hidden />
                  </span>
                  <div>
                    <h2 className="text-lg font-bold">{pet.name}</h2>
                    <p className="text-sm text-ink-soft">
                      {pet.breed} · {pet.age_years}세 · {pet.weight_kg}kg
                    </p>
                  </div>
                </div>
                <Link
                  to={`/pets/${pet.id}/edit`}
                  aria-label={`${pet.name} 프로필 수정`}
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-line text-ink-soft"
                >
                  <Pencil size={16} aria-hidden />
                </Link>
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                <Chip tone="leaf">{SIZE_LABELS[pet.size]}</Chip>
                <Chip tone="leaf">활동량 {ACTIVITY_LABELS[pet.activity_level]}</Chip>
                <Chip tone="carrot">{PERSONALITY_LABELS[pet.personality]}</Chip>
                <Chip tone="carrot">{PATH_LABELS[pet.path_preference]}</Chip>
                <Chip>{HEAT_LABELS[pet.heat_sensitivity]}</Chip>
                <Chip>낯선 환경: {NOVELTY_LABELS[pet.novelty_reaction]}</Chip>
              </div>
              <button
                type="button"
                disabled={selected}
                onClick={() => selectPet(pet.id)}
                className={`mt-4 flex min-h-11 w-full items-center justify-center gap-1.5 rounded-2xl text-sm font-bold ${
                  selected ? 'bg-leaf-50 text-leaf-800' : 'border border-line text-ink-soft hover:bg-cream'
                }`}
              >
                {selected && <Check size={16} aria-hidden />}
                {selected ? '지금 산책할 아이' : '이 아이로 추천받기'}
              </button>
            </Card>
          );
        })}
      </div>
      {petsLoaded && pets.length === 0 && (
        <Card>
          <EmptyState title="아직 등록된 반려동물이 없어요" />
        </Card>
      )}
      <LinkButton to="/pets/new" variant="ghost" className="mt-4 w-full">
        <Plus size={18} aria-hidden />
        반려동물 추가
      </LinkButton>
    </div>
  );
}
