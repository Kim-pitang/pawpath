export type Size = 'small' | 'medium' | 'large';
export type Level = 'low' | 'medium' | 'high';
export type Personality = 'active' | 'timid' | 'curious';
export type PathPreference = 'familiar' | 'new';
export type NoveltyReaction = 'calm' | 'cautious' | 'anxious';
export type Difficulty = 'easy' | 'just_right' | 'hard';
export type WeatherScenario = 'live' | 'rain_later' | 'heatwave' | 'cold' | 'heavy_rain';

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
  };
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
}

export interface RecommendedCourse {
  rank: number;
  course_id: number;
  code: string;
  name: string;
  description: string;
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
  factors: Factor[];
  reason: { summary: string; details: string[] };
  cautions: string[];
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
  learning: { feedback_total: number; is_personalized: boolean };
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
