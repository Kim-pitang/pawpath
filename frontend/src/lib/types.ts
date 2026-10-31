export type Size = 'small' | 'medium' | 'large';
export type Level = 'low' | 'medium' | 'high';
export type Personality = 'active' | 'timid' | 'curious';
export type PathPreference = 'familiar' | 'new';
export type NoveltyReaction = 'calm' | 'cautious' | 'anxious';
export type Difficulty = 'easy' | 'just_right' | 'hard';
export type WeatherScenario = 'live' | 'rain_later' | 'rain_now' | 'heatwave' | 'cold' | 'heavy_rain';
export type TimeBucket = 'morning' | 'lunch' | 'afternoon' | 'evening';
export type TrackingSource = 'gps' | 'manual' | 'simulation';

export interface PetInput {
  name: string;
  breed: string;
  age_years: number;
  weight_kg: number;
  size: Size;
  activity_level: Level;
  personality: Personality;
  path_preference: PathPreference;
  heat_sensitivity: Level;
  novelty_reaction: NoveltyReaction;
  preferred_distance_km?: number | null;
  preferred_time_bucket?: TimeBucket | null;
}

export interface Pet extends PetInput {
  id: number;
  feedback_total: number;
  created_at: string;
  updated_at: string;
}

export interface TimeWindow {
  start_hour: number;
  end_hour: number;
}

export interface Schedule {
  available_windows: TimeWindow[];
  preferred_duration_min: number;
  walks_per_day: number;
}

export interface WeatherHour {
  time: string;
  temperature: number;
  apparent_temperature: number;
  precipitation_probability: number;
  precipitation_mm: number;
  humidity: number;
  wind_speed: number;
  uv_index: number | null;
  is_day: boolean;
}

export interface WeatherMeta {
  source: string;
  scenario: string;
  is_mock: boolean;
  notice: string | null;
}

export interface CurrentWeather extends WeatherMeta {
  current: WeatherHour;
  condition: string;
  walk_comfort_hint: string;
}

export interface ForecastWeather extends WeatherMeta {
  hours: WeatherHour[];
}

export interface Facility {
  type: string;
  name: string;
  lat: number;
  lng: number;
}

export interface Course {
  id: number;
  code: string;
  name: string;
  description: string;
  area: string;
  start_lat: number;
  start_lng: number;
  distance_km: number;
  duration_min: number;
  route: [number, number][];
  has_park: boolean;
  park_names: string[];
  lighting: string;
  is_paved: boolean;
  surface_note: string;
  crowd_level: string;
  pet_allowed: boolean;
  pet_rule_note: string;
  is_familiar: boolean;
  shade_level: number;
  difficulty: string;
  traffic_exposure: string;
  scenery_tags: string[];
  facilities: Facility[];
  data_sources: {
    route?: string;
    facilities?: string;
    team_estimates?: string[];
    observed?: string[];
    /** 측정도 추정도 없어 '확인 불가'로 표시하는 속성. 내 산책길 코스에만 있다. */
    unknown?: string[];
  };
  /** 내 산책길로 만든 코스. 주인에게만 보인다. */
  is_personal?: boolean;
  environment?: {
    collected_on?: string;
    road?: { pedestrian: number; local: number; major: number; unknown: number } | null;
    lit?: { yes: number; no: number; unknown: number } | null;
    trees?: number | null;
  } | null;
}

export interface Approach {
  mode: 'routed' | 'straight' | 'too_far';
  distance_m: number;
  duration_min: number;
  route: [number, number][];
  notice: string | null;
}

export interface SlotWeather {
  temperature: number;
  apparent_temperature: number;
  precipitation_probability: number;
  precipitation_mm: number;
  humidity: number;
  wind_speed: number;
  uv_index: number | null;
}

export interface Slot {
  start: string;
  end: string;
  label: string;
  duration_min: number;
  score: number;
  components: Record<string, number>;
  excluded_reason: string | null;
  before_rain: boolean;
  rain_onset: string | null;
  rain_overlap_min: number;
  is_dark: boolean;
  fits_window: boolean;
  weather: SlotWeather;
}

export interface Factor {
  key: string;
  label: string;
  score: number;
  weight: number;
  contribution: number;
  evidence: string[];
}

export interface Safety {
  lighting: string;
  lighting_text: string;
  lighting_is_estimate: boolean;
  has_park: boolean;
  park_names: string[];
  is_paved: boolean;
  surface_note: string;
  traffic_exposure: string;
  crowd_level: string;
  pet_allowed: boolean;
  pet_rule_note: string;
  verified_facilities: Record<string, number>;
  is_personal?: boolean;
  unknown?: string[];
}

export interface SafetyItem {
  key: string;
  label: string;
  status: 'ok' | 'caution' | 'danger' | 'unverified';
  score: number | null;
  value: string;
  source: 'forecast' | 'demo' | 'observed' | 'estimated' | 'unknown';
  source_label: string;
  detail: string | null;
}

export interface SafetyAssessment {
  score: number;
  level: 'good' | 'caution' | 'danger' | 'blocked';
  items: SafetyItem[];
  risks: string[];
  blocked_reasons: string[];
  unverified: string[];
  penalty: number;
  disclaimer: string;
}

