import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { api, UNAUTHORIZED_EVENT } from '../lib/api';
import type { Account, Pet, Recommendation, Schedule, WeatherScenario } from '../lib/types';

interface AppState {
  /** 로그인 상태. 처음 읽는 동안은 null이다. */
  account: Account | null;
  refreshAccount: () => Promise<Account>;
  signOut: () => Promise<void>;
  /** 세션이 만료되었을 때처럼 화면 위에 알릴 계정 안내. */
  authNotice: string | null;
  clearAuthNotice: () => void;
  pets: Pet[];
  petsLoaded: boolean;
  loadError: string | null;
  selectedPet: Pet | null;
  selectPet: (id: number) => void;
  refreshPets: () => Promise<Pet[]>;
  schedule: Schedule | null;
  setSchedule: (schedule: Schedule) => void;
  scenario: WeatherScenario;
  setScenario: (scenario: WeatherScenario) => void;
  /** 현재 반려동물과 날씨 조건의 추천을 돌려준다. 캐시가 없으면 새로 계산한다. */
  loadRecommendation: (options?: { force?: boolean }) => Promise<Recommendation | null>;
  cachedRecommendation: Recommendation | null;
  /** 프로필, 일정, 피드백이 바뀌면 호출해 다음 조회 때 다시 계산하게 한다. */
  invalidateRecommendations: () => void;
  /** LLM 문장처럼 나중에 보강된 추천으로 캐시를 바꾼다. */
  replaceRecommendation: (recommendation: Recommendation) => void;
}

const AppContext = createContext<AppState | null>(null);
const PET_KEY = 'pawpath.selectedPetId';
const SCENARIO_KEY = 'pawpath.scenario';

export function AppProvider({ children }: { children: ReactNode }) {
  const [pets, setPets] = useState<Pet[]>([]);
  const [petsLoaded, setPetsLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(() => Number(localStorage.getItem(PET_KEY)) || null);
  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [scenario, setScenarioState] = useState<WeatherScenario>(
    () => (localStorage.getItem(SCENARIO_KEY) as WeatherScenario) || 'live',
  );
  const [cache, setCache] = useState<Record<string, Recommendation>>({});
  const inFlight = useRef<Record<string, Promise<Recommendation>>>({});
  const [account, setAccount] = useState<Account | null>(null);
  const accountRef = useRef<Account | null>(null);
  const [authNotice, setAuthNotice] = useState<string | null>(null);

  const refreshAccount = useCallback(async () => {
    const next = await api.authMe();
    accountRef.current = next;
    setAccount(next);
    return next;
  }, []);

  const refreshPets = useCallback(async () => {
    const list = await api.listPets();
    setPets(list);
    setPetsLoaded(true);
    setLoadError(null);
    return list;
  }, []);

  useEffect(() => {
    refreshAccount().catch((error: Error) => {
      setLoadError(error.message);
      setPetsLoaded(true);
    });
  }, [refreshAccount]);

  // 어느 API든 401을 받으면 계정 상태를 다시 읽는다. 로그인해 있었다면 만료를 알린다.
  useEffect(() => {
    const onUnauthorized = () => {
      const wasSignedIn = accountRef.current?.authenticated ?? false;
      refreshAccount()
        .then((next) => {
          if (wasSignedIn && !next.authenticated) setAuthNotice('로그인이 만료되었어요. 다시 로그인해 주세요.');
        })
        .catch(() => undefined);
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [refreshAccount]);

  // 계정이 바뀌면 그 보호자의 반려동물과 일정을 새로 읽고, 다른 계정의 추천 캐시를 비운다.
  const accountKey = account ? (account.user ? `user:${account.user.id}` : account.auth_required ? 'locked' : 'guest') : null;
  useEffect(() => {
    if (!accountKey) return;
    setCache({});
    if (accountKey === 'locked') {
      setPets([]);
      setSchedule(null);
      setPetsLoaded(true);
      return;
    }
    // 이전 계정의 반려동물로 새 계정의 API를 부르지 않도록 목록을 먼저 비운다.
    setPets([]);
    setPetsLoaded(false);
    refreshPets().catch((error: Error) => {
      setLoadError(error.message);
      setPetsLoaded(true);
    });
    api.getSchedule().then(setSchedule).catch(() => undefined);
  }, [accountKey, refreshPets]);

  const signOut = useCallback(async () => {
    await api.logout();
    setAuthNotice(null);
    await refreshAccount();
  }, [refreshAccount]);
  const clearAuthNotice = useCallback(() => setAuthNotice(null), []);

  const selectedPet = useMemo(
    () => pets.find((pet) => pet.id === selectedId) ?? pets[0] ?? null,
    [pets, selectedId],
  );

  const selectPet = useCallback((id: number) => {
    setSelectedId(id);
    localStorage.setItem(PET_KEY, String(id));
  }, []);

  const setScenario = useCallback((next: WeatherScenario) => {
    setScenarioState(next);
    localStorage.setItem(SCENARIO_KEY, next);
  }, []);

  const cacheKey = selectedPet ? `${selectedPet.id}:${scenario}` : null;
  const cachedRecommendation = cacheKey ? (cache[cacheKey] ?? null) : null;

  const loadRecommendation = useCallback(
    async ({ force = false }: { force?: boolean } = {}) => {
      if (!selectedPet || !cacheKey) return null;
      if (!force && cache[cacheKey]) return cache[cacheKey];
      // StrictMode의 이중 실행과 빠른 재진입에도 추천을 한 번만 계산한다.
      const pending = inFlight.current[cacheKey] ?? api.recommend(selectedPet.id, scenario);
      inFlight.current[cacheKey] = pending;
      try {
        const result = await pending;
        setCache((previous) => ({ ...previous, [cacheKey]: result }));
        return result;
      } finally {
        delete inFlight.current[cacheKey];
      }
    },
    [cache, cacheKey, scenario, selectedPet],
  );

  const invalidateRecommendations = useCallback(() => setCache({}), []);
  const replaceRecommendation = useCallback((recommendation: Recommendation) => {
    setCache((previous) => {
      const key = `${recommendation.pet_id}:${recommendation.weather.scenario}`;
      // 그사이 새 추천을 받았다면 오래된 결과로 덮어쓰지 않는다.
      return previous[key]?.id === recommendation.id ? { ...previous, [key]: recommendation } : previous;
    });
  }, []);

  const value = useMemo<AppState>(
    () => ({
      account,
      refreshAccount,
      signOut,
      authNotice,
      clearAuthNotice,
      pets,
      petsLoaded,
      loadError,
      selectedPet,
      selectPet,
      refreshPets,
      schedule,
      setSchedule,
      scenario,
      setScenario,
      loadRecommendation,
      cachedRecommendation,
      invalidateRecommendations,
      replaceRecommendation,
    }),
    [
      account,
      refreshAccount,
      signOut,
      authNotice,
      clearAuthNotice,
      pets,
      petsLoaded,
      loadError,
      selectedPet,
      selectPet,
      refreshPets,
      schedule,
      scenario,
      setScenario,
      loadRecommendation,
      cachedRecommendation,
      invalidateRecommendations,
      replaceRecommendation,
    ],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppState {
  const context = useContext(AppContext);
  if (!context) throw new Error('useApp은 AppProvider 안에서만 쓸 수 있습니다');
  return context;
}
