import { ImagePlus, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { api } from '../lib/api';
import { MAX_PHOTOS, PHOTO_PRIVACY_NOTE, prepareImage } from '../lib/photos';
import type { SavedWalkDetail } from '../lib/types';
import { Card, ErrorNotice, SectionTitle } from './ui';

/** 저장한 산책길의 사진. 가족만 볼 수 있고, readOnly면 올리거나 지우지 못한다. */
export default function WalkPhotos({ walk, onChange, readOnly = false }: { walk: SavedWalkDetail; onChange: (walk: SavedWalkDetail) => void; readOnly?: boolean }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = async () => onChange(await api.getSavedWalk(walk.id));

  const add = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    setError(null);
    const problems: string[] = [];
    const room = MAX_PHOTOS - walk.photos.length;
    for (const file of Array.from(files).slice(0, room)) {
      try {
        await api.uploadPhoto(walk.id, await prepareImage(file));
      } catch (uploadError) {
        problems.push((uploadError as Error).message);
      }
    }
    if (files.length > room) problems.push(`사진은 ${MAX_PHOTOS}장까지 올릴 수 있어요.`);
    try {
      await reload();
    } catch (loadError) {
      problems.push((loadError as Error).message);
    }
    setError(problems.length ? problems.join(' ') : null);
    setBusy(false);
  };

  const remove = async (photoId: number, index: number) => {
    if (!window.confirm(`사진 ${index + 1}을 삭제할까요?`)) return;
    try {
      await api.deletePhoto(walk.id, photoId);
      await reload();
    } catch (deleteError) {
      setError((deleteError as Error).message);
    }
  };

  return (
    <Card>
      <SectionTitle>
        사진 <span className="text-sm font-normal text-ink-muted">{walk.photos.length} / {MAX_PHOTOS}</span>
      </SectionTitle>
      <div className="grid grid-cols-3 gap-2">
        {walk.photos.map((photo, index) => (
          <div key={photo.id} className="relative">
            <a href={api.photoUrl(walk.id, photo.id)} target="_blank" rel="noreferrer">
              <img
                src={api.photoUrl(walk.id, photo.id)}
                alt={`${walk.title} 사진 ${index + 1}`}
                loading="lazy"
                className="aspect-square w-full rounded-lg bg-cream-deep object-cover"
                data-testid="walk-photo"
              />
            </a>
            {!readOnly && <button
              type="button"
              onClick={() => void remove(photo.id, index)}
              aria-label={`사진 ${index + 1} 삭제`}
              className="absolute top-1 right-1 flex h-8 w-8 items-center justify-center rounded-full bg-white/90 text-ink shadow"
            >
              <Trash2 size={14} aria-hidden />
            </button>}
          </div>
        ))}
        {!readOnly && walk.photos.length < MAX_PHOTOS && (
          <label className="flex aspect-square cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed border-line text-xs font-semibold text-ink-soft hover:bg-leaf-50">
            <ImagePlus size={20} className="text-mango-700" aria-hidden />
            {busy ? '올리는 중' : '사진 추가'}
            <input type="file" accept="image/*" multiple aria-label="사진 추가" className="sr-only" disabled={busy} onChange={(event) => void add(event.target.files).then(() => (event.target.value = ''))} />
          </label>
        )}
      </div>
      {readOnly && walk.photos.length === 0 && <p className="text-sm text-ink-muted">사진이 없어요.</p>}
      <p className="mt-2 text-xs text-ink-muted">{PHOTO_PRIVACY_NOTE}</p>
      {error && (
        <div className="mt-2">
          <ErrorNotice message={error} />
        </div>
      )}
    </Card>
  );
}
