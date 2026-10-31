import { AlertOctagon, AlertTriangle, ChevronDown, HelpCircle, ShieldCheck } from 'lucide-react';
import { useState } from 'react';
import type { SafetyAssessment, SafetyItem } from '../lib/types';

const LEVELS = {
  good: { label: '양호', icon: ShieldCheck, tone: 'bg-leaf-50 text-leaf-800' },
  caution: { label: '주의', icon: AlertTriangle, tone: 'bg-[#fffbeb] text-[#92400e]' },
  danger: { label: '위험', icon: AlertOctagon, tone: 'bg-[#ffedea] text-[#831c1e]' },
  blocked: { label: '추천 제외', icon: AlertOctagon, tone: 'bg-[#ffedea] text-[#831c1e]' },
};

const STATUS_ICON = { ok: ShieldCheck, caution: AlertTriangle, danger: AlertOctagon, unverified: HelpCircle };
const STATUS_TEXT = { ok: '양호', caution: '주의', danger: '위험', unverified: '확인 불가' };
const STATUS_COLOR = { ok: 'text-mango-700', caution: 'text-[#92400e]', danger: 'text-[#b42318]', unverified: 'text-ink-muted' };
const SOURCE_TEXT: Record<SafetyItem['source'], string> = {
  forecast: '예보',
  demo: '모의',
  observed: 'OSM 기록',
  estimated: '팀 추정',
  unknown: '데이터 없음',
  unavailable: '날씨 확인 불가',
};

const percent = (value: number) => `${Math.round(value * 100)}%`;

/** 점수에 들어간 항목이 어디서 온 값인지 한 줄로 보여 준다. */
function DataQualityLine({ assessment }: { assessment: SafetyAssessment }) {
  const quality = assessment.data_quality;
  if (!quality) return null;
  const { shares } = quality;
  const parts = [`예보·실측 ${percent(shares.realtime + shares.observed)}`, `팀 추정 ${percent(shares.estimated)}`];
  if (shares.demo > 0) parts.push(`시연용 ${percent(shares.demo)}`);
  parts.push(`데이터 없음 ${percent(shares.missing)}`);
  return (
    <p className="mt-2 text-[11px] text-ink-muted" data-testid="safety-data-quality">
      안전 점수 근거: {parts.join(' · ')}
      {quality.environment_collected_on && ` · 코스 환경 기록 ${quality.environment_collected_on}`}
      {quality.insufficient && ' · 확인할 수 없는 항목이 많아 양호로 판단하지 않았어요'}
    </p>
  );
}

export function SafetyBadge({ assessment }: { assessment: SafetyAssessment }) {
  const level = LEVELS[assessment.level];
  const Icon = level.icon;
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-bold ${level.tone}`}>
      <Icon size={13} aria-hidden />
      안전 {Math.round(assessment.score)}점 · {level.label}
    </span>
  );
}

export default function SafetyPanel({ assessment }: { assessment: SafetyAssessment }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-line p-3" data-testid="safety-panel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SafetyBadge assessment={assessment} />
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          className="flex min-h-8 items-center gap-1 text-xs font-semibold text-ink-soft"
        >
          항목별 근거
          <ChevronDown size={15} className={`transition ${open ? 'rotate-180' : ''}`} aria-hidden />
        </button>
      </div>

      {assessment.warning && (
        <p role="alert" className="mt-2 flex items-start gap-1.5 rounded-xl bg-carrot-100 px-3 py-2 text-sm font-bold text-carrot-700" data-testid="safety-warning">
          <AlertOctagon size={16} className="mt-0.5 shrink-0" aria-hidden />
          <span>{assessment.warning}</span>
        </p>
      )}
      {assessment.risks.length > 0 && (
        <ul className="mt-2 flex flex-col gap-1 text-sm text-carrot-700" aria-label="위험 요인">
          {assessment.risks.map((risk) => (
            <li key={risk} className="flex items-start gap-1.5">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden />
              <span>{risk}</span>
            </li>
          ))}
        </ul>
      )}
      {assessment.unverified.length > 0 && (
        <p className="mt-2 flex items-start gap-1.5 text-xs text-ink-soft">
          <HelpCircle size={13} className="mt-0.5 shrink-0" aria-hidden />
          <span>확인 불가: {assessment.unverified.join(', ')}. 데이터가 없는 항목은 안전하다고 보지 않아요.</span>
        </p>
      )}
      <DataQualityLine assessment={assessment} />

      {open && (
        <div className="mt-3">
          <ul className="flex flex-col divide-y divide-line text-sm" aria-label="안전 평가 항목">
            {assessment.items.map((item) => {
              const Icon = STATUS_ICON[item.status];
              return (
                <li key={item.key} className="flex items-start gap-2 py-1.5">
                  <Icon size={15} className={`mt-0.5 shrink-0 ${STATUS_COLOR[item.status]}`} aria-hidden />
                  <div className="min-w-0 flex-1">
                    <p className="flex flex-wrap items-baseline justify-between gap-x-2">
                      <span className="font-semibold text-ink">
                        {item.label} <span className="font-normal text-ink-soft">{STATUS_TEXT[item.status]}</span>
                      </span>
                      <span className="text-[11px] text-ink-muted">{SOURCE_TEXT[item.source]}</span>
                    </p>
                    <p className="text-xs text-ink-soft">{item.value}</p>
                  </div>
                </li>
              );
            })}
          </ul>
          <p className="mt-2 text-xs text-ink-muted">{assessment.disclaimer}</p>
        </div>
      )}
    </div>
  );
}
