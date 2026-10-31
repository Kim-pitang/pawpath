import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useApp } from '../context/AppContext';

/** 메뉴 없는 전체 화면(GPS 기록, 길 안내)도 누구의 산책인지 정한 뒤 쓴다. 메뉴가 있는 화면은 Layout이 같은 일을 한다. */
export default function RequireProfile({ children }: { children: ReactNode }) {
  const { account } = useApp();
  const location = useLocation();
  if (account?.authenticated && account.profile_required) return <Navigate to="/profiles" replace state={{ from: location.pathname + location.search }} />;
  return <>{children}</>;
}