export interface ScoreGroup {
  key: string;
  label: string;
  score: number;
  weight: number;
  contribution: number;
  evidence: string[];
}

export interface RecommendedCourse {
  rank: number;
  course_id: number;
  code: string;
  name: string;
  description: string;
  is_personal?: boolean;
  distance_km: number;
  duration_min: number;
  total_score: number;
  baseline_score: number;
  learning_delta: number;
  baseline_rank: number;
  rank_change: number;
  preference_score: number;
  visit_count: number;
  feedback_count: number;
  recommended_time: Slot;
  safety: Safety;
  safety_assessment: SafetyAssessment;
  alternative: { course_id: number; name: string; distance_km: number; duration_min: number } | null;
  score_breakdown: ScoreGroup[];
  factors: Factor[];
  reason: { summary: string; details: string[]; llm_summary?: string };
  cautions: string[];
  other_cautions: string[];
}

export interface Recommendation {
  id: number;
  created_at: string;
  pet_id: number;
  pet_name: string;
  walkable: boolean;
  weather: WeatherMeta;
  features: {
    life_stage: string;
    ideal_walk_min: number;
    ideal_distance_km: number;
    novelty_tolerance: number;
    crowd_tolerance: number;
    comfort_low: number;
    comfort_high: number;
  };
  schedule: {
    windows: TimeWindow[];
    preferred_duration_min: number;
    walks_per_day: number;
  };
  time_recommendation: {
    recommended_duration_min: number;
    best_slots: Slot[];
    slots: Slot[];
  };
  courses: RecommendedCourse[];
  weights: Record<string, number>;
  learning: { feedback_total: number; is_personalized: boolean; mode: 'rule_based' | 'personalized'; ranker: string };
  excluded_courses: { course_id: number; name: string; reasons: string[] }[];
  explanation_engine: {
    provider: string;
    model: string | null;
    status: 'disabled' | 'pending' | 'ok' | 'failed' | 'rejected';
  };
  blocked_reasons: string[];
  indoor_alternatives: string[];
  disclaimer: string;
}

export interface FeedbackInput {
  walk_id: number;
  walk_rating: number;
  pet_rating: number;
  difficulty: Difficulty;
  weather_rating: number;
  would_revisit: boolean;
  memo: string;
}

export interface FeedbackBrief {
  id: number;
  walk_rating: number;
  pet_rating: number;
  difficulty: Difficulty;
  weather_rating: number;
  would_revisit: boolean;
  memo: string;
  affinity_before: number;
  affinity_after: number;
  created_at: string;
}

export interface Feedback extends FeedbackBrief {
  walk_id: number;
  pet_id: number;
  course_id: number;
  course_name: string;
  signal: number;
}

export interface Walk {
  id: number;
  pet_id: number;
  course_id: number;
  course_name: string;
  distance_km: number;
  recommendation_id: number | null;
  started_at: string;
  ended_at: string;
  duration_min: number;
  feedback: FeedbackBrief | null;
  tracking_source: TrackingSource;
  is_simulated: boolean;
}

export interface Insights {
  pet_id: number;
  pet_name: string;
  stats: {
    walk_count: number;
    total_minutes: number;
    total_distance_km: number;
    feedback_count: number;
    average_pet_rating: number | null;
    simulated_walk_count: number;
  };
  courses: {
    course_id: number;
    course_name: string;
    visit_count: number;
    feedback_count: number;
    affinity: number;
    average_pet_rating: number | null;
  }[];
  attributes: { key: string; label: string; weight: number }[];
  attributes_learned: boolean;
  time_preferences: { key: string; label: string; score: number; samples: number }[];
  affinity_history: {
    feedback_id: number;
    created_at: string;
    course_id: number;
    course_name: string;
    pet_rating: number;
    before: number;
    after: number;
  }[];
  recommendation_history: {
    id: number;
    created_at: string;
    scenario: string;
    feedback_total: number;
    courses: { rank: number; course_id: number; name: string; total_score: number }[];
  }[];
}

export interface RouteResult {
  mode: 'routed' | 'straight' | 'too_far';
  distance_m: number;
  duration_min: number;
  route: [number, number][];
  notice: string | null;
}

export interface AlternativeResult {
  course_id: number;
  status: 'continue' | 'shorten' | 'return_now' | 'unknown';
  action: 'continue' | 'return_to_start' | 'finish_course' | 'no_location' | 'no_walking_route';
  reasons: string[];
  remaining_m: number;
  remaining_min: number;
  checked_at: string;
  cache_minutes: number;
  data_limit: string;
  weather: WeatherMeta;
  assessment: SafetyAssessment | null;
  return_route: RouteResult | null;
  location_notice: string | null;
  alternatives: {
    course_id: number;
    name: string;
    distance_km: number;
    duration_min: number;
    from_here_m: number;
    safety_score: number;
    safety_level: SafetyAssessment['level'];
    reason: string;
  }[];
}

