"""서비스 시각 유틸리티.

PawPath는 한 동네를 대상으로 하므로 모든 시각을 서비스 지역 기준의
타임존 없는 현지 시각(naive datetime)으로 저장하고 주고받는다.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import get_settings


def now_local() -> datetime:
    tz = ZoneInfo(get_settings().service_timezone)
    return datetime.now(tz).replace(tzinfo=None, second=0, microsecond=0)
