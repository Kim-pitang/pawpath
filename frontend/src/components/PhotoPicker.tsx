import { ImagePlus, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { MAX_PHOTOS, PHOTO_PRIVACY_NOTE, prepareImage } from '../lib/photos';
import { ErrorNotice } from './ui';

export interface PendingPhoto {
  key: string;
  blob: Blob;
  url: string;
}

/** 산책길을 저장하기 전에 붙일 사진을 고른다. 저장한 뒤에 올린다. */
export default function PhotoPicker({ photos, onChange }: { photos: PendingPhoto[]; onChange: (photos: PendingPhoto[]) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const latest = useRef(photos);
  latest.current = photos;

  useEffect(() => () => latest.current.forEach((photo) => URL.revokeObjectURL(photo.url)), []);

  const add = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    setError(null);
    const room = MAX_PHOTOS - latest.current.length;
    const picked = Array.from(files);
    const added: PendingPhoto[] = [];
    const problems: string[] = [];
    for (const file of picked.slice(0, room)) {
      try {
        const blob = await prepareImage(file);
        added.push({ key: `${Date.now()}-${added.length}-${file.name}`, blob, url: URL.createObjectURL(blob) });
      } catch (prepareError) {
        problems.push((prepareError as Error).message);
      }
    }
    if (picked.length > room) problems.push(`사진은 ${MAX_PHOTOS}장까지 고를 수 있어요.`);
    onChange([...latest.current, ...added]);
    setError(problems.length ? problems.join(' ') : null);
    setBusy(false);
  };

  const remove = (key: string) => {
    const target = photos.find((photo) => photo.key === key);
    if (target) URL.revokeObjectURL(target.url);
    onChange(photos.filter((photo) => photo.key !== key));
  };

  return (
    <div className="flex flex-col gap-2" data-testid="photo-picker">
      <p className="text-sm font-semibold">
        사진 <span className="font-normal text-ink-muted">{photos.length} / {MAX_PHOTOS}</span>
      </p>
      <div className="grid grid-cols-4 gap-2">
        {photos.map((photo, index) => (
          <div key={photo.key} className="relative">
            <img src={photo.url} alt={`고른 사진 ${index + 1}`} className="aspect-square w-full rounded-2xl object-cover" data-testid="pending-photo" />
            <button
              type="button"
              onClick={() => remove(photo.key)}
              aria-label={`사진 ${index + 1} 빼기`}
              className="absolute -top-1.5 -right-1.5 flex h-7 w-7 items-center justify-center rounded-full bg-ink text-white shadow"
            >
              <X size={14} aria-hidden />
            </button>
          </div>
        ))}
        {photos.length < MAX_PHOTOS && (
          <label className="flex aspect-square cursor-pointer flex-col items-center justify-center gap-1 rounded-2xl border-2 border-dashed border-line text-xs font-semibold text-ink-soft hover:bg-leaf-50">
            <ImagePlus size={20} className="text-leaf-500" aria-hidden />
            {busy ? '준비 중' : '사진 추가'}
            <input type="file" accept="image/*" multiple aria-label="사진 고르기" className="sr-only" disabled={busy} onChange={(event) => void add(event.target.files).then(() => (event.target.value = ''))} />
          </label>
        )}
      </div>
      <p className="text-xs text-ink-muted">{PHOTO_PRIVACY_NOTE}</p>
      {error && <ErrorNotice message={error} />}
    </div>
  );
}
