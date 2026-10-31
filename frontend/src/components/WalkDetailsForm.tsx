import { useApp } from '../context/AppContext';
import { VISIBILITY_HINTS, VISIBILITY_LABELS } from '../lib/labels';
import type { Visibility } from '../lib/types';
import { ChoiceGroup, ErrorNotice } from './ui';

export interface WalkDetailsValue {
  title: string;
  petId: number | null;
  memo: string;
  visibility: Visibility;
  shareMemo: boolean;
}

const INPUT_CLASS = 'mt-1.5 min-h-12 w-full rounded-2xl border border-line bg-white px-4 text-base outline-none focus:border-leaf-500';
const VISIBILITY_OPTIONS = (Object.keys(VISIBILITY_LABELS) as Visibility[]).map((value) => ({ value, label: VISIBILITY_LABELS[value] }));

export const PRIVACY_WARNING = 'GPS 경로에는 집 주소 같은 민감한 위치가 드러날 수 있어요. 출발점과 도착점을 확인한 뒤 공유해 주세요.';

/** 기록 저장, GPX 가져오기, 상세 수정 화면이 함께 쓰는 입력 항목. */
export default function WalkDetailsForm({ value, onChange }: { value: WalkDetailsValue; onChange: (value: WalkDetailsValue) => void }) {
  const { pets } = useApp();
  const update = <K extends keyof WalkDetailsValue>(key: K, next: WalkDetailsValue[K]) => onChange({ ...value, [key]: next });

  return (
    <div className="flex flex-col gap-4">
      <label className="text-sm font-semibold">
        산책길 이름
        <input className={INPUT_CLASS} value={value.title} maxLength={80} onChange={(event) => update('title', event.target.value)} />
      </label>
      <label className="text-sm font-semibold">
        반려동물
        <select className={INPUT_CLASS} value={value.petId ?? ''} onChange={(event) => update('petId', Number(event.target.value) || null)}>
          <option value="">선택 안 함</option>
          {pets.map((pet) => (
            <option key={pet.id} value={pet.id}>
              {pet.name}
            </option>
          ))}
        </select>
      </label>
      <label className="text-sm font-semibold">
        산책 메모
        <textarea
          className="mt-1.5 min-h-24 w-full rounded-2xl border border-line bg-white p-4 text-base outline-none focus:border-leaf-500"
          value={value.memo}
          maxLength={1000}
          onChange={(event) => update('memo', event.target.value)}
        />
      </label>
      <div>
        <ChoiceGroup label="공개 범위" value={value.visibility} options={VISIBILITY_OPTIONS} onChange={(next) => update('visibility', next)} />
        <p className="mt-1.5 text-xs text-ink-muted">{VISIBILITY_HINTS[value.visibility]}</p>
      </div>
      {value.visibility !== 'private' && (
        <>
          <label className="flex min-h-11 items-center gap-2 text-sm font-semibold">
            <input type="checkbox" className="h-5 w-5 accent-leaf-500" checked={value.shareMemo} onChange={(event) => update('shareMemo', event.target.checked)} />
            공유 화면에 메모도 보여 주기
          </label>
          <ErrorNotice message={PRIVACY_WARNING} />
        </>
      )}
    </div>
  );
}
