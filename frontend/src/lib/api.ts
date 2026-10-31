import type {
  AlternativeResult,
  Approach,
  Course,
  CurrentWeather,
  Feedback,
  FeedbackInput,
  ForecastWeather,
  Insights,
  NearbyResult,
  Pet,
  PetInput,
  Recommendation,
  RouteResult,
  Schedule,
  TrackingSource,
  Walk,
  WalkReport,
  WeatherScenario,
} from './types';

const BASE = import.meta.env.VITE_API_URL ?? '/api';

export class ApiError extends Error {}

function describeDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return '입력한 값을 다시 확인해 주세요.';
  return '요청을 처리하지 못했어요.';
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    });
  } catch {
    throw new ApiError('서버에 연결할 수 없어요. 백엔드가 실행 중인지 확인해 주세요.');
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(describeDetail(body.detail));
  }
  return response.json();
}

const post = <T>(path: string, body: unknown) => request<T>(path, { method: 'POST', body: JSON.stringify(body) });
const put = <T>(path: string, body: unknown) => request<T>(path, { method: 'PUT', body: JSON.stringify(body) });

export const api = {
  listPets: () => request<Pet[]>('/pets'),
  getPet: (id: number) => request<Pet>(`/pets/${id}`),
  createPet: (body: PetInput) => post<Pet>('/pets', body),
  updatePet: (id: number, body: PetInput) => put<Pet>(`/pets/${id}`, body),
  insights: (id: number) => request<Insights>(`/pets/${id}/insights`),

  getSchedule: () => request<Schedule>('/schedule'),
  updateSchedule: (body: Schedule) => put<Schedule>('/schedule', body),

  currentWeather: (scenario: WeatherScenario, petId?: number) =>
    request<CurrentWeather>(`/weather/current?scenario=${scenario}${petId ? `&pet_id=${petId}` : ''}`),
  forecast: (scenario: WeatherScenario, hours = 24) =>
    request<ForecastWeather>(`/weather/forecast?scenario=${scenario}&hours=${hours}`),

  listCourses: () => request<Course[]>('/courses'),
  getCourse: (id: number) => request<Course>(`/courses/${id}`),
  approach: (courseId: number, latitude: number, longitude: number) =>
    post<Approach>(`/courses/${courseId}/approach`, { latitude, longitude }),
  nearbyPlaces: (courseId: number, radiusM = 300, types?: string[]) =>
    request<NearbyResult>(`/courses/${courseId}/nearby?radius_m=${radiusM}${types ? `&types=${types.join(',')}` : ''}`),
  walkingRoute: (from: [number, number], to: [number, number]) =>
    post<RouteResult>('/routes/walking', { from_latitude: from[0], from_longitude: from[1], to_latitude: to[0], to_longitude: to[1] }),
  alternativeRoute: (body: {
    pet_id: number;
    course_id: number;
    latitude: number | null;
    longitude: number | null;
    progress_m: number;
    weather_scenario: WeatherScenario;
  }) => post<AlternativeResult>('/routes/alternative', body),

  recommend: (petId: number, scenario: WeatherScenario) =>
    post<Recommendation>('/recommendations', { pet_id: petId, weather_scenario: scenario }),
  latestRecommendations: (petId: number, limit = 1) =>
    request<Recommendation[]>(`/recommendations?pet_id=${petId}&limit=${limit}`),
  explainRecommendation: (id: number) => post<Recommendation>(`/recommendations/${id}/explain`, {}),

  createWalk: (body: {
    pet_id: number;
    course_id: number;
    recommendation_id: number | null;
    duration_min: number;
    started_at?: string;
    tracking_source?: TrackingSource;
    distance_km?: number;
  }) =>
    post<Walk>('/walks', body),
  listWalks: (petId: number) => request<Walk[]>(`/walks?pet_id=${petId}`),
  walkReport: (petId: number, weekOffset = 0) => request<WalkReport>(`/walks/report?pet_id=${petId}&week_offset=${weekOffset}`),

  submitFeedback: (body: FeedbackInput) => post<Feedback>('/feedback', body),
};
