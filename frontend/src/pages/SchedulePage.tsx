import { Plus, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Card, ChoiceGroup, ErrorNotice, Loading, PageTitle } from '../components/ui';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import { windowLabel } from '../lib/format';
import { SCHEDULE_PRESETS } from '../lib/labels';
import type { TimeWindow } from '../lib/types';

const SELECT_CLASS = 'min-h-12 flex-1 rounded-2xl border border-line bg-white px-3 text-base';
const hasWindow = (windows: TimeWindow[], target: TimeWindow) =>
  windows.some((window) => window.start_hour === target.start_hour && window.end_hour === target.end_hour);

export default function SchedulePage() {
  const { schedule, setSchedule, invalidateRecommendations } = useApp();
  const navigate = useNavigate();
  const [windows, setWindows] = useState<TimeWindow[]>([]);
  const [duration, setDuration] = useState(40);
  const [walks, setWalks] = useState(1);
  const [customStart, setCustomStart] = useState(16);
  const [customEnd, setCustomEnd] = useState(20);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!schedule) return;
    setWindows(schedule.available_windows);
    setDuration(schedule.preferred_duration_min);
    setWalks(schedule.walks_per_day);
  }, [schedule]);

  if (!schedule) return <Loading />;

  const toggle = (target: TimeWindow) =>
    setWindows((previous) =>
      hasWindow(previous, target)
        ? previous.filter((window) => !(window.start_hour === target.start_hour && window.end_hour === target.end_hour))
        : [...previous, target],
    );

  const addCustom = () => {
    if (customEnd <= customStart) {
      setError('끝나는 시각은 시작 시각보다 늦어야 해요.');
      return;
    }
    setError(null);
    const target = { start_hour: customStart, end_hour: customEnd };
    if (!hasWindow(windows, target)) setWindows((previous) => [...previous, target]);
  };

  const onSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const saved = await api.updateSchedule({
        available_windows: windows,
        preferred_duration_min: duration,
        walks_per_day: walks,
      });
      setSchedule(saved);
      invalidateRecommendations();
      navigate('/');
    } catch (saveError) {
      setError((saveError as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <PageTitle sub="이 시간 안에서만 산책을 추천해요.">산책 가능 시간</PageTitle>

      <Card className="flex flex-col gap-4">
        <div>
          <p className="mb-1.5 text-sm font-semibold">시간대 선택</p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {SCHEDULE_PRESETS.map((preset) => {
              const target = { start_hour: preset.start_hour, end_hour: preset.end_hour };
              const selected = hasWindow(windows, target);
              return (
                <button
                  key={preset.key}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => toggle(target)}
                  className={`min-h-14 rounded-2xl border text-sm font-bold ${
                    selected ? 'border-leaf-500 bg-leaf-500 text-white' : 'border-line bg-white text-ink-soft'
                  }`}
                >
                  {preset.label}
                  <span className="block text-xs font-medium opacity-80">
                    {preset.start_hour}~{preset.end_hour}시
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        <div>
          <p className="mb-1.5 text-sm font-semibold">직접 시간 입력</p>
          <div className="flex items-center gap-2">
            <select aria-label="시작 시각" className={SELECT_CLASS} value={customStart} onChange={(e) => setCustomStart(Number(e.target.value))}>
              {Array.from({ length: 24 }, (_, hour) => (
                <option key={hour} value={hour}>{hour}시</option>
              ))}
            </select>
            <span className="text-ink-muted">~</span>
            <select aria-label="끝나는 시각" className={SELECT_CLASS} value={customEnd} onChange={(e) => setCustomEnd(Number(e.target.value))}>
              {Array.from({ length: 24 }, (_, index) => index + 1).map((hour) => (
                <option key={hour} value={hour}>{hour}시</option>
              ))}
            </select>
            <button
              type="button"
              onClick={addCustom}
              aria-label="직접 입력한 시간 추가"
              className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-carrot-500 text-white"
            >
              <Plus size={20} aria-hidden />
            </button>
          </div>
        </div>

        <div>
          <p className="mb-1.5 text-sm font-semibold">선택한 시간</p>
          {windows.length === 0 ? (
            <p className="text-sm text-carrot-700">시간을 하나 이상 골라 주세요.</p>
          ) : (
            <ul className="flex flex-wrap gap-1.5">
              {windows.map((window) => (
                <li key={`${window.start_hour}-${window.end_hour}`}>
                  <button
                    type="button"
                    onClick={() => toggle(window)}
                    aria-label={`${windowLabel(window.start_hour, window.end_hour)} 삭제`}
                    className="flex min-h-9 items-center gap-1 rounded-full bg-leaf-50 px-3 text-sm font-semibold text-leaf-800"
                  >
                    {windowLabel(window.start_hour, window.end_hour)}
                    <X size={14} aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>

      <Card className="flex flex-col gap-5">
        <label className="text-sm font-semibold">
          한 번에 걸을 수 있는 시간: <span className="text-leaf-600">{duration}분</span>
          <input
            type="range"
            min={10}
            max={120}
            step={5}
            value={duration}
            onChange={(e) => setDuration(Number(e.target.value))}
            className="mt-2 w-full accent-[var(--color-leaf-500)]"
          />
        </label>
        <ChoiceGroup
          label="하루 희망 횟수"
          value={walks}
          options={[1, 2, 3].map((count) => ({ value: count, label: `${count}번` }))}
          onChange={setWalks}
        />
      </Card>

      {error && <ErrorNotice message={error} />}
      <Button onClick={onSave} disabled={saving || windows.length === 0}>
        {saving ? '저장 중이에요' : '저장하기'}
      </Button>
    </div>
  );
}
