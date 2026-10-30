import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { api } from '../lib/api';
import type { Pet, Recommendation, Schedule, WeatherScenario } from '../lib/types';

interface AppState {
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

  const refreshPets = useCallback(async () => {
    const list = await api.listPets();
    setPets(list);
    setPetsLoaded(true);
    setLoadError(null);
    return list;
  }, []);

  useEffect(() => {
    refreshPets().catch((error: Error) => {
      setLoadError(error.message);
      setPetsLoaded(true);
    });
    api.getSchedule().then(setSchedule).catch(() => undefined);
  }, [refreshPets]);

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

  const value = useMemo<AppState>(
    () => ({
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
    }),
    [
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
    ],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppState {
  const context = useContext(AppContext);
  if (!context) throw new Error('useApp은 AppProvider 안에서만 쓸 수 있습니다');
  return context;
}
