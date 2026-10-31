"""Google OAuth 2.0 로그인. OpenID Connect의 승인 코드 흐름에 PKCE, state, nonce를 붙인다.

ID 토큰은 서버가 클라이언트 비밀값으로 Google 토큰 엔드포인트에서 HTTPS로 직접 받는다. Google 문서는
이 경우 서명을 검증하지 않아도 된다고 안내하므로(OpenID Connect 문서의 "Obtain user information from
the ID token"), 암호 라이브러리 없이 발급자, 대상, 만료, nonce를 확인한다. 브라우저에서 받은 ID 토큰은 쓰지 않는다.
"""
import base64
import binascii
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import quote, urlencode

import httpx
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import OAuthState, User
from app.seed import new_user_defaults
from app.services.profile_service import new_default_profile

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = {"https://accounts.google.com", "accounts.google.com"}
STATE_COOKIE = "pawpath_google_state"
STATE_COOKIE_PATH = "/api/auth/google"
STATE_MINUTES = 10
# 처음 로그인한 계정은 대표 프로필의 이름과 아바타를 정한 뒤 원래 가려던 곳으로 간다.
PROFILE_SETUP_PATH = "/profiles/setup"
# 본인 재확인의 state 앞에 붙인다. 이미 쓴 state로 돌아와도 오류를 어느 화면에 알릴지 알 수 있다. 권한 판단에는 쓰지 않는다.
REAUTH_STATE_PREFIX = "reauth."
TIMEOUT_SECONDS = 10.0
# 테스트에서 가짜 Google 서버로 바꿔 끼운다.
TRANSPORT: httpx.BaseTransport | None = None


class GoogleAuthError(Exception):
    """화면에는 reason만 알리고, detail은 서버 로그에만 남긴다. 승인 코드와 토큰은 담지 않는다."""

    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass
class PendingLogin:
    nonce: str
    code_verifier: str
    next_path: str
    reauth_user_id: int | None = None


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def safe_next(path: str | None) -> str:
    """로그인 뒤 돌아갈 앱 안의 경로만 받는다. 다른 사이트로 보내는 주소는 홈으로 바꾼다."""
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path or any(ord(char) < 32 for char in path):
        return "/"
    return path[:300]


def begin(db: Session, settings: Settings, next_path: str, now: datetime, reauth_user_id: int | None = None) -> tuple[str, str]:
    """state를 저장하고 Google 로그인 주소를 돌려준다. state는 브라우저 쿠키로도 보내 시작한 브라우저와 묶는다.

    reauth_user_id를 주면 로그인이 아니라 그 보호자의 본인 재확인이다. Google 문서의 prompt 값은 none, consent,
    select_account뿐이라 비밀번호를 다시 묻게 강제할 수 없다. 계정을 고르게 하고 같은 계정인지 서버에서 확인한다.
    """
    state = (REAUTH_STATE_PREFIX if reauth_user_id is not None else "") + secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    db.execute(delete(OAuthState).where(OAuthState.expires_at <= now))
    db.add(OAuthState(state_hash=_hash(state), nonce=nonce, code_verifier=verifier, next_path=next_path, expires_at=now + timedelta(minutes=STATE_MINUTES), reauth_user_id=reauth_user_id))
    db.commit()
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()),
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    return state, f"{AUTH_URL}?{query}"


def _take_state(db: Session, state: str | None, cookie_state: str | None, now: datetime) -> PendingLogin:
    """state를 한 번만 쓰고 지운다. 다른 브라우저에서 시작한 요청(로그인 CSRF)은 쿠키가 달라 막힌다."""
    if not state or not cookie_state or not secrets.compare_digest(state, cookie_state):
        raise GoogleAuthError("google_state", "state가 없거나 브라우저 쿠키와 다름")
    row = db.scalar(select(OAuthState).where(OAuthState.state_hash == _hash(state)))
    if row is None:
        raise GoogleAuthError("google_state", "이미 쓰였거나 없는 state")
    pending = PendingLogin(row.nonce, row.code_verifier, row.next_path, row.reauth_user_id)
    expired = row.expires_at <= now
    db.delete(row)
    db.commit()
    if expired:
        raise GoogleAuthError("google_state", "만료된 state")
    return pending


