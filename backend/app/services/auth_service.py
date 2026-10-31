"""보호자 로그인 세션. 로그인은 Google로만 하고(google_auth_service), 여기서는 세션을 열고 확인하고 닫는다."""
import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.models import AuthSession, User

SESSION_COOKIE = "pawpath_session"
# 로그인한 지 이 기간이 지나면 계속 쓰고 있어도 끝난다.
SESSION_DAYS = 30
# 이 기간 동안 요청이 없으면 끝난다.
SESSION_IDLE_DAYS = 7
# 요청마다 DB에 쓰지 않도록 마지막 사용 시각은 이 간격으로만 갱신한다.
TOUCH_MINUTES = 5
# 본인을 다시 확인한 뒤 되돌릴 수 없는 작업을 할 수 있는 시간.
REAUTH_MINUTES = 10


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User, now: datetime, profile_id: int | None = None) -> str:
    """profile_id는 로그인하자마자 쓸 프로필이다. 비우면 화면에서 프로필을 고른다."""
    token = secrets.token_urlsafe(32)
    idle_limit = now - timedelta(days=SESSION_IDLE_DAYS)
    db.execute(delete(AuthSession).where(or_(AuthSession.expires_at <= now, func.coalesce(AuthSession.last_seen_at, AuthSession.created_at) <= idle_limit)))
    db.add(AuthSession(user_id=user.id, token_hash=_token_hash(token), created_at=now, expires_at=now + timedelta(days=SESSION_DAYS), last_seen_at=now, profile_id=profile_id))
    db.commit()
    return token


def find_session(db: Session, token: str, now: datetime) -> AuthSession | None:
    """쓸 수 있는 세션을 돌려주고 마지막 사용 시각을 갱신한다. 끝난 세션은 지운다.

    화면은 같은 쿠키로 요청을 동시에 보내므로, 다른 요청이 먼저 지웠어도 오류가 나지 않는 구문으로 쓴다.
    """
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
    if session is None:
        return None
    last_seen = session.last_seen_at or session.created_at
    if session.expires_at <= now or last_seen + timedelta(days=SESSION_IDLE_DAYS) <= now:
        db.execute(delete(AuthSession).where(AuthSession.id == session.id))
        db.commit()
        return None
    if now - last_seen >= timedelta(minutes=TOUCH_MINUTES):
        db.execute(update(AuthSession).where(AuthSession.id == session.id).values(last_seen_at=now))
        db.commit()
    return session


def user_for_token(db: Session, token: str, now: datetime) -> User | None:
    session = find_session(db, token, now)
    return db.get(User, session.user_id) if session else None


def needs_reauth(session: AuthSession, now: datetime) -> bool:
    return (session.reauthenticated_at or session.created_at) + timedelta(minutes=REAUTH_MINUTES) <= now


def reauthenticate(db: Session, session: AuthSession, now: datetime) -> str:
    """본인 확인을 기록하고 토큰을 바꾼다. 쿠키를 훔친 사람은 주인이 확인한 권한을 함께 얻지 못한다."""
    token = secrets.token_urlsafe(32)
    session.token_hash = _token_hash(token)
    session.reauthenticated_at = now
    db.commit()
    return token


def end_session(db: Session, token: str) -> None:
    db.execute(delete(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
    db.commit()


EXPIRED_COOKIE = f"{SESSION_COOKIE}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax"
