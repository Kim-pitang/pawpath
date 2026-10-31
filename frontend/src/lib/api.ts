import type {
  Account,
  AlternativeResult,
  Approach,
  Course,
  CurrentWeather,
  Feedback,
  FeedbackInput,
  ForecastWeather,
  GpxPreview,
  Insights,
  NearbyResult,
  Pet,
  PetInput,
  PublicWalk,
  Recommendation,
  RouteResult,
  SavedWalkDetail,
  SavedWalkInput,
  SavedWalkSort,
  SavedWalkSummary,
  Schedule,
  SharedWalk,
  TrackingSource,
  Visibility,
  Walk,
  WalkPhoto,
  WalkReport,
  WeatherScenario,
} from './types';

const BASE = import.meta.env.VITE_API_URL ?? '/api';
export const MAX_GPX_BYTES = 10 * 1024 * 1024;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status = 0,
  ) {
    super(message);
  }
}

/** 로그인이 필요하거나 만료되면 앱 상태가 계정 정보를 다시 읽도록 알린다. */
export const UNAUTHORIZED_EVENT = 'pawpath:unauthorized';

function failed(status: number, detail: unknown): ApiError {
  if (status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  return new ApiError(describeDetail(detail), status);
}

function describeDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return '입력한 값을 다시 확인해 주세요.';
  return '요청을 처리하지 못했어요.';
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      // 로그인 세션 쿠키를 함께 보낸다. API 주소가 다른 출처여도 동작한다.
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      ...init,
    });
  } catch {
    throw new ApiError('서버에 연결할 수 없어요. 백엔드가 실행 중인지 확인해 주세요.');
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw failed(response.status, body.detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

/** 진행률을 보여 주려고 XHR로 올린다. 파일 원본을 그대로 보내 인코딩을 서버가 판단한다. */
function uploadGpx(file: File, onProgress: (percent: number) => void): Promise<GpxPreview> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${BASE}/my-walks/import/preview`);
    xhr.withCredentials = true;
    xhr.setRequestHeader('Content-Type', 'application/gpx+xml');
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onerror = () => reject(new ApiError('서버에 연결할 수 없어요. 백엔드가 실행 중인지 확인해 주세요.'));
    xhr.onload = () => {
      let body: { detail?: unknown } = {};
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        // 본문이 JSON이 아니면 아래 기본 문구를 쓴다.
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as GpxPreview);
      else reject(failed(xhr.status, body.detail));
    };
    xhr.send(file);
  });
}

const post = <T>(path: string, body: unknown) => request<T>(path, { method: 'POST', body: JSON.stringify(body) });
const put = <T>(path: string, body: unknown) => request<T>(path, { method: 'PUT', body: JSON.stringify(body) });

export const api = {
  authMe: () => request<Account>('/auth/me'),
  signup: (body: { login_id: string; password: string; name: string }) => post<Account>('/auth/signup', body),
  login: (body: { login_id: string; password: string }) => post<Account>('/auth/login', body),
  logout: () => post<Account>('/auth/logout', {}),
  /** 페이지 이동으로 여는 주소. 서버가 Google 로그인 화면으로 보낸다. */
  googleStartUrl: (next: string) => `${BASE}/auth/google/start?next=${encodeURIComponent(next)}`,

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
  /** 피드백 전 산책만 지울 수 있다. */
  deleteWalk: (id: number) => request<void>(`/walks/${id}`, { method: 'DELETE' }),
  walkReport: (petId: number, weekOffset = 0) => request<WalkReport>(`/walks/report?pet_id=${petId}&week_offset=${weekOffset}`),

  submitFeedback: (body: FeedbackInput) => post<Feedback>('/feedback', body),

  createSavedWalk: (body: SavedWalkInput) => post<SavedWalkDetail>('/my-walks', body),
  listSavedWalks: ({ sort, petId, visibility }: { sort: SavedWalkSort; petId: number | null; visibility: Visibility | null }) =>
    request<SavedWalkSummary[]>(`/my-walks?sort=${sort}${petId ? `&pet_id=${petId}` : ''}${visibility ? `&visibility=${visibility}` : ''}`),
  getSavedWalk: (id: number) => request<SavedWalkDetail>(`/my-walks/${id}`),
  updateSavedWalk: (id: number, body: Partial<Pick<SavedWalkInput, 'title' | 'pet_id' | 'memo' | 'visibility' | 'share_memo'>>) =>
    request<SavedWalkDetail>(`/my-walks/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteSavedWalk: (id: number) => request<void>(`/my-walks/${id}`, { method: 'DELETE' }),
  savedWalkGpxUrl: (id: number) => `${BASE}/my-walks/${id}/gpx`,
  previewGpx: uploadGpx,
  shareSavedWalk: (id: number, body: { expires_in_days: number | null; share_memo: boolean }) => post<SavedWalkDetail>(`/my-walks/${id}/share`, body),
  unshareSavedWalk: (id: number) => request<SavedWalkDetail>(`/my-walks/${id}/share`, { method: 'DELETE' }),
  registerCourse: (id: number) => post<SavedWalkDetail>(`/my-walks/${id}/course`, {}),
  unregisterCourse: (id: number) => request<SavedWalkDetail>(`/my-walks/${id}/course`, { method: 'DELETE' }),
  getSharedWalk: (token: string) => request<SharedWalk>(`/shared/${encodeURIComponent(token)}`),
  sharedWalkGpxUrl: (token: string) => `${BASE}/shared/${encodeURIComponent(token)}/gpx`,
  listPublicWalks: () => request<PublicWalk[]>('/public-walks'),
  uploadPhoto: (walkId: number, photo: Blob) =>
    request<WalkPhoto>(`/my-walks/${walkId}/photos`, { method: 'POST', body: photo, headers: { 'Content-Type': photo.type || 'image/jpeg' } }),
  deletePhoto: (walkId: number, photoId: number) => request<void>(`/my-walks/${walkId}/photos/${photoId}`, { method: 'DELETE' }),
  photoUrl: (walkId: number, photoId: number) => `${BASE}/my-walks/${walkId}/photos/${photoId}`,
};
