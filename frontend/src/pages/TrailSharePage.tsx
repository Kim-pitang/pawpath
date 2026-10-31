import { FileUp, Footprints, ImagePlus, Share2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import LoginPrompt from '../components/LoginPrompt';
import RouteThumbnail from '../components/RouteThumbnail';
import { Button, Card, ChoiceGroup, EmptyState, ErrorNotice, InfoNotice, LinkButton, Loading, PageTitle, SectionTitle } from '../components/ui';
import WalkRouteMap from '../components/WalkRouteMap';
import { PRIVACY_WARNING } from '../components/WalkDetailsForm';
import { useApp } from '../context/AppContext';
import { api } from '../lib/api';
import { dateTimeLabel, distanceLabel } from '../lib/format';
import { HIDE_RADIUS_OPTIONS, TRAIL_DIFFICULTY_LABELS, TRAIL_FEATURE_LABELS, TRAIL_SUITABLE_LABELS, TRAIL_VISIBILITY_LABELS, VISIBILITY_LABELS, WALK_SOURCE_LABELS } from '../lib/labels';
import type { LatLng } from '../lib/navigation';
import { prepareImage } from '../lib/photos';
import type { SavedWalkDetail, SavedWalkSummary, TrailDetail, TrailFeature, TrailInput, TrailPreview, TrailSuitable, TrailVisibility } from '../lib/types';

const INPUT_CLASS = 'mt-1.5 min-h-12 w-full rounded-2xl border border-line bg-white px-4 text-base font-normal outline-none focus:border-leaf-500';
const VISIBILITY_OPTIONS = (Object.keys(TRAIL_VISIBILITY_LABELS) as TrailVisibility[]).map((value) => ({ value, label: TRAIL_VISIBILITY_LABELS[value] }));
// 자동 생성 경로는 아직 아무도 걷지 않아 공유 대상에서 뺀다.
const SHAREABLE_SOURCES = ['recorded', 'imported'] as const;
type ShareableSource = (typeof SHAREABLE_SOURCES)[number];
const SOURCE_OPTIONS = SHAREABLE_SOURCES.map((value) => ({ value, label: WALK_SOURCE_LABELS[value] }));

/** 산책길 공유와 수정. 경로는 기존 기록을 그대로 쓰므로 고를 것과 쓸 것만 받는다. */
export default function TrailSharePage() {
  const { trailId } = useParams();
  const [params, setParams] = useSearchParams();
  const { account } = useApp();
  const editId = Number(trailId) || null;
  const walkId = Number(params.get('walk')) || null;

  if (!account) return <Loading />;
  if (!account.authenticated) {
    return (
      <div className="flex flex-col gap-4">
        <PageTitle>산책길 공유</PageTitle>
        <LoginPrompt title="로그인하면 산책길을 공유할 수 있어요">
          <p className="text-sm text-ink-soft">로그인하지 않고 저장한 산책길은 시연 보호자 것이라 공유할 수 없어요.</p>
        </LoginPrompt>
      </div>
    );
  }
  if (editId) return <TrailEditor key={`edit-${editId}`} editId={editId} walkId={null} />;
  if (walkId) return <TrailEditor key={`walk-${walkId}`} editId={null} walkId={walkId} />;
  return <WalkChooser onChoose={(id) => setParams({ walk: String(id) })} />;
}

function WalkChooser({ onChoose }: { onChoose: (id: number) => void }) {
  const [walks, setWalks] = useState<SavedWalkSummary[] | null>(null);
  const [source, setSource] = useState<ShareableSource>('recorded');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listSavedWalks({ sort: 'recent', petId: null, visibility: null }).then(setWalks).catch((loadError: Error) => setError(loadError.message));
  }, []);

  const available = walks?.filter((walk) => walk.community_trail === null && walk.source_type === source) ?? [];

  return (
    <div className="flex flex-col gap-4">
      <PageTitle sub="이미 저장한 산책길에서 고르면 경로를 다시 올릴 필요가 없어요.">산책길 공유</PageTitle>
      <ChoiceGroup label="어떤 산책길을 공유할까요?" value={source} options={SOURCE_OPTIONS} onChange={setSource} />
      {error && <ErrorNotice message={error} />}
      {!walks && !error && <Loading />}
      {walks && available.length === 0 && (
        <Card>
          <EmptyState title={source === 'recorded' ? '공유할 수 있는 기록이 없어요' : '공유할 수 있는 GPX 경로가 없어요'}>
            {source === 'recorded' ? (
              <LinkButton to="/record">
                <Footprints size={18} aria-hidden />
                산책 기록 시작
              </LinkButton>
            ) : (
              <LinkButton to="/my-walks/import">
                <FileUp size={18} aria-hidden />
                GPX 가져오기
              </LinkButton>
            )}
          </EmptyState>
        </Card>
      )}
      {available.length > 0 && (
        <ul className="flex flex-col gap-3" aria-label="공유할 산책길 목록">
          {available.map((walk) => (
            <li key={walk.id}>
              <button
                type="button"
                onClick={() => onChoose(walk.id)}
                className="flex w-full items-center gap-3 rounded-3xl border border-line bg-white p-3 text-left transition hover:bg-leaf-50"
                data-testid="shareable-walk"
              >
                <RouteThumbnail segments={walk.preview} label={`${walk.title} 경로`} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-bold">{walk.title}</span>
                  <span className="mt-0.5 block text-xs text-ink-soft">{dateTimeLabel(walk.started_at)}</span>
                  <span className="mt-1 block text-sm font-semibold">{distanceLabel(walk.distance_m)}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function TagPicker<T extends string>({ label, labels, value, onChange }: { label: string; labels: Record<T, string>; value: T[]; onChange: (value: T[]) => void }) {
  return (
    <fieldset>
      <legend className="mb-1.5 text-sm font-semibold">{label}</legend>
      <div className="flex flex-wrap gap-2">
        {(Object.keys(labels) as T[]).map((tag) => {
          const selected = value.includes(tag);
          return (
            <button
              key={tag}
              type="button"
              aria-pressed={selected}
              onClick={() => onChange(selected ? value.filter((item) => item !== tag) : [...value, tag])}
              className={`min-h-11 rounded-2xl border px-3 text-sm font-semibold transition ${selected ? 'border-leaf-500 bg-leaf-500 text-white' : 'border-line bg-white text-ink-soft hover:bg-leaf-50'}`}
            >
              {labels[tag]}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

function TrailEditor({ editId, walkId }: { editId: number | null; walkId: number | null }) {
  const navigate = useNavigate();
  const { account } = useApp();
  const [trail, setTrail] = useState<TrailDetail | null>(null);
  const [walk, setWalk] = useState<SavedWalkDetail | null>(null);
  const [form, setForm] = useState<TrailInput | null>(null);
  const [preview, setPreview] = useState<TrailPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    let active = true;
    (async () => {
      const existing = editId ? await api.getTrail(editId) : null;
      if (existing && !existing.owner) throw new Error('내가 공유한 산책길만 고칠 수 있어요.');
      const source = await api.getSavedWalk(existing?.owner?.saved_walk_id ?? (walkId as number));
      if (!active) return;
      setTrail(existing);
      setWalk(source);
      setForm(
        existing
          ? {
              title: existing.title,
              description: existing.description,
              cover_photo_id: existing.cover_photo_id,
              visibility: existing.visibility,
              region: existing.region,
              features: existing.features,
              suitable_for: existing.suitable_for,
              hide_radius_m: existing.owner!.hide_radius_m as TrailInput['hide_radius_m'],
            }
          : // 사진은 보호자가 직접 고른 것만 공개한다.
            { title: source.title, description: '', cover_photo_id: null, visibility: 'public', region: '', features: [], suitable_for: [], hide_radius_m: 200 },
      );
    })().catch((loadError: Error) => active && setError(loadError.message));
    return () => {
      active = false;
    };
  }, [editId, walkId]);

  const radius = form?.hide_radius_m;
  const sourceId = walk?.id;
  useEffect(() => {
    if (!sourceId || !radius) return;
    let active = true;
    setPreviewError(null);
    api
      .previewTrail(sourceId, radius)
      .then((result) => active && setPreview(result))
      .catch((failure: Error) => {
        if (!active) return;
        setPreview(null);
        setPreviewError(failure.message);
      });
    return () => {
      active = false;
    };
  }, [sourceId, radius]);

  const route = useMemo(() => (preview?.route ?? []) as LatLng[][], [preview?.route]);

  if (!walk || !form) return error ? <ErrorNotice message={error} /> : <Loading />;
  if (!editId && walk.community_trail) {
    return (
      <Card>
        <EmptyState title="이미 공유한 산책길이에요">
          <LinkButton to={`/community/trails/${walk.community_trail.id}`}>공유한 산책길 보기</LinkButton>
        </EmptyState>
      </Card>
    );
  }

  const update = <K extends keyof TrailInput>(key: K, value: TrailInput[K]) => setForm({ ...form, [key]: value });

  const addCover = async (files: FileList | null) => {
    const file = files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const photo = await api.uploadPhoto(walk.id, await prepareImage(file));
      setWalk(await api.getSavedWalk(walk.id));
      setForm((current) => current && { ...current, cover_photo_id: photo.id });
    } catch (uploadError) {
      setError((uploadError as Error).message);
    } finally {
      setUploading(false);
    }
  };

  const submit = async () => {
    setSaving(true);
    setError(null);
    const body = { ...form, title: form.title.trim(), description: form.description.trim(), region: form.region.trim() };
    try {
      const saved = trail ? await api.updateTrail(trail.id, body) : await api.createTrail({ ...body, saved_walk_id: walk.id });
      navigate(`/community/trails/${saved.id}`, { replace: true });
    } catch (saveError) {
      setError((saveError as Error).message);
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <PageTitle sub={trail ? undefined : `${walk.title}의 경로를 그대로 써요.`}>{trail ? '공유한 산책길 수정' : '산책길 공유'}</PageTitle>

      <section className="flex flex-col gap-2" aria-label="공개될 경로">
        <SectionTitle>공개될 경로</SectionTitle>
        <div className="h-64 overflow-hidden rounded-3xl border border-line md:h-80">
          <WalkRouteMap segments={route} />
        </div>
        {previewError && <ErrorNotice message={previewError} />}
        {preview && (
          <p className="text-sm text-ink-soft" data-testid="trail-preview-summary">
            {distanceLabel(preview.distance_m)} · 약 {preview.estimated_min}분 · {TRAIL_DIFFICULTY_LABELS[preview.difficulty]}
            {preview.hidden_m > 0 && ` · 앞뒤 약 ${distanceLabel(preview.hidden_m)}를 가렸어요`}
          </p>
        )}
        {preview && !preview.can_navigate && <InfoNotice>가린 구간이나 끊긴 구간 때문에 다른 보호자가 이 길로 길 안내를 받을 수는 없어요. 지도와 GPX로는 볼 수 있어요.</InfoNotice>}
        <ChoiceGroup label="출발점과 도착점 주변 가리기" value={form.hide_radius_m} options={HIDE_RADIUS_OPTIONS} onChange={(value) => update('hide_radius_m', value)} />
        <p className="text-xs text-ink-muted">{PRIVACY_WARNING} 지도에 보이는 선만 공개되고, 걸은 시각과 메모, 반려동물 정보는 공개되지 않아요.</p>
        {walk.visibility !== 'private' && (
          <ErrorNotice message={`이 산책길은 ${VISIBILITY_LABELS[walk.visibility]} 상태예요. 그쪽 주소로는 출발점과 도착점을 가리지 않은 경로가 열려요. 가리려면 원본 산책길의 공유를 해제해 주세요.`} />
        )}
      </section>

      <Card className="flex flex-col gap-4">
        <label className="text-sm font-semibold">
          산책길 제목
          <input className={INPUT_CLASS} value={form.title} maxLength={80} onChange={(event) => update('title', event.target.value)} />
        </label>
        <label className="text-sm font-semibold">
          산책길 설명
          <textarea
            className="mt-1.5 min-h-24 w-full rounded-2xl border border-line bg-white p-4 text-base font-normal outline-none focus:border-leaf-500"
            value={form.description}
            maxLength={2000}
            placeholder="어떤 길인가요? 집 주소처럼 개인적인 내용은 적지 말아 주세요."
            onChange={(event) => update('description', event.target.value)}
          />
        </label>
        <label className="text-sm font-semibold">
          지역 <span className="font-normal text-ink-muted">(비워 두면 자동으로 정해요)</span>
          <input className={INPUT_CLASS} value={form.region} maxLength={30} placeholder={preview?.region ?? ''} onChange={(event) => update('region', event.target.value)} />
        </label>
        <TagPicker<TrailFeature> label="산책길 특징" labels={TRAIL_FEATURE_LABELS} value={form.features} onChange={(value) => update('features', value)} />
        <TagPicker<TrailSuitable> label="이런 아이에게 추천해요" labels={TRAIL_SUITABLE_LABELS} value={form.suitable_for} onChange={(value) => update('suitable_for', value)} />

        <fieldset>
          <legend className="mb-1.5 text-sm font-semibold">대표 이미지</legend>
          <div className="grid grid-cols-3 gap-2">
            <button
              type="button"
              aria-pressed={form.cover_photo_id === null}
              onClick={() => update('cover_photo_id', null)}
              className={`flex aspect-square items-center justify-center rounded-2xl border-2 bg-cream p-2 text-xs font-semibold text-ink-soft ${form.cover_photo_id === null ? 'border-leaf-500' : 'border-line'}`}
            >
              사진 없이
              <br />
              경로 그림
            </button>
            {walk.photos.map((photo, index) => (
              <button
                key={photo.id}
                type="button"
                aria-pressed={form.cover_photo_id === photo.id}
                aria-label={`사진 ${index + 1}을 대표 이미지로`}
                onClick={() => update('cover_photo_id', photo.id)}
                className={`overflow-hidden rounded-2xl border-2 ${form.cover_photo_id === photo.id ? 'border-leaf-500' : 'border-transparent'}`}
              >
                <img src={api.photoUrl(walk.id, photo.id)} alt="" className="aspect-square w-full bg-cream-deep object-cover" />
              </button>
            ))}
            {walk.photos.length < 5 && (
              <label className="flex aspect-square cursor-pointer flex-col items-center justify-center gap-1 rounded-2xl border-2 border-dashed border-line text-xs font-semibold text-ink-soft hover:bg-leaf-50">
                <ImagePlus size={20} className="text-leaf-500" aria-hidden />
                {uploading ? '올리는 중' : '사진 추가'}
                <input type="file" accept="image/*" aria-label="대표 이미지 올리기" className="sr-only" disabled={uploading} onChange={(event) => void addCover(event.target.files).then(() => (event.target.value = ''))} />
              </label>
            )}
          </div>
          <p className="mt-1.5 text-xs text-ink-muted">고른 사진 한 장만 공개돼요. 촬영 위치 정보는 지우고 저장해요.</p>
        </fieldset>

        <ChoiceGroup label="공개 여부" value={form.visibility} options={VISIBILITY_OPTIONS} onChange={(value) => update('visibility', value)} />
        <p className="-mt-2 text-xs text-ink-muted">
          {form.visibility === 'public' ? '커뮤니티에 올라가 누구나 볼 수 있어요.' : '나만 볼 수 있고 커뮤니티에 나오지 않아요.'} 작성자 이름은 “{account?.user?.name}”으로 표시돼요.
        </p>
      </Card>

      {error && <ErrorNotice message={error} />}
      <Button onClick={() => void submit()} disabled={saving || !form.title.trim() || preview === null}>
        <Share2 size={18} aria-hidden />
        {saving ? '저장 중이에요' : trail ? '저장하기' : '공유하기'}
      </Button>
      <Link to={trail ? `/community/trails/${trail.id}` : '/community/share'} className="min-h-11 text-center text-sm font-semibold text-ink-soft underline">
        {trail ? '수정 그만두기' : '다른 산책길 고르기'}
      </Link>
    </div>
  );
}
