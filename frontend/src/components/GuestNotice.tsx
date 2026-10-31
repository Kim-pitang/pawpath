import { Link, useLocation } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { InfoNotice } from './ui';

/** 로그인하지 않으면 시연 보호자 계정에 저장된다는 안내. 공유 범위와 별개로 서버 사용자 모두가 같은 계정을 쓴다. */
export default function GuestNotice() {
  const { account } = useApp();
  const location = useLocation();
  if (!account || account.authenticated) return null;
  return (
    <InfoNotice>
      로그인하지 않아 시연 보호자 계정에 저장돼요. 같은 서버를 쓰는 누구나 볼 수 있으니, 내 기록만 남기려면{' '}
      <Link to="/login" state={{ from: location.pathname + location.search }} className="font-bold underline">
        로그인
      </Link>
      해 주세요.
    </InfoNotice>
  );
}