def _exchange(settings: Settings, code: str, verifier: str) -> dict:
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": settings.google_redirect_uri,
        "code_verifier": verifier,
    }
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, transport=TRANSPORT) as client:
            response = client.post(TOKEN_URL, data=form, headers={"Accept": "application/json"})
    except httpx.HTTPError as error:
        raise GoogleAuthError("google_failed", f"토큰 요청 실패: {type(error).__name__}") from error
    try:
        body = response.json()
    except ValueError as error:
        raise GoogleAuthError("google_failed", f"토큰 응답 {response.status_code}: JSON 아님") from error
    if response.status_code != 200 or not isinstance(body, dict):
        error_code = body.get("error") if isinstance(body, dict) else None
        raise GoogleAuthError("google_failed", f"토큰 응답 {response.status_code}: {error_code}")
    return body


def _claims(id_token: object, settings: Settings, nonce: str, now_epoch: float) -> dict:
    if not isinstance(id_token, str) or id_token.count(".") != 2:
        raise GoogleAuthError("google_failed", "ID 토큰 형식 오류")
    payload = id_token.split(".")[1]
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (ValueError, binascii.Error) as error:
        raise GoogleAuthError("google_failed", "ID 토큰을 읽을 수 없음") from error
    if not isinstance(claims, dict):
        raise GoogleAuthError("google_failed", "ID 토큰 내용 오류")
    if claims.get("iss") not in ISSUERS:
        raise GoogleAuthError("google_failed", "발급자가 Google이 아님")
    audience = claims.get("aud")
    if audience != settings.google_client_id and not (isinstance(audience, list) and settings.google_client_id in audience):
        raise GoogleAuthError("google_failed", "다른 앱에 발급된 토큰")
    expires = claims.get("exp")
    if not isinstance(expires, (int, float)) or expires <= now_epoch:
        raise GoogleAuthError("google_failed", "만료된 토큰")
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise GoogleAuthError("google_failed", "nonce가 다름")
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject or len(subject) > 64:
        raise GoogleAuthError("google_failed", "사용자 ID 없음")
    return claims


def _display_name(claims: dict) -> str:
    name = str(claims.get("name") or "").strip() or str(claims.get("email") or "").split("@")[0].strip()
    return (name or "Google 사용자")[:30]


def complete(db: Session, settings: Settings, code: str | None, state: str | None, cookie_state: str | None, now: datetime, clock: float | None = None) -> tuple[User, str, bool]:
    """콜백을 처리해 보호자, 돌아갈 경로, 본인 재확인 여부를 돌려준다. 같은 Google 계정은 늘 같은 보호자가 된다."""
    pending = _take_state(db, state, cookie_state, now)
    if not code:
        raise GoogleAuthError("google_failed", "승인 코드 없음")
    tokens = _exchange(settings, code, pending.code_verifier)
    claims = _claims(tokens.get("id_token"), settings, pending.nonce, time.time() if clock is None else clock)
    if pending.reauth_user_id is not None:
        # 본인 재확인에서는 보호자를 새로 만들지 않는다.
        user = db.get(User, pending.reauth_user_id)
        if user is None or user.google_sub != claims["sub"]:
            raise GoogleAuthError("google_mismatch", "본인 재확인에 다른 Google 계정을 고름")
        return user, pending.next_path, True
    email = claims.get("email") if claims.get("email_verified") is True and isinstance(claims.get("email"), str) else None
    email = email[:254] if email else None
    user = db.scalar(select(User).where(User.google_sub == claims["sub"]))
    next_path = pending.next_path
    if user is None:
        user = User(name=_display_name(claims), google_sub=claims["sub"], google_email=email, **new_user_defaults())
        new_default_profile(user)
        db.add(user)
        next_path = f"{PROFILE_SETUP_PATH}?next={quote(pending.next_path, safe='')}"
    elif email:
        user.google_email = email
    try:
        db.commit()
    except IntegrityError:
        # 같은 Google 계정으로 동시에 처음 로그인한 경우다.
        db.rollback()
        next_path = pending.next_path
        user = db.scalar(select(User).where(User.google_sub == claims["sub"]))
        if user is None:
            raise
    return user, next_path, False
