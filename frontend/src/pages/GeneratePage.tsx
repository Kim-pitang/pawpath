import { LocateFixed, Sparkles } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import GuestNotice from '../components/GuestNotice';
import { Button, Card, ErrorNotice, InfoNotice, PageTitle, SectionTitle } from '../components/ui';
import WalkDetailsForm, { PRIVACY_WARNING, type WalkDetailsValue } from '../components/WalkDetailsForm';
import WalkRouteMap from '../components/WalkRouteMap';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import { distanceLabel } from '../lib/format';
import { GPS_MESSAGES, useGeolocation } from '../lib/location';
import type { LatLng } from '../lib/navigation';
import { newClientId } from '../lib/recording';
import type { GenerateRouteResult } from '../lib/types';

const LEVEL_TEXT: Record<string, string> = { good: '안전 양호', caution: '주의 필요', danger: '위험 요소 있음', blocked: '권하지 않음' };

const MIN_MINUTES = 20;
const MAX_MINUTES = 90;
const DEFAULT_MINUTES = 30;

/** 목표 시간과 후보 시간의 차이를 문장으로. 5분 미만 차이는 목표와 같다고 본다. */
function timeGap(duration: number, target: number): string {
  const gap = Math.round(duration - target);
  if (Math.abs(gap) < 5) return '목표 시간과 비슷해요';
  return gap > 0 ? `목표보다 약 ${gap}분 길어요` : `목표보다 약 ${-gap}분 짧아요`;
}

const clampMinutes = (value: number) => Math.min(MAX_MINUTES, Math.max(MIN_MINUTES, Math.round(value / 5) * 5));

