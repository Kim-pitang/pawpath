"""보호자 계정: 비밀번호 해시, 로그인 세션, 로그인 시도 제한. 표준 라이브러리만 쓴다."""
import base64
import hashlib
import hmac
import math
import secrets
import threading
import time
from datetime import datetime, timedelta

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AuthSession, User
from app.seed import new_user_defaults

SESSION_COOKIE = "pawpath_session"
# 로그인한 지 이 기간이 지나면 계속 쓰고 있어도 끝난다.
SESSION_DAYS = 30
# 이 기간 동안 요청이 없으면 끝난다.
SESSION_IDLE_DAYS = 7
# 요청마다 DB에 쓰지 않도록 마지막 사용 시각은 이 간격으로만 갱신한다.
TOUCH_MINUTES = 5
# 본인을 다시 확인한 뒤 되돌릴 수 없는 작업을 할 수 있는 시간.
REAUTH_MINUTES = 10
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
MAX_FAILURES = 5
LOCK_SECONDS = 600


class AuthError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        expected = _unb64(digest)
        actual = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return scheme == "scrypt" and hmac.compare_digest(actual, expected)


# 없는 아이디도 같은 시간이 걸리게 해 아이디가 있는지 응답 시간으로 알 수 없게 한다.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


class LoginThrottle:
    """아이디별로 연달아 틀린 횟수를 센다. 서버 메모리에 두므로 재시작하면 초기화된다."""

    def __init__(self) -> None:
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def seconds_locked(self, login_id: str, now: float) -> float:
        with self._lock:
            recent = [t for t in self._failures.get(login_id, []) if now - t < LOCK_SECONDS]
            self._failures[login_id] = recent
            return LOCK_SECONDS - (now - recent[0]) if len(recent) >= MAX_FAILURES else 0.0

    def fail(self, login_id: str, now: float) -> None:
        with self._lock:
            self._failures.setdefault(login_id, []).append(now)

    def clear(self, login_id: str | None = None) -> None:
        with self._lock:
            if login_id is None:
                self._failures.clear()
            else:
                self._failures.pop(login_id, None)


throttle = LoginThrottle()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def signup(db: Session, login_id: str, password: str, name: str) -> User:
    if db.scalar(select(User.id).where(User.login_id == login_id)) is not None:
        raise AuthError(409, "이미 사용 중인 아이디예요.")
    user = User(name=name, login_id=login_id, password_hash=hash_password(password), **new_user_defaults())
    db.add(user)
    try:
        db.commit()
    except IntegrityError as error:
        # 같은 아이디로 동시에 가입한 경우다.
        db.rollback()
        raise AuthError(409, "이미 사용 중인 아이디예요.") from error
    return user


def _check_password(throttle_key: str, stored: str | None, password: str, failure: AuthError, clock: float | None) -> None:
    now = time.monotonic() if clock is None else clock
    wait = throttle.seconds_locked(throttle_key, now)
    if wait:
        raise AuthError(429, f"로그인 시도가 너무 많아요. {math.ceil(wait / 60)}분 뒤에 다시 시도해 주세요.")
    matched = verify_password(password, stored or _DUMMY_HASH)
    if stored is None or not matched:
        throttle.fail(throttle_key, now)
        raise failure
    throttle.clear(throttle_key)


def login(db: Session, login_id: str, password: str, clock: float | None = None) -> User:
    user = db.scalar(select(User).where(User.login_id == login_id))
    stored = user.password_hash if user is not None and user.password_hash else None
    _check_password(login_id, stored, password, AuthError(401, "아이디나 비밀번호가 맞지 않아요."), clock)
    return user


def create_session(db: Session, user: User, now: datetime) -> str:
    token = secrets.token_urlsafe(32)
    idle_limit = now - timedelta(days=SESSION_IDLE_DAYS)
    db.execute(delete(AuthSession).where(or_(AuthSession.expires_at <= now, func.coalesce(AuthSession.last_seen_at, AuthSession.created_at) <= idle_limit)))
    db.add(AuthSession(user_id=user.id, token_hash=_token_hash(token), created_at=now, expires_at=now + timedelta(days=SESSION_DAYS), last_seen_at=now))
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


def confirm_password(user: User, password: str, clock: float | None = None) -> None:
    """로그인 중인 보호자의 비밀번호를 다시 확인한다.

    로그인과 따로 세어, 세션을 훔친 사람이 일부러 틀려서 주인의 로그인까지 막지 못하게 한다.
    """
    if not user.password_hash:
        raise AuthError(409, "Google 계정은 Google로 본인을 확인해 주세요.")
    _check_password(f"reauth:{user.id}", user.password_hash, password, AuthError(403, "비밀번호가 맞지 않아요."), clock)


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
