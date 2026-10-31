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
  source: 'forecast' | 'demo' | 'observed' | 'estimated' | 'unknown' | 'unavailable';
  source_label: string;
  detail: string | null;
}

/** 점수에 들어간 안전 항목의 출처별 비중. */
export interface SafetyDataQuality {
  shares: { realtime: number; observed: number; estimated: number; demo: number; missing: number };
  missing_items: string[];
  estimated_items: string[];
  environment_collected_on: string | null;
  insufficient: boolean;
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
  data_quality?: SafetyDataQuality;
  /** 위험 수준일 때의 강한 경고 */
  warning?: string | null;
}

export interface ScoreGroup {
  key: string;
  label: string;
  score: number;
  weight: number;
  contribution: number;
  evidence: string[];
}

/** v2 개인화 묶음. 데이터가 없는 묶음은 available이 false이고 score가 null이다. */
export interface ScoreGroupDetail extends Omit<ScoreGroup, 'score'> {
  score: number | null;
  available: boolean;
  source: string;
}

export interface ReasonBasis {
  key: string;
  label: string;
  text: string;
  source: string;
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
  reason: { summary: string; details: string[]; llm_summary?: string; basis?: ReasonBasis[] };
  cautions: string[];
  other_cautions: string[];
  personalization_score?: number | null;
  safety_penalty?: number;
  skip_penalty?: number;
  score_groups?: ScoreGroupDetail[];
  /** 다녀온 코스만 남아 바꿔 넣은 새 코스 */
  exploration?: boolean;
  similar_to?: string | null;
}

export type RecommendationStatus = 'ok' | 'unsafe' | 'no_forecast' | 'no_window' | 'no_candidates';

export interface Recommendation {
  id: number;
  created_at: string;
  pet_id: number;
  pet_name: string;
  walkable: boolean;
  status?: RecommendationStatus;
  data_notice?: string | null;
  algorithm?: { version: string; ranker: string; base_weights: Record<string, number> };
  weather: WeatherMeta & { fetched_at?: string | null; is_available?: boolean };
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
  /** 커뮤니티 산책길로 걸었으면 그 번호. 산책을 마친 뒤 후기로 잇는다. */
  community_trail_id?: number | null;
  /** 산책을 한 프로필. */
  profile?: ProfileBrief | null;
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
  /** 커뮤니티에 공유한 상태. */
  community_trail: { id: number; visibility: TrailVisibility } | null;
  id: number;
  pet_id: number | null;
  pet_name: string | null;
  /** 산책길을 만든 프로필. */
  profile?: ProfileBrief | null;
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
  /** 코스가 없을 때 추천 후보가 되지 못한 이유. 후보이거나 직접 뺐으면 비어 있다. */
  course_blocked?: string | null;
  memo: string;
  share_token: string | null;
  share_expires_at: string | null;
  share_memo: boolean;
  route: number[][][];
  photos: WalkPhoto[];
  /** 지금 프로필이 고치고 지울 수 있으면 참이다. 만든 프로필이나 대표 프로필만 할 수 있다. */
  can_manage?: boolean;
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

export interface AccountSummary {
  provider: 'password' | 'google';
  /** 참이면 탈퇴 전에 본인을 다시 확인해야 한다. */
  reauth_required: boolean;
  session_expires_at: string;
  session_idle_days: number;
  data: {
    /** 대표 프로필 말고 더 만든 프로필 수. */
    profiles?: number;
    pets: number;
    walks: number;
    feedback: number;
    recommendations: number;
    saved_walks: number;
    photos: number;
    personal_courses: number;
    shared_walks: number;
    community_trails: number;
    trail_reviews: number;
  };
  /** 자동 백업을 쓰지 않으면 비어 있다. */
  backup_retention_days: number | null;
}

export interface Account {
  authenticated: boolean;
  auth_required: boolean;
  google_enabled: boolean;
  user: AccountUser | null;
  /** 아래는 예전 서버나 로그인하지 않은 상태에서는 비어 있을 수 있다. */
  profiles?: Profile[];
  max_profiles?: number;
  /** 이 세션에서 쓰는 프로필. 서버가 계정 소속을 확인한 값이다. */
  current_profile?: Profile | null;
  /** 프로필이 여러 개인데 아직 고르지 않았으면 참이다. */
  profile_required?: boolean;
}

export type AvatarKey = 'paw' | 'bone' | 'sun' | 'moon' | 'leaf' | 'heart' | 'star' | 'flower';
export type WalkScope = 'profile' | 'family';

/** 대표 계정 안의 보호자 프로필. 따로 로그인하지 않는다. */
export interface Profile {
  id: number;
  name: string;
  avatar_key: AvatarKey;
  is_default: boolean;
  created_at: string;
  updated_at: string;
  last_active_at: string | null;
}
/** 기록에 붙는 프로필. 지운 프로필도 이름이 남는다. */
export interface ProfileBrief {
  id: number;
  name: string;
  avatar_key: AvatarKey;
  is_default: boolean;
  deleted: boolean;
}
export interface ProfileActivity {
  walk_count: number;
  total_distance_km: number;
  total_minutes: number;
  saved_walk_count: number;
  simulated_walk_count: number;
  last_walk_at: string | null;
}
export interface ProfileDetail extends Profile {
  activity: ProfileActivity;
}
export interface FamilyOverview {
  profile_count: number;
  max_profiles: number;
  totals: ProfileActivity;
  members: { profile: ProfileBrief; last_active_at: string | null; activity: ProfileActivity }[];
  pets: { id: number; name: string; breed: string; walk_count: number }[];
  recent_walks: Walk[];
}

// 산책길 커뮤니티
export type TrailVisibility = 'public' | 'private';
export type TrailSort = 'recent' | 'popular' | 'rating';
export type TrailDifficulty = 'easy' | 'moderate' | 'hard';
export type TrailFeature = 'park' | 'shade' | 'flat' | 'paved' | 'waterside' | 'forest' | 'quiet' | 'lit';
export type TrailSuitable = 'small' | 'medium' | 'large' | 'senior' | 'puppy' | 'active' | 'timid';
export type HideRadius = 100 | 200 | 300 | 500;

export interface TrailSummary {
  id: number;
  title: string;
  description: string;
  region: string;
  author_name: string;
  cover_photo_id: number | null;
  visibility: TrailVisibility;
  features: TrailFeature[];
  suitable_for: TrailSuitable[];
  distance_m: number;
  estimated_min: number;
  elevation_gain_m: number | null;
  difficulty: TrailDifficulty;
  preview: number[][][];
  view_count: number;
  like_count: number;
  bookmark_count: number;
  review_count: number;
  average_rating: number | null;
  liked: boolean;
  bookmarked: boolean;
  is_mine: boolean;
  created_at: string;
  updated_at: string;
}

export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
  has_next: boolean;
}