export interface NearbyPlace {
  type: string;
  label: string;
  name: string;
  lat: number;
  lng: number;
  distance_m: number;
  note: string | null;
}

export interface NearbyResult {
  course_id: number;
  radius_m: number;
  source: string;
  collected_on: string | null;
  unavailable_types: string[];
  notice: string;
  places: NearbyPlace[];
}

export interface WalkReport {
  pet_id: number;
  pet_name: string;
  week: { start: string; end: string; offset: number };
  summary: {
    walk_count: number;
    total_distance_km: number;
    total_minutes: number;
    average_minutes: number | null;
    average_pet_rating: number | null;
  };
  previous_week: WalkReport['summary'];
  change: Record<'walk_count' | 'total_distance_km' | 'total_minutes', { difference: number; percent: number | null }>;
  daily: {
    date: string;
    weekday: string;
    walk_count: number;
    distance_km: number;
    minutes: number;
    average_pet_rating: number | null;
    walks: { id: number; course_name: string; distance_km: number; duration_min: number }[];
  }[];
  favorite_courses: { course_id: number; course_name: string; visit_count: number; average_pet_rating: number | null }[];
  satisfaction_trend: { feedback_id: number; date: string; course_name: string; pet_rating: number; walk_rating: number }[];
  recommendation_vs_actual: {
    walks: { walk_id: number; date: string; recommended_top: string | null; chosen: string; chosen_rank: number | null; followed_top: boolean }[];
    followed_top_count: number;
    in_top_three_count: number;
  };
  simulated_walks_excluded: number;
  total_simulated_walks: number;
}

// 나만의 산책길
export type Visibility = 'private' | 'link' | 'public';
export type WalkSourceType = 'recorded' | 'imported' | 'generated';
export type SavedWalkSort = 'recent' | 'distance';

export interface WalkPointInput {
  latitude: number;
  longitude: number;
  altitude: number | null;
  accuracy: number | null;
  recorded_at: string | null;
  segment: number;
}

export interface RouteFit {
  score: number | null;
  level: 'good' | 'caution' | 'danger' | 'blocked' | null;
  summary: string;
  details: string[];
  cautions: string[];
  highlights: string[];
  start_label: string | null;
  unknown: string[];
  excluded: string[];
}

export interface GeneratedRoute {
  route: [number, number][];
  distance_m: number;
  duration_min: number;
  repeated_pct: number;
  start_snap_m: number;
  fit: RouteFit | null;
}

export interface GenerateRouteResult {
  target_min: number;
  candidates: GeneratedRoute[];
  notice: string | null;
  scored_for: string | null;
  fit_notice: string | null;
}

export interface SavedWalkInput {
  title: string;
  pet_id: number | null;
  memo: string;
  visibility: Visibility;
  share_memo: boolean;
  source_type: WalkSourceType;
  client_id: string;
  duration_sec?: number;
  points: WalkPointInput[];
}

export interface SavedWalkSummary {
  id: number;
  pet_id: number | null;
  pet_name: string | null;
  title: string;
  source_type: WalkSourceType;
  started_at: string;
  ended_at: string | null;
  distance_m: number;
  duration_sec: number | null;
  average_speed_mps: number | null;
  has_timestamps: boolean;
  point_count: number;
  visibility: Visibility;
  preview: number[][][];
}

export interface WalkPhoto {
  id: number;
  content_type: string;
  size_bytes: number;
  created_at: string;
}

export interface PersonalCourse {
  id: number;
  active: boolean;
  area: string;
  in_current_area: boolean;
  environment_measured: boolean;
  measurement: 'pending' | 'done' | 'failed' | 'off';
  unknown: string[];
  notes: string[];
}

export interface SavedWalkDetail extends SavedWalkSummary {
  course: PersonalCourse | null;
  memo: string;
  share_token: string | null;
  share_expires_at: string | null;
  share_memo: boolean;
  route: number[][][];
  photos: WalkPhoto[];
}

export interface SharedWalk {
  title: string;
  distance_m: number;
  duration_sec: number | null;
  memo: string | null;
  start: number[];
  end: number[];
  route: number[][][];
}

export interface PublicWalk {
  token: string;
  title: string;
  distance_m: number;
  duration_sec: number | null;
  preview: number[][][];
}

export interface GpxPreview {
  name: string | null;
  version: string;
  track_count: number;
  segment_count: number;
  point_count: number;
  invalid_point_count: number;
  has_timestamps: boolean;
  distance_m: number;
  duration_sec: number | null;
  started_at: string | null;
  ended_at: string | null;
  average_speed_mps: number | null;
  warnings: string[];
  duplicate_of: { id: number; title: string } | null;
  points: { segment: number; latitude: number; longitude: number; altitude: number | null; recorded_at: string | null }[];
}

// 계정
export interface AccountUser {
  id: number;
  name: string;
  /** Google 로그인 사용자는 아이디가 없다. */
  login_id: string | null;
  email: string | null;
  provider: 'password' | 'google';
}

export interface Account {
  authenticated: boolean;
  auth_required: boolean;
  google_enabled: boolean;
  user: AccountUser | null;
}

