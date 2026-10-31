import { api } from './api';

export const MAX_PHOTOS = 5;
const MAX_SIDE = 1600;
const QUALITY = 0.85;

/**
 * 사진을 다시 그려 JPEG로 만든다. 촬영 위치 같은 메타데이터가 빠지고 용량도 줄어든다.
 * 브라우저가 사진의 회전 정보를 반영해 그리므로 방향은 그대로 유지된다.
 */
export async function prepareImage(file: File): Promise<Blob> {
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.src = url;
    try {
      await image.decode();
    } catch {
      throw new Error(`${file.name}: 열 수 없는 사진이에요. JPG나 PNG로 바꿔 올려 주세요.`);
    }
    const scale = Math.min(1, MAX_SIDE / Math.max(image.naturalWidth, image.naturalHeight));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
    const context = canvas.getContext('2d');
    if (!context) throw new Error('사진을 준비하지 못했어요.');
    // 투명한 PNG가 검게 나오지 않도록 흰 바탕을 깐다.
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', QUALITY));
    if (!blob) throw new Error('사진을 준비하지 못했어요.');
    return blob;
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** 순서대로 올리고 실패한 장수를 돌려준다. 산책길은 이미 저장된 뒤라 사진 실패로 되돌리지 않는다. */
export async function uploadPhotos(walkId: number, photos: Blob[]): Promise<number> {
  let failedCount = 0;
  for (const photo of photos) {
    try {
      await api.uploadPhoto(walkId, photo);
    } catch {
      failedCount += 1;
    }
  }
  return failedCount;
}

export const PHOTO_PRIVACY_NOTE = '사진은 나만 볼 수 있고 공유 화면에는 나오지 않아요. 촬영 위치 정보는 지우고 저장해요.';
