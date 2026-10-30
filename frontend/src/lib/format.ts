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
