import type { HideRadius, TrailDifficulty, TrailFeature, TrailSuitable, TrailVisibility, Visibility, WalkSourceType, Difficulty, Level, NoveltyReaction, PathPreference, Personality, Size, TimeBucket, WeatherScenario } from './types';

export const SIZE_LABELS: Record<Size, string> = { small: '소형견', medium: '중형견', large: '대형견' };
export const ACTIVITY_LABELS: Record<Level, string> = { low: '낮음', medium: '보통', high: '높음' };
export const HEAT_LABELS: Record<Level, string> = { low: '더위에 강해요', medium: '보통', high: '더위를 많이 타요' };
export const PERSONALITY_LABELS: Record<Personality, string> = {
  active: '활발함',
  timid: '소심함',
  curious: '호기심 많음',
};
export const PATH_LABELS: Record<PathPreference, string> = { familiar: '익숙한 길 선호', new: '새로운 길 선호' };
export const NOVELTY_LABELS: Record<NoveltyReaction, string> = {
  calm: '금방 적응해요',
  cautious: '조심스러워요',
  anxious: '많이 불안해해요',
};
export const DIFFICULTY_LABELS: Record<Difficulty, string> = {
  easy: '쉬웠어요',
  just_right: '딱 좋았어요',
  hard: '힘들었어요',
};

export const TIME_BUCKET_LABELS: Record<TimeBucket, string> = {
  morning: '오전',
  lunch: '점심',
  afternoon: '오후',
  evening: '저녁',
};

export const SCENARIO_LABELS: Record<WeatherScenario, string> = {
  live: '실제 날씨',
  rain_later: '곧 비',
  rain_now: '지금 비',
  heatwave: '폭염',
  cold: '한파',
  heavy_rain: '폭우',
};

export const FACILITY_LABELS: Record<string, string> = {
  park: '공원',
  dog_park: '반려견 놀이터',
  pet_friendly: '반려동물 동반 표시',
  pet_shop: '반려용품점',
  convenience: '편의점',
  toilets: '화장실',
  drinking_water: '음수대',
  veterinary: '동물병원',
  bench: '벤치',
  waste_basket: '쓰레기통',
  police: '경찰시설',
  surveillance: 'CCTV',
};

export const CROWD_LABELS: Record<string, string> = { low: '낮음', medium: '보통', high: '높음' };
export const TRAFFIC_LABELS: Record<string, string> = {
  low: '차량 노출 적음',
  medium: '차량 노출 보통',
  high: '차량 노출 많음',
};
export const DIFFICULTY_COURSE_LABELS: Record<string, string> = {
  easy: '평탄해요',
  moderate: '오르막 있어요',
  hard: '가팔라요',
};

export const SCHEDULE_PRESETS = [
  { key: 'morning', label: '오전', start_hour: 7, end_hour: 11 },
  { key: 'lunch', label: '점심', start_hour: 11, end_hour: 14 },
  { key: 'afternoon', label: '오후', start_hour: 14, end_hour: 18 },
  { key: 'evening', label: '저녁', start_hour: 18, end_hour: 22 },
];

export const WEATHER_SOURCE_LABELS: Record<string, string> = {
  'open-meteo': 'Open-Meteo 실시간 예보',
  mock: '모의 날씨',
  'mock-fallback': '모의 날씨 (API 연결 실패)',
};

export const VISIBILITY_LABELS: Record<Visibility, string> = { private: '비공개', link: '링크 공유', public: '공개' };
export const VISIBILITY_HINTS: Record<Visibility, string> = {
  private: '공유 링크와 공개 목록에 나오지 않아요. 커뮤니티 공유는 산책길 상세에서 따로 정해요.',
  link: '링크를 받은 사람만 볼 수 있어요.',
  public: '공개된 산책길 목록에 올라가 누구나 볼 수 있어요.',
};
export const WALK_SOURCE_LABELS: Record<WalkSourceType, string> = { recorded: '직접 기록', imported: 'GPX 가져옴' };

export const TRAIL_VISIBILITY_LABELS: Record<TrailVisibility, string> = { public: '공개', private: '비공개' };
export const TRAIL_DIFFICULTY_LABELS: Record<TrailDifficulty, string> = { easy: '가벼워요', moderate: '보통이에요', hard: '힘들어요' };
export const TRAIL_FEATURE_LABELS: Record<TrailFeature, string> = {
  park: '공원',
  shade: '그늘',
  flat: '평지',
  paved: '포장길',
  waterside: '물가',
  forest: '숲길',
  quiet: '한적해요',
  lit: '밤에도 밝아요',
};
export const TRAIL_SUITABLE_LABELS: Record<TrailSuitable, string> = {
  small: '소형견',
  medium: '중형견',
  large: '대형견',
  senior: '노령견',
  puppy: '어린 강아지',
  active: '활동량 많은 아이',
  timid: '겁 많은 아이',
};
export const HIDE_RADIUS_OPTIONS: { value: HideRadius; label: string }[] = [
  { value: 100, label: '100m' },
  { value: 200, label: '200m' },
  { value: 300, label: '300m' },
  { value: 500, label: '500m' },
];
