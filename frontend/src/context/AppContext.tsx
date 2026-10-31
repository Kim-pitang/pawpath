import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { api, setProfileRequired, setSessionRecovery } from '../lib/api';
import { clearDraft, loadDraft } from '../lib/recording';
import type { Account, AccountUser, Pet, Profile, Recommendation, Schedule, WeatherScenario } from '../lib/types';

/**
 * 이 기기에서 마지막으로 로그인한 보호자. 세션이 끝난 뒤에도 누가 다시 로그인해야 하는지 알기 위해 남긴다.
 * profile_id는 다시 로그인했을 때 쓰던 프로필로 돌아가는 데 쓴다.
 */
type RememberedAccount = Pick<AccountUser, 'id'> & { profile_id?: number | null };

export interface ExpiredSession extends RememberedAccount {
  authRequired: boolean;
  googleEnabled: boolean;
}

interface AppState {
  /** 로그인 상태. 처음 읽는 동안은 null이다. */
  account: Account | null;
  refreshAccount: () => Promise<Account>;
  signOut: () => Promise<void>;
  /** 대표 계정의 프로필. 로그인하지 않았으면 비어 있다. */
  profiles: Profile[];
  /** 이 세션에서 쓰는 프로필. 서버가 계정 소속을 확인한 값이다. */
  currentProfile: Profile | null;
  /** 다른 프로필로 바꾼다. 로그아웃하지 않고 서버가 소속을 확인한 뒤 바꾼다. 저장하지 않은 기록을 지우지 않기로 하면 null을 돌려준다. */
  switchProfile: (id: number) => Promise<Account | null>;
  /** 프로필이 바뀔 때마다 늘어난다. 화면이 이 값으로 다시 그려져 이전 프로필의 데이터가 남지 않는다. */
  profileEpoch: number;
  /** 세션이 끝나 다시 로그인을 기다리는 중이면 그 보호자. 이때는 시연 보호자로 넘어가지 않는다. */
  expired: ExpiredSession | null;
  /** 기기에 남긴 계정 정보를 지우고 로그인하지 않은 상태로 돌아간다. */
  leaveAccount: () => Promise<void>;
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
const REMEMBERED_KEY = 'pawpath.account';

function loadRemembered(): RememberedAccount | null {
  try {
    const remembered = JSON.parse(localStorage.getItem(REMEMBERED_KEY) ?? 'null') as RememberedAccount | null;
    return typeof remembered?.id === 'number' ? remembered : null;
  } catch {
    return null;
  }
}

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
  const [expired, setExpired] = useState<ExpiredSession | null>(null);
  const waitingRequests = useRef<((resume: boolean) => void)[]>([]);
  const [profileEpoch, setProfileEpoch] = useState(0);
  const lastProfileId = useRef<number | null>(null);

  const settleRequests = useCallback((resume: boolean) => {
    waitingRequests.current.splice(0).forEach((settle) => settle(resume));
  }, []);

  const refreshAccount = useCallback(async () => {
    const next = await api.authMe();
    const remembered = loadRemembered();
    if (next.user) {
      const sameUser = remembered === null || remembered.id === next.user.id;
      // 다른 사람이 이 기기에서 로그인했다면 앞사람의 저장하지 않은 기록과 멈춰 둔 요청을 넘겨주지 않는다.
      if (!sameUser) clearDraft();
      const profileId = next.current_profile?.id ?? (sameUser ? remembered?.profile_id : null) ?? null;
      const remember: RememberedAccount = { id: next.user.id, profile_id: profileId };
      localStorage.setItem(REMEMBERED_KEY, JSON.stringify(remember));
      setExpired(null);
      settleRequests(sameUser);
    } else if (remembered) {
      // 세션이 끝났다. 시연 보호자로 넘어가면 다시 저장한 경로가 공용 계정에 들어가므로, 화면을 그대로 두고 로그인을 받는다.
      setExpired({ ...remembered, authRequired: next.auth_required, googleEnabled: next.google_enabled });
      return next;
    }
    setAccount(next);
    return next;
  }, [settleRequests]);

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

