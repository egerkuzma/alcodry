"""Общая обвязка тестов: журнал, к которому состояние пересчитывается пошагово."""

from __future__ import annotations

from datetime import date, timedelta

from app import logic

D0 = date(2026, 1, 1)


def d(n: int) -> date:
    """Дата через n дней после старта журнала."""
    return D0 + timedelta(days=n)


class Journal:
    """Журнал событий и состояние, полученное их пошаговым применением.

    Ровно то, что делает `db.py`, но без sqlite: тесты проверяют логику.
    """

    def __init__(self, start: date = D0):
        self.events = list(logic.start_journal(start))
        self.state = logic.apply_all(None, self.events)

    def do(self, action, today: date, note: str | None = None) -> logic.State:
        return self._add(action(self.state, today, note))

    def read(self, today: date) -> logic.State:
        """Обращение к состоянию — здесь срабатывает автовыход из окна."""
        return self._add(logic.catch_up(self.state, today))

    def close_stage(self, note: str | None = None) -> date:
        """Закрыть текущий этап ровно в срок и тут же начать следующий,
        не отгуливая окно. Возвращает день закрытия."""
        day = self.state.end_date
        self.do(logic.stage_done, day, note)
        self.do(logic.window_end, day)
        return day

    def kinds(self) -> list[str]:
        return [e.kind for e in self.events]

    def _add(self, events: list[logic.Event]) -> logic.State:
        if events:
            self.events += events
            self.state = logic.apply_all(self.state, events)
        return self.state
