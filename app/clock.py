"""Единственное место, где приложение узнаёт текущий день.

Всё остальное принимает дату параметром — иначе логику не протестировать.
"""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

MOSCOW = ZoneInfo("Europe/Moscow")


def today() -> date:
    """Календарная дата по Москве."""
    return datetime.now(MOSCOW).date()


def now_utc_iso() -> str:
    """Момент записи события, ISO 8601 в UTC."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