export default function GeneratePage() {
  const navigate = useNavigate();
  const { schedule, selectedPet } = useApp();
  const clientId = useRef(newClientId());
  const [useGps, setUseGps] = useState(false);
  const gps = useGeolocation(useGps);
  // GPS는 첫 위치만 출발점으로 쓰고 감시를 끈다. 계속 따라가면 좌표가 흔들릴 때마다 만든 경로가 사라진다.
  const [gpsOrigin, setGpsOrigin] = useState<{ point: LatLng; accuracy: number | null } | null>(null);
  // 응답을 기다리는 사이 출발점이 바뀌면 늦게 온 응답을 버리려고, 요청마다 번호를 매긴다.
  const requestId = useRef(0);
  const [picked, setPicked] = useState<LatLng | null>(null);
  const [chosenMinutes, setChosenMinutes] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<GenerateRouteResult | null>(null);
  const [selected, setSelected] = useState(0);
  const [details, setDetails] = useState<WalkDetailsValue | null>(null);
  const [saving, setSaving] = useState(false);

  const minutes = chosenMinutes ?? clampMinutes(schedule?.preferred_duration_min ?? DEFAULT_MINUTES);
  const origin: LatLng | null = picked ?? gpsOrigin?.point ?? null;
  const candidate = result?.candidates[selected] ?? null;
  const segments = useMemo<LatLng[][]>(() => (candidate ? [candidate.route] : []), [candidate]);
  const gpsMessage = useGps && picked === null ? GPS_MESSAGES[gps.status] : undefined;

  useEffect(() => {
    if (useGps && gps.position) {
      setGpsOrigin({ point: gps.position.point, accuracy: gps.position.accuracy });
      setUseGps(false);
    }
  }, [useGps, gps.position]);

  // 출발점이 바뀌면 이전 결과는 다른 곳의 경로라서 지운다.
  useEffect(() => {
    requestId.current += 1;
    setLoading(false);
    setResult(null);
    setDetails(null);
    setError(null);
  }, [origin?.[0], origin?.[1]]);

  const generate = async () => {
    if (!origin || loading) return;
    const mine = ++requestId.current;
    setLoading(true);
    setError(null);
    setResult(null);
    setDetails(null);
    try {
      const next = await api.generateRoute(origin[0], origin[1], minutes, selectedPet?.id ?? null);
      if (mine !== requestId.current) return;
      clientId.current = newClientId();
      setResult(next);
      setSelected(0);
      if (next.candidates[0]) {
        setDetails({ title: `${minutes}분 순환 산책길`, petId: selectedPet?.id ?? null, memo: '', visibility: 'private', shareMemo: false });
      }
    } catch (generateError) {
      if (mine === requestId.current) setError((generateError as Error).message);
    } finally {
      if (mine === requestId.current) setLoading(false);
    }
  };

  const save = async () => {
    if (!candidate || !details) return;
    setSaving(true);
    setError(null);
    try {
      const walk = await api.createSavedWalk({
        title: details.title.trim(),
        pet_id: details.petId,
        memo: details.memo,
        visibility: details.visibility,
        share_memo: details.shareMemo,
        source_type: 'generated',
        client_id: clientId.current,
        points: candidate.route.map(([latitude, longitude]) => ({ latitude, longitude, altitude: null, accuracy: null, recorded_at: null, segment: 0 })),
      });
      navigate(`/my-walks/${walk.id}`, { replace: true });
    } catch (saveError) {
      setError((saveError as Error).message);
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <PageTitle sub="출발 위치와 산책 시간을 정하면 도보 길찾기로 한 바퀴 도는 경로를 만들어요.">산책길 만들기</PageTitle>

      <Card className="flex flex-col gap-4">
        <div>
          <SectionTitle>출발 위치</SectionTitle>
          <p className="text-sm text-ink-soft">{origin ? (picked ? '지도에서 고른 위치예요.' : `현재 위치예요.${gpsOrigin?.accuracy != null ? ` 정확도 약 ${Math.round(gpsOrigin.accuracy)}m` : ''}`) : '현재 위치를 쓰거나 지도를 눌러 고르세요.'}</p>
          <Button
            variant="ghost"
            className="mt-2 w-full"
            onClick={() => {
              setPicked(null);
              setGpsOrigin(null);
              setUseGps(true);
            }}
          >
            <LocateFixed size={18} aria-hidden />
            현재 위치 사용
          </Button>
          {gpsMessage && (
            <div className="mt-2">
              <ErrorNotice message={gpsMessage} />
            </div>
          )}
        </div>
        <div className="h-64 overflow-hidden rounded-3xl border border-line">
          <WalkRouteMap segments={segments} position={origin} showEnd={false} onMapClick={(point) => setPicked(point)} centerOnPosition />
        </div>
        <label className="text-sm font-semibold">
          산책 시간 {minutes}분
          <input
            type="range"
            min={MIN_MINUTES}
            max={MAX_MINUTES}
            step={5}
            value={minutes}
            onChange={(event) => setChosenMinutes(Number(event.target.value))}
            className="mt-2 w-full accent-leaf-600"
            data-testid="generate-minutes"
          />
          <span className="text-xs font-normal text-ink-muted">
            {schedule ? `일정에 적은 희망 시간(${schedule.preferred_duration_min}분)으로 시작해요. ` : ''}걷는 속도 3.6km/h 기준이에요.
          </span>
        </label>
        <Button onClick={generate} disabled={!origin || loading} className="w-full" data-testid="generate-button">
          <Sparkles size={18} aria-hidden />
          {loading ? '경로를 만드는 중이에요' : '경로 만들기'}
        </Button>
        {loading && (
          <p role="status" className="text-sm font-semibold text-ink-soft">
            8방향의 경로를 만들어 비교하고 있어요. 보통 10초쯤, 후보가 모자라면 더 걸려요.
          </p>
        )}
      </Card>

      {error && <ErrorNotice message={error} />}
      {result && result.candidates.length === 0 && result.notice && <InfoNotice>{result.notice}</InfoNotice>}
      {result && result.fit_notice && <InfoNotice>{result.fit_notice}</InfoNotice>}

      {result && candidate && details && (
        <>
          <Card>
            <SectionTitle>만든 경로 {result.candidates.length}개</SectionTitle>
            {result.scored_for && <p className="mb-2 text-xs text-ink-soft">{result.scored_for}에게 맞는 순서로 보여 드려요. 점수는 성향, 날씨, 일정, 주변 환경(OSM 기록)으로 계산해요.</p>}
            <div className="flex flex-col gap-2" role="group" aria-label="경로 후보">
              {result.candidates.map((item, index) => (
                <button
                  key={index}
                  type="button"
                  aria-pressed={index === selected}
                  onClick={() => {
                    // 다른 후보를 고르면 저장 요청의 식별자도 새로 만들어, 앞서 저장 응답을 놓친 후보가 대신 저장되지 않게 한다.
                    if (index !== selected) clientId.current = newClientId();
                    setSelected(index);
                  }}
                  className={`min-h-12 rounded-2xl border px-4 py-2 text-left text-sm ${index === selected ? 'border-leaf-600 bg-leaf-50 font-bold' : 'border-line bg-white'}`}
                  data-testid="generate-candidate"
                >
                  후보 {index + 1} · 약 {Math.round(item.duration_min)}분 · {distanceLabel(item.distance_m)}
                  {item.fit?.score != null && <span className="ml-1 font-bold text-leaf-800">· 맞춤 {Math.round(item.fit.score)}점</span>}
                  <span className="block text-xs font-normal text-ink-soft">
                    {timeGap(item.duration_min, result.target_min)} · 같은 길을 다시 지나는 구간 약 {Math.round(item.repeated_pct)}%
                  </span>
                  {item.fit && item.fit.highlights.length > 0 && (
                    <span className="block text-xs font-normal text-ink-soft">{item.fit.highlights.slice(0, 2).join(' · ')}</span>
                  )}
                  {item.start_snap_m > 30 && (
                    <span className="block text-xs font-normal text-ink-soft">
                      출발 위치에서 약 {Math.round(item.start_snap_m)}m 떨어진 가까운 길에서 시작해요. 그곳까지 먼저 걸어가 주세요.
                    </span>
                  )}
                </button>
              ))}
            </div>
            {candidate.fit && (candidate.fit.summary || candidate.fit.excluded.length > 0) && (
              <div className="mt-3 rounded-2xl border border-line bg-white p-3 text-sm" data-testid="generate-fit">
                <p className="font-semibold">
                  {candidate.fit.summary}
                  {candidate.fit.level && <span className="ml-1 text-xs font-normal text-ink-soft">({LEVEL_TEXT[candidate.fit.level]}{candidate.fit.start_label ? `, 추천 출발 ${candidate.fit.start_label}` : ''})</span>}
                </p>
                {candidate.fit.excluded.length > 0 && <p className="mt-1 text-xs text-ink-soft">이 시간대에는 권하지 않아요: {candidate.fit.excluded.join(' / ')}</p>}
                {candidate.fit.highlights.length > 0 && (
                  <ul className="mt-2 list-disc pl-5 text-xs text-ink-soft">
                    {candidate.fit.highlights.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                )}
                {candidate.fit.cautions.length > 0 && (
                  <ul className="mt-2 list-disc pl-5 text-xs text-carrot-700">
                    {candidate.fit.cautions.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                )}
                {candidate.fit.unknown.length > 0 && <p className="mt-2 text-xs text-ink-muted">측정하지 못해 확인 불가로 본 항목이 있어요. 현장에서 확인해 주세요.</p>}
              </div>
            )}
            <div className="mt-3">
              <InfoNotice>
                도보 길찾기로 자동 만든 경로예요. 경사와 반려견 출입 여부는 확인하지 않았고, 도로·조명·나무·공원은 OpenStreetMap 기록 기준이에요. 실제로 걸으며 확인해 주세요. 경로를 만들 때 출발 위치가 길찾기 서버(OpenStreetMap 기반 공용 서버)로 전송돼요.
              </InfoNotice>
            </div>
          </Card>

          <Card>
            <WalkDetailsForm value={details} onChange={setDetails} />
            <div className="mt-3">
              <InfoNotice>{PRIVACY_WARNING}</InfoNotice>
            </div>
            <div className="mt-4">
              <GuestNotice />
            </div>
            <Button onClick={save} disabled={saving || !details.title.trim()} className="mt-4 w-full" data-testid="generate-save">
              {saving ? '저장 중이에요' : '내 산책길로 저장'}
            </Button>
            <p className="mt-2 text-xs text-ink-muted">저장하면 바로 내 추천 후보 코스가 되고, 산책길 화면에서 뺄 수 있어요.</p>
          </Card>
        </>
      )}
    </div>
  );
}
