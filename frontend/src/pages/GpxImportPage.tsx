import { CheckCircle2, FileUp } from 'lucide-react';
import { useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import GuestNotice from '../components/GuestNotice';
import PhotoPicker, { type PendingPhoto } from '../components/PhotoPicker';
import { Button, Card, ErrorNotice, InfoNotice, PageTitle, SectionTitle } from '../components/ui';
import WalkDetailsForm, { type WalkDetailsValue } from '../components/WalkDetailsForm';
import WalkRouteMap from '../components/WalkRouteMap';
import { useApp } from '../context/AppContext';
import { api, MAX_GPX_BYTES } from '../lib/api';
import { distanceLabel, durationLabel, speedLabel } from '../lib/format';
import type { LatLng } from '../lib/navigation';
import { uploadPhotos } from '../lib/photos';
import { newClientId } from '../lib/recording';
import type { GpxPreview } from '../lib/types';

export default function GpxImportPage() {
  const navigate = useNavigate();
  const { selectedPet } = useApp();
  const inputRef = useRef<HTMLInputElement>(null);
  const clientId = useRef(newClientId());
  const [preview, setPreview] = useState<GpxPreview | null>(null);
  const [details, setDetails] = useState<WalkDetailsValue | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [photos, setPhotos] = useState<PendingPhoto[]>([]);

  const segments = useMemo(() => {
    const grouped = new Map<number, LatLng[]>();
    for (const point of preview?.points ?? []) {
      if (!grouped.has(point.segment)) grouped.set(point.segment, []);
      grouped.get(point.segment)!.push([point.latitude, point.longitude]);
    }
    return [...grouped.values()];
  }, [preview]);

  const check = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    setPreview(null);
    setDetails(null);
    if (!file.name.toLowerCase().endsWith('.gpx')) {
      setError('.gpx 파일만 가져올 수 있어요.');
      return;
    }
    if (file.size > MAX_GPX_BYTES) {
      setError(`파일이 너무 커요. ${MAX_GPX_BYTES / (1024 * 1024)}MB까지 가져올 수 있어요.`);
      return;
    }
    setProgress(0);
    try {
      const result = await api.previewGpx(file, setProgress);
      clientId.current = newClientId();
      setPreview(result);
      setDetails({
        title: (result.name ?? file.name.replace(/\.gpx$/i, '')).slice(0, 80),
        petId: selectedPet?.id ?? null,
        memo: '',
        visibility: 'private',
        shareMemo: false,
      });
    } catch (checkError) {
      setError((checkError as Error).message);
    } finally {
      setProgress(null);
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  const save = async () => {
    if (!preview || !details) return;
    setSaving(true);
    setError(null);
    try {
      const walk = await api.createSavedWalk({
        title: details.title.trim(),
        pet_id: details.petId,
        memo: details.memo,
        visibility: details.visibility,
        share_memo: details.shareMemo,
        source_type: 'imported',
        client_id: clientId.current,
        points: preview.points.map((point) => ({
          latitude: point.latitude,
          longitude: point.longitude,
          altitude: point.altitude,
          accuracy: null,
          recorded_at: point.recorded_at,
          segment: point.segment,
        })),
      });
      const photoFailures = await uploadPhotos(walk.id, photos.map((photo) => photo.blob));
      navigate(`/my-walks/${walk.id}`, { replace: true, state: photoFailures ? { photoFailures } : null });
    } catch (saveError) {
      setError((saveError as Error).message);
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <PageTitle sub="다른 앱에서 내려받은 GPX 파일을 내 산책길로 저장해요.">GPX 가져오기</PageTitle>

      <label
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          void check(event.dataTransfer.files[0]);
        }}
        className={`flex min-h-36 cursor-pointer flex-col items-center justify-center gap-2 rounded-3xl border-2 border-dashed p-6 text-center transition ${
          dragging ? 'border-leaf-500 bg-leaf-50' : 'border-line bg-white'
        }`}
        data-testid="gpx-dropzone"
      >
        <FileUp size={28} className="text-leaf-500" aria-hidden />
        <span className="text-sm font-bold">{preview ? '다른 파일 선택' : 'GPX 파일 선택'}</span>
        <span className="text-xs text-ink-muted">여기로 끌어다 놓아도 돼요. {MAX_GPX_BYTES / (1024 * 1024)}MB, 10만 지점까지 가져올 수 있어요.</span>
        <input
          ref={inputRef}
          type="file"
          accept=".gpx,application/gpx+xml"
          aria-label="GPX 파일"
          className="sr-only"
          onChange={(event) => void check(event.target.files?.[0])}
        />
      </label>

      {progress !== null && (
        <div role="status" className="flex flex-col gap-1.5">
          <p className="text-sm font-semibold text-ink-soft">{progress < 100 ? `파일을 올리는 중이에요 ${progress}%` : '파일을 검증하는 중이에요'}</p>
          <div role="progressbar" aria-label="업로드 진행률" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100} className="h-2.5 overflow-hidden rounded-full bg-leaf-100">
            <div className="h-full rounded-full bg-leaf-500 transition-[width]" style={{ width: `${progress}%` }} />
          </div>
        </div>
      )}
      {error && <ErrorNotice message={error} />}

      {preview && details && (
        <>
          <Card>
            <SectionTitle>
              <span className="flex items-center gap-1.5">
                <CheckCircle2 size={18} className="text-leaf-500" aria-hidden />
                파일 검증 결과
              </span>
            </SectionTitle>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm" data-testid="gpx-result">
              <Row label="GPX 버전" value={preview.version} />
              <Row label="트랙 / 구간" value={`${preview.track_count}개 / ${preview.segment_count}개`} />
              <Row label="지점" value={`${preview.point_count.toLocaleString()}개`} />
              <Row label="거리" value={distanceLabel(preview.distance_m)} />
              <Row label="시간" value={durationLabel(preview.duration_sec)} />
              <Row label="평균 속도" value={speedLabel(preview.average_speed_mps)} />
            </dl>
            {preview.warnings.length > 0 && (
              <ul className="mt-3 flex flex-col gap-2" aria-label="확인할 내용">
                {preview.warnings.map((warning) => (
                  <li key={warning}>
                    <InfoNotice>{warning}</InfoNotice>
                  </li>
                ))}
              </ul>
            )}
            {preview.duplicate_of && (
              <div className="mt-3" data-testid="gpx-duplicate">
                <ErrorNotice message={`같은 경로가 이미 저장되어 있어요: ${preview.duplicate_of.title}. 그래도 저장하면 따로 하나 더 생겨요.`} />
                <Link to={`/my-walks/${preview.duplicate_of.id}`} className="mt-1 inline-block min-h-8 text-sm font-semibold text-leaf-800 underline">
                  저장된 산책길 보기
                </Link>
              </div>
            )}
          </Card>

          <div className="h-64 overflow-hidden rounded-3xl border border-line">
            <WalkRouteMap segments={segments} />
          </div>

          <Card>
            <WalkDetailsForm value={details} onChange={setDetails} />
            <div className="mt-4">
              <PhotoPicker photos={photos} onChange={setPhotos} />
            </div>
            <div className="mt-4">
              <GuestNotice />
            </div>
            <Button onClick={save} disabled={saving || !details.title.trim()} className="mt-4 w-full">
              {saving ? '저장 중이에요' : '산책길로 저장'}
            </Button>
          </Card>
        </>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="text-ink-muted">{label}</dt>
      <dd className="font-semibold">{value}</dd>
    </div>
  );
}
