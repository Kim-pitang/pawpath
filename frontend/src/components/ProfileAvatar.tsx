import { Bone, Flower, Heart, Leaf, Moon, PawPrint, Star, Sun, type LucideIcon } from 'lucide-react';
import type { AvatarKey } from '../lib/types';

/** 프로필 아바타. 사진을 올리지 않고 PawPath의 색과 아이콘에서 고른다. */
export const AVATARS: Record<AvatarKey, { icon: LucideIcon; label: string; tone: string }> = {
  paw: { icon: PawPrint, label: '발바닥', tone: 'bg-carrot-50 text-carrot-500' },
  bone: { icon: Bone, label: '뼈다귀', tone: 'bg-cream-deep text-ink-soft' },
  sun: { icon: Sun, label: '해', tone: 'bg-carrot-100 text-carrot-700' },
  moon: { icon: Moon, label: '달', tone: 'bg-sky-500/15 text-sky-500' },
  leaf: { icon: Leaf, label: '나뭇잎', tone: 'bg-leaf-50 text-leaf-600' },
  heart: { icon: Heart, label: '하트', tone: 'bg-plum-500/15 text-plum-500' },
  star: { icon: Star, label: '별', tone: 'bg-leaf-100 text-leaf-800' },
  flower: { icon: Flower, label: '꽃', tone: 'bg-carrot-50 text-plum-500' },
};
export const AVATAR_KEYS = Object.keys(AVATARS) as AvatarKey[];

const SIZES = {
  xs: { box: 'h-7 w-7 rounded-full', icon: 15 },
  sm: { box: 'h-10 w-10 rounded-2xl', icon: 20 },
  md: { box: 'h-14 w-14 rounded-2xl', icon: 28 },
  lg: { box: 'h-24 w-24 rounded-3xl md:h-28 md:w-28', icon: 48 },
};

export default function ProfileAvatar({ avatar, size = 'sm', className = '' }: { avatar: AvatarKey; size?: keyof typeof SIZES; className?: string }) {
  const { icon: Icon, tone } = AVATARS[avatar] ?? AVATARS.paw;
  const { box, icon } = SIZES[size];
  return (
    <span className={`flex shrink-0 items-center justify-center ${box} ${tone} ${className}`} aria-hidden>
      <Icon size={icon} />
    </span>
  );
}
