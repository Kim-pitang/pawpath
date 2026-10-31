function clock(date: Date): string {
  const hours = date.getHours();
  const minutes = date.getMinutes();
  const period = hours < 12 ? '오전' : '오후';
  const hour12 = hours % 12 === 0 ? 12 : hours % 12;
  return `${period} ${hour12}:${String(minutes).padStart(2, '0')}`;
}

export function hourLabel(iso: string): string {
  return `${new Date(iso).getHours()}시`;
}

export function dayLabel(iso: string): string {
  const date = new Date(iso);
  const today = new Date();
  const dayDiff = Math.round(
    (new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime() -
      new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime()) /
      86400000,
  );
  if (dayDiff === 0) return '오늘';
  if (dayDiff === 1) return '내일';
  if (dayDiff === -1) return '어제';
  return `${date.getMonth() + 1}월 ${date.getDate()}일`;
}

export function slotRange(startIso: string, endIso: string): string {
  return `${dayLabel(startIso)} ${clock(new Date(startIso))} ~ ${clock(new Date(endIso))}`;
}

export function dateTimeLabel(iso: string): string {
  return `${dayLabel(iso)} ${clock(new Date(iso))}`;
}

/** 서비스 시각 형식(타임존 없는 현지 시각)으로 바꾼다. */
export function toLocalIso(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

export function windowLabel(start: number, end: number): string {
  return `${start}시 ~ ${end}시`;
}

export function signed(value: number, digits = 1): string {
  const fixed = Math.abs(value).toFixed(digits);
  if (Number(fixed) === 0) return fixed;
  return `${value > 0 ? '+' : '−'}${fixed}`;
}

export function dateLabel(date: Date): string {
  return `${date.getMonth() + 1}월 ${date.getDate()}일`;
}

export function distanceLabel(meters: number): string {
  return meters < 1000 ? `${Math.round(meters)}m` : `${(meters / 1000).toFixed(2)}km`;
}

export function durationLabel(seconds: number | null): string {
  if (seconds === null) return '시간 정보 없음';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours > 0) return `${hours}시간 ${minutes}분`;
  if (minutes > 0) return `${minutes}분 ${Math.round(seconds % 60)}초`;
  return `${Math.round(seconds)}초`;
}

export function speedLabel(metersPerSecond: number | null): string {
  return metersPerSecond === null ? '-' : `${(metersPerSecond * 3.6).toFixed(1)}km/h`;
}

export function clockLabel(ms: number): string {
  const total = Math.floor(ms / 1000);
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${pad(Math.floor(total / 3600))}:${pad(Math.floor((total % 3600) / 60))}:${pad(total % 60)}`;
}