  // 어느 API든 401을 받으면 다시 로그인할 때까지 그 요청을 멈춰 둔다. 저장 중이던 내용을 잃지 않고 이어서 보낸다.
  useEffect(() => {
    setSessionRecovery(
      () =>
        new Promise<boolean>((resolve) => {
          waitingRequests.current.push(resolve);
          refreshAccount()
            .then((next) => {
              // 로그인한 적이 없는 기기면 기다릴 일이 없다.
              if (!next.user && !loadRemembered()) settleRequests(false);
            })
            .catch(() => settleRequests(false));
        }),
    );
  }, [refreshAccount, settleRequests]);

  // 오래 두었다가 돌아오면 무언가 누르기 전에 세션이 끝났거나 다른 탭에서 로그아웃했는지 확인한다.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') refreshAccount().catch(() => undefined);
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [refreshAccount]);

  // 다른 기기에서 쓰던 프로필을 지웠을 때처럼 서버가 프로필을 다시 고르라고 하면, 계정을 새로 읽어 선택 화면으로 보낸다.
  useEffect(() => {
    setProfileRequired(() => void refreshAccount().catch(() => undefined));
  }, [refreshAccount]);

  // 계정이 바뀌면 그 대표 계정의 반려동물을 새로 읽는다. 반려동물은 가족 공용이라 프로필을 바꿔도 그대로다.
  const accountKey = account ? (account.user ? `user:${account.user.id}` : account.auth_required ? 'locked' : 'guest') : null;
  useEffect(() => {
    if (!accountKey) return;
    if (accountKey === 'locked') {
      setPets([]);
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
  }, [accountKey, refreshPets]);

  // 일정과 추천은 프로필마다 다르다. 프로필이 바뀌면 일정을 새로 읽고 이전 프로필의 추천 캐시를 비운다.
  const currentProfile = account?.current_profile ?? null;
  const waitingForProfile = Boolean(account?.user && account.profile_required);
  const profileKey = accountKey && accountKey !== 'locked' && !waitingForProfile ? `${accountKey}:${currentProfile?.id ?? 'guest'}` : null;
  useEffect(() => {
    setCache({});
    setSchedule(null);
    if (profileKey) api.getSchedule().then(setSchedule).catch(() => undefined);
  }, [profileKey]);

  // 이미 쓰던 프로필에서 다른 프로필로 바뀌었을 때만 화면을 다시 그린다. 처음 계정을 읽을 때는 그대로 둔다.
  useEffect(() => {
    const id = currentProfile?.id ?? null;
    if (id === null) return;
    if (lastProfileId.current !== null && lastProfileId.current !== id) setProfileEpoch((value) => value + 1);
    lastProfileId.current = id;
  }, [currentProfile?.id]);

  const switchProfile = useCallback(
    async (id: number) => {
      // 저장하지 않은 기록은 시작한 사람의 것이다. 그대로 두면 바꾼 프로필의 기록으로 저장되므로, 로그아웃할 때처럼 묻고 지운다.
      const previous = currentProfile?.id ?? loadRemembered()?.profile_id ?? null;
      const changing = previous !== null && previous !== id;
      if (changing && loadDraft() && !window.confirm('저장하지 않은 산책 기록이 있어요. 프로필을 바꾸면 이 기기에서 지워져요.')) return null;
      await api.selectProfile(id);
      if (changing) clearDraft();
      return refreshAccount();
    },
    [currentProfile?.id, refreshAccount],
  );

  const leaveAccount = useCallback(async () => {
    localStorage.removeItem(REMEMBERED_KEY);
    localStorage.removeItem(PET_KEY);
    setSelectedId(null);
    setExpired(null);
    settleRequests(false);
    await refreshAccount();
  }, [refreshAccount, settleRequests]);

  const signOut = useCallback(async () => {
    await api.logout();
    await leaveAccount();
  }, [leaveAccount]);

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
      profiles: account?.profiles ?? [],
      currentProfile,
      switchProfile,
      profileEpoch,
      expired,
      leaveAccount,
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
      currentProfile,
      switchProfile,
      profileEpoch,
      expired,
      leaveAccount,
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
