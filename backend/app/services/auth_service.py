"""보호자 계정: 비밀번호 해시, 로그인 세션, 로그인 시도 제한. 표준 라이브러리만 쓴다."""
import base64
import hashlib
import hmac
import math
import secrets
import threading
import time
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AuthSession, User
from app.seed import new_user_defaults

SESSION_COOKIE = "pawpath_session"
SESSION_DAYS = 30
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


def login(db: Session, login_id: str, password: str, clock: float | None = None) -> User:
    now = time.monotonic() if clock is None else clock
    wait = throttle.seconds_locked(login_id, now)
    if wait:
        raise AuthError(429, f"로그인 시도가 너무 많아요. {math.ceil(wait / 60)}분 뒤에 다시 시도해 주세요.")
    user = db.scalar(select(User).where(User.login_id == login_id))
    stored = user.password_hash if user is not None and user.password_hash else None
    matched = verify_password(password, stored or _DUMMY_HASH)
    if stored is None or not matched:
        throttle.fail(login_id, now)
        raise AuthError(401, "아이디나 비밀번호가 맞지 않아요.")
    throttle.clear(login_id)
    return user


def create_session(db: Session, user: User, now: datetime) -> str:
    token = secrets.token_urlsafe(32)
    db.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
    db.add(AuthSession(user_id=user.id, token_hash=_token_hash(token), created_at=now, expires_at=now + timedelta(days=SESSION_DAYS)))
    db.commit()
    return token


def user_for_token(db: Session, token: str, now: datetime) -> User | None:
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
    if session is None or session.expires_at <= now:
        return None
    return db.get(User, session.user_id)


def end_session(db: Session, token: str) -> None:
    db.execute(delete(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
    db.commit()


EXPIRED_COOKIE = f"{SESSION_COOKIE}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax"
