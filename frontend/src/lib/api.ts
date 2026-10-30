import type {
  Course,
  CurrentWeather,
  Feedback,
  FeedbackInput,
  ForecastWeather,
  Insights,
  Pet,
  PetInput,
  Recommendation,
  Schedule,
  Walk,
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

  recommend: (petId: number, scenario: WeatherScenario) =>
    post<Recommendation>('/recommendations', { pet_id: petId, weather_scenario: scenario }),
  latestRecommendations: (petId: number, limit = 1) =>
    request<Recommendation[]>(`/recommendations?pet_id=${petId}&limit=${limit}`),

  createWalk: (body: { pet_id: number; course_id: number; recommendation_id: number | null; duration_min: number }) =>
    post<Walk>('/walks', body),
  listWalks: (petId: number) => request<Walk[]>(`/walks?pet_id=${petId}`),

  submitFeedback: (body: FeedbackInput) => post<Feedback>('/feedback', body),
};
