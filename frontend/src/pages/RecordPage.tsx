import { ChevronLeft, LocateFixed, Pause, PawPrint, Play, Satellite, Square, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import GuestNotice from '../components/GuestNotice';
import PhotoPicker, { type PendingPhoto } from '../components/PhotoPicker';
import { Button, Card, Chip, ErrorNotice, InfoNotice, SectionTitle } from '../components/ui';
import WalkDetailsForm, { type WalkDetailsValue } from '../components/WalkDetailsForm';
import WalkRouteMap from '../components/WalkRouteMap';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import { clockLabel, dateLabel, distanceLabel, durationLabel, speedLabel } from '../lib/format';
import { GPS_MESSAGES, useGeolocation, useWakeLock, type WalkPosition } from '../lib/location';
import { uploadPhotos } from '../lib/photos';
import type { LatLng } from '../lib/navigation';
import {
  addFix,
  clearDraft,
  elapsedMs,
  loadDraft,
  MAX_RECORD_ACCURACY_M,
  newClientId,
  pauseRecording,
  recordingSegments,
  recoverRecording,
  resumeRecording,
  saveDraft,
  startRecording,
  stopRecording,
  toWalkPoints,
  type LocationFix,
  type Recording,
} from '../lib/recording';

const toFix = (position: WalkPosition, t: number): LocationFix => ({
  lat: position.point[0],
  lng: position.point[1],
  altitude: position.altitude ?? null,
  accuracy: position.accuracy,
  t,
});

export default function RecordPage() {
  const navigate = useNavigate();
  const [recording, setRecording] = useState<Recording | null>(() => {
    const draft = loadDraft();
    return draft ? recoverRecording(draft) : null;
  });
  const [restored] = useState(recording !== null);
  const [storageFailed, setStorageFailed] = useState(false);
  const [follow, setFollow] = useState(true);
  const [now, setNow] = useState(() => Date.now());
  const status = recording?.status ?? null;
  const gps = useGeolocation(status !== 'stopped');
  const position = gps.position;

  useWakeLock(status === 'recording');

  useEffect(() => {
    if (!position) return;
    setRecording((current) => (current ? addFix(current, toFix(position, position.timestamp ?? Date.now())).recording : current));
  }, [position]);

  // 좌표마다 기기에 남겨 새로고침이나 앱 중단에도 기록이 사라지지 않게 한다.
  useEffect(() => {
    if (recording) setStorageFailed(!saveDraft(recording));
  }, [recording]);

  useEffect(() => {
    if (status !== 'recording') return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [status]);

  const segments = useMemo<LatLng[][]>(() => (recording ? recordingSegments(recording) : []), [recording]);

  const start = () => {
    const time = Date.now();
    const started = startRecording(newClientId(), time);
    // 가만히 서 있으면 위치 갱신이 늦을 수 있으니 지금 위치를 첫 지점으로 넣는다.
    setRecording(position ? addFix(started, toFix(position, time)).recording : started);
    setFollow(true);
  };

  const pause = () => setRecording((current) => (current ? pauseRecording(current, Date.now()) : current));

  const resume = () => {
    const time = Date.now();
    setRecording((current) => {
      if (!current) return current;
      const resumed = resumeRecording(current, time);
      return position ? addFix(resumed, toFix(position, time)).recording : resumed;
    });
    setFollow(true);
  };

  const stop = () => setRecording((current) => (current ? stopRecording(current, Date.now()) : current));

  const discard = () => {
    if (!window.confirm('기록을 버릴까요? 되돌릴 수 없어요.')) return;
    clearDraft();
    setRecording(null);
  };

  const leave = () => {
    if (status === 'recording' && !window.confirm('기록을 멈추고 나갈까요? 다시 들어오면 이어서 기록할 수 있어요.')) return;
    navigate('/my-walks');
  };

  if (recording?.status === 'stopped') {
    return <SaveStep recording={recording} segments={segments} onResume={resume} onDiscard={discard} />;
  }

  const gpsMessage = GPS_MESSAGES[gps.status];
  const weakSignal = position?.accuracy != null && position.accuracy > MAX_RECORD_ACCURACY_M;
  const elapsed = recording ? elapsedMs(recording, now) : 0;
  const activeSeconds = elapsed / 1000;

  return (
    <div className="flex h-dvh flex-col bg-cream">
      <header className="z-10 flex items-center gap-2 border-b border-line bg-cream px-2 py-1.5">
        <button type="button" onClick={leave} aria-label="나가기" className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-ink-soft">
          <ChevronLeft size={24} aria-hidden />
        </button>
        <h1 className="min-w-0 flex-1 truncate text-base font-bold">산책 기록</h1>
        {status === 'paused' && <Chip tone="carrot">일시정지</Chip>}
        {weakSignal ? (
          <Chip tone="carrot">
            <Satellite size={13} aria-hidden />
            신호 약함
          </Chip>
        ) : position ? (
          <Chip tone="leaf">
            <Satellite size={13} aria-hidden />
            GPS ±{Math.round(position.accuracy ?? 0)}m
          </Chip>
        ) : null}
      </header>

      <div className="relative min-h-0 flex-1">
        <WalkRouteMap segments={segments} position={position?.point ?? null} accuracy={position?.accuracy ?? null} follow={follow} showEnd={false} onUserPan={() => setFollow(false)} />
        {!follow && (
          <button
            type="button"
            onClick={() => setFollow(true)}
            className="absolute right-3 bottom-3 z-10 flex min-h-11 items-center gap-1.5 rounded-full bg-white px-4 text-sm font-bold text-ink shadow-md"
          >
            <LocateFixed size={16} aria-hidden />
            내 위치로
          </button>
        )}
      </div>

      <div className="z-10 flex flex-col gap-3 rounded-t-3xl border-t border-line bg-white p-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
        {gpsMessage && <ErrorNotice message={gpsMessage} />}
        {restored && recording && status === 'paused' && (
          <InfoNotice>저장하지 않은 기록을 불러왔어요. 화면을 닫은 동안의 이동은 기록되지 않았어요.</InfoNotice>
        )}
        {storageFailed && <ErrorNotice message="기기 저장 공간이 부족해 임시 저장을 못 했어요. 새로고침하면 기록이 사라질 수 있으니 먼저 저장해 주세요." />}
        {recording && recording.gaps > 0 && <InfoNotice>위치가 끊긴 {recording.gaps}곳은 거리에 넣지 않았어요.</InfoNotice>}

        {recording ? (
          <dl className="grid grid-cols-3 text-center" data-testid="record-stats">
            <Stat label="거리" value={distanceLabel(recording.distance)} testId="record-distance" />
            <Stat label="시간" value={clockLabel(elapsed)} testId="record-time" />
            <Stat label="평균 속도" value={speedLabel(activeSeconds > 0 ? recording.distance / activeSeconds : null)} />
          </dl>
        ) : (
          <p className="text-xs leading-relaxed text-ink-soft">
            화면을 끄거나 다른 앱으로 이동하면 브라우저가 위치 기록을 멈출 수 있어요. 화면을 켠 채로 걸어 주세요. 기록은 이 기기에 계속 임시 저장돼요.
          </p>
        )}

        {status === null && (
          <Button onClick={start} disabled={gps.status !== 'active'} className="w-full">
            <Play size={18} aria-hidden />
            {gps.status === 'requesting' ? '현재 위치를 찾는 중이에요' : '산책 시작'}
          </Button>
        )}
        {status === 'recording' && (
          <div className="grid grid-cols-2 gap-2">
            <Button variant="ghost" onClick={pause}>
              <Pause size={18} aria-hidden />
              일시정지
            </Button>
            <Button variant="accent" onClick={stop}>
              <Square size={16} aria-hidden />
              산책 종료
            </Button>
          </div>
        )}
        {status === 'paused' && (
          <>
            <div className="grid grid-cols-2 gap-2">
              <Button onClick={resume}>
                <Play size={18} aria-hidden />
                다시 시작
              </Button>
              <Button variant="accent" onClick={stop}>
                <Square size={16} aria-hidden />
                산책 종료
              </Button>
            </div>
            <button type="button" onClick={discard} className="min-h-10 text-sm font-semibold text-ink-soft">
              기록 버리기
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value, testId }: { label: string; value: string; testId?: string }) {
  return (
    <div>
      <dt className="text-xs text-ink-muted">{label}</dt>
      <dd className="mt-0.5 text-lg font-bold text-ink" data-testid={testId}>
        {value}
      </dd>
    </div>
  );
}

function SaveStep({ recording, segments, onResume, onDiscard }: { recording: Recording; segments: LatLng[][]; onResume: () => void; onDiscard: () => void }) {
  const navigate = useNavigate();
  const { selectedPet } = useApp();
  const [details, setDetails] = useState<WalkDetailsValue>({
    title: `${dateLabel(new Date(recording.startedAt))} 산책`,
    petId: selectedPet?.id ?? null,
    memo: '',
    visibility: 'private',
    shareMemo: false,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [photos, setPhotos] = useState<PendingPhoto[]>([]);

  const seconds = Math.round(recording.activeMs / 1000);
  const canSave = recording.points.length >= 2;

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const walk = await api.createSavedWalk({
        title: details.title.trim(),
        pet_id: details.petId,
        memo: details.memo,
        visibility: details.visibility,
        share_memo: details.shareMemo,
        source_type: 'recorded',
        client_id: recording.id,
        duration_sec: seconds,
        points: toWalkPoints(recording),
      });
      clearDraft();
      const photoFailures = await uploadPhotos(walk.id, photos.map((photo) => photo.blob));
      navigate(`/my-walks/${walk.id}`, { replace: true, state: photoFailures ? { photoFailures } : null });
    } catch (saveError) {
      setError(`${(saveError as Error).message} 기록은 이 기기에 남아 있으니 다시 저장할 수 있어요.`);
      setSaving(false);
    }
  };

  return (
    <div className="mx-auto flex min-h-dvh max-w-2xl flex-col gap-4 bg-cream p-4">
      <h1 className="flex items-center gap-2 font-brand text-2xl text-leaf-800">
        <PawPrint size={22} className="text-carrot-500" aria-hidden />
        산책 저장
      </h1>
      <div className="h-56 overflow-hidden rounded-3xl border border-line">
        <WalkRouteMap segments={segments} />
      </div>
      <Card>
        <SectionTitle>{dateLabel(new Date(recording.startedAt))} 산책 결과</SectionTitle>
        <dl className="grid grid-cols-3 text-center" data-testid="save-summary">
          <Stat label="거리" value={distanceLabel(recording.distance)} />
          <Stat label="시간" value={durationLabel(seconds)} />
          <Stat label="평균 속도" value={speedLabel(seconds > 0 ? recording.distance / seconds : null)} />
        </dl>
      </Card>

      {canSave ? (
        <Card>
          <WalkDetailsForm value={details} onChange={setDetails} />
          <div className="mt-4">
            <PhotoPicker photos={photos} onChange={setPhotos} />
          </div>
          <div className="mt-4">
            <GuestNotice />
          </div>
          {error && (
            <div className="mt-4">
              <ErrorNotice message={error} />
            </div>
          )}
          <Button onClick={save} disabled={saving || !details.title.trim()} className="mt-4 w-full">
            {saving ? '저장 중이에요' : '저장하기'}
          </Button>
        </Card>
      ) : (
        <ErrorNotice message="이동이 기록되지 않아 저장할 수 없어요. 조금 더 걸은 뒤 종료해 주세요." />
      )}

      <div className="grid grid-cols-2 gap-2">
        <Button variant="ghost" onClick={onResume}>
          <Play size={18} aria-hidden />
          이어서 기록
        </Button>
        <Button variant="ghost" onClick={onDiscard}>
          <Trash2 size={16} aria-hidden />
          기록 버리기
        </Button>
      </div>
    </div>
  );
}