export type TrailReactionPage = Paged<TrailSummary> & { hidden_count: number };

export interface TrailNearby extends TrailSummary {
  distance_from_me_m: number;
}

export interface TrailRecommended extends TrailSummary {
  match_score: number;
  reasons: string[];
}

export interface TrailReview {
  id: number;
  trail_id: number;
  rating: number;
  content: string;
  author_name: string;
  is_mine: boolean;
  verified: boolean;
  edited: boolean;
  photos: { id: number }[];
  created_at: string;
  updated_at: string;
}

export interface MyTrailReview extends TrailReview {
  trail_available: boolean;
  trail_title: string | null;
}

export interface TrailDetail extends TrailSummary {
  route: number[][][];
  start: number[];
  end: number[];
  start_label: string | null;
  end_label: string | null;
  can_navigate: boolean;
  my_review: TrailReview | null;
  walked: boolean;
  owner: { saved_walk_id: number; hide_radius_m: number } | null;
}

export interface TrailPreview {
  saved_walk_id: number;
  hide_radius_m: number;
  hidden_m: number;
  region: string;
  distance_m: number;
  estimated_min: number;
  elevation_gain_m: number | null;
  difficulty: TrailDifficulty;
  start_label: string | null;
  end_label: string | null;
  can_navigate: boolean;
  route: number[][][];
}

export interface TrailInput {
  title: string;
  description: string;
  cover_photo_id: number | null;
  visibility: TrailVisibility;
  region: string;
  features: TrailFeature[];
  suitable_for: TrailSuitable[];
  hide_radius_m: HideRadius;
}

export interface TrailQuery {
  q?: string;
  region?: string;
  min_km?: number;
  max_km?: number;
  min_minutes?: number;
  max_minutes?: number;
  difficulty?: TrailDifficulty;
  suitable?: TrailSuitable;
  sort?: TrailSort;
  page?: number;
  size?: number;
}
