"""Чистая логика переходов.

Ни sqlite, ни FastAPI, ни обращений к системным часам: всё, что зависит от
текущего дня, приходит параметром `today`. Состояние неизменяемо и целиком
выводится из журнала событий — `rebuild_state_from_events()`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Sequence

from . import ru

STAGE_WINDOW_DAYS = 3  # окно после обычного этапа
CYCLE_WINDOW_DAYS = 3  # окно после завершения всего цикла

MODE_STAGE = "stage"
MODE_WINDOW = "window"

EVENT_KINDS = (
    "stage_start",
    "relapse",
    "stage_done",
    "cycle_done",
    "window_end",
    "window_drink",
)


def stages_for_cycle(cycle_no: int) -> list[int]:
    """Длины этапов в неделях для указанного цикла."""
    return [1, 2, 3, 3, 4]


def max_stage_weeks(cycle_no: int) -> int:
    """Потолок длины этапа — самая длинная ступень лестницы."""
    return max(stages_for_cycle(cycle_no))


class TransitionError(Exception):
    """Действие недопустимо в текущем состоянии. Наверху становится 409."""


@dataclass(frozen=True)
class State:
    mode: str
    stage_index: int
    penalty_weeks: int
    start_date: date
    window_ends_on: date | None
    cycle_no: int

    @property
    def stages(self) -> list[int]:
        return stages_for_cycle(self.cycle_no)

    @property
    def stages_in_cycle(self) -> int:
        return len(self.stages)

    @property
    def base_weeks(self) -> int:
        """База текущего этапа; в режиме `window` — база следующего."""
        return self.stages[self.stage_index]

    @property
    def stage_weeks(self) -> int:
        return min(self.base_weeks + self.penalty_weeks, max_stage_weeks(self.cycle_no))

    @property
    def end_date(self) -> date:
        return self.start_date + timedelta(days=self.stage_weeks * 7)

    def days_passed(self, today: date) -> int:
        return (today - self.start_date).days

    def days_left(self, today: date) -> int:
        return max(0, (self.end_date - today).days)

    def can_close(self, today: date) -> bool:
        return self.mode == MODE_STAGE and today >= self.end_date

    def window_days_left(self, today: date) -> int:
        if self.mode != MODE_WINDOW or self.window_ends_on is None:
            return 0
        return max(0, (self.window_ends_on - today).days + 1)


@dataclass(frozen=True)
class Event:
    kind: str
    local_date: date
    stage_index: int
    penalty_weeks: int
    cycle_no: int
    auto: bool = False
    note: str | None = None
    id: int | None = None
    ts: str | None = None


def _event(state: State, kind: str, local_date: date, *, auto: bool = False,
           note: str | None = None) -> Event:
    """Событие с отпечатком состояния на момент до перехода."""
    return Event(
        kind=kind,
        local_date=local_date,
        stage_index=state.stage_index,
        penalty_weeks=state.penalty_weeks,
        cycle_no=state.cycle_no,
        auto=auto,
        note=note,
    )


# --- воспроизведение журнала ------------------------------------------------

def apply_event(state: State | None, event: Event) -> State:
    """Применить одно событие. Без проверок: журнал считается достоверным,
    проверки живут в действиях ниже."""
    if state is None:
        if event.kind != "stage_start":
            raise ValueError(f"журнал начинается не со stage_start, а с {event.kind}")
        return State(
            mode=MODE_STAGE,
            stage_index=event.stage_index,
            penalty_weeks=event.penalty_weeks,
            start_date=event.local_date,
            window_ends_on=None,
            cycle_no=event.cycle_no,
        )

    if event.kind == "stage_start":
        return replace(state, mode=MODE_STAGE, start_date=event.local_date,
                       window_ends_on=None)

    if event.kind == "relapse":
        return replace(state, mode=MODE_STAGE, penalty_weeks=state.penalty_weeks + 1,
                       start_date=event.local_date, window_ends_on=None)

    if event.kind == "stage_done":
        return replace(state, mode=MODE_WINDOW, penalty_weeks=0,
                       stage_index=state.stage_index + 1,
                       window_ends_on=event.local_date + timedelta(days=STAGE_WINDOW_DAYS - 1))

    if event.kind == "cycle_done":
        # Пишется сразу вслед за stage_done последнего этапа и перекрывает окно.
        return replace(state, mode=MODE_WINDOW, stage_index=0,
                       cycle_no=state.cycle_no + 1,
                       window_ends_on=event.local_date + timedelta(days=CYCLE_WINDOW_DAYS - 1))

    if event.kind == "window_end":
        return replace(state, mode=MODE_STAGE, start_date=event.local_date,
                       window_ends_on=None)

    if event.kind == "window_drink":
        return state

    raise ValueError(f"неизвестный вид события: {event.kind}")


def rebuild_state_from_events(events: Sequence[Event]) -> State | None:
    """Состояние целиком из журнала. Пустой журнал — состояния ещё нет."""
    state: State | None = None
    for event in events:
        state = apply_event(state, event)
    return state


def apply_all(state: State | None, events: Sequence[Event]) -> State:
    for event in events:
        state = apply_event(state, event)
    assert state is not None
    return state


# --- действия ---------------------------------------------------------------
# Каждое возвращает список событий, а не новое состояние: состояние всегда
# получается проигрыванием журнала, и разойтись им негде.

def start_journal(today: date, cycle_no: int = 1) -> list[Event]:
    """Первое событие журнала."""
    return [Event(kind="stage_start", local_date=today, stage_index=0,
                  penalty_weeks=0, cycle_no=cycle_no, auto=True)]


def relapse(state: State, today: date, note: str | None = None) -> list[Event]:
    if state.mode != MODE_STAGE:
        raise TransitionError("Идёт окно — срыв отмечать нечем, алкоголь разрешён")
    return [_event(state, "relapse", today, note=note)]


def stage_done(state: State, today: date, note: str | None = None) -> list[Event]:
    if state.mode != MODE_STAGE:
        raise TransitionError("Этап уже закрыт, идёт окно")
    if today < state.end_date:
        raise TransitionError(
            f"Этап идёт до {ru.ru_date(state.end_date)}, "
            f"осталось {ru.days(state.days_left(today))}"
        )
    events: list[Event] = [_event(state, "stage_done", today, note=note)]
    if state.stage_index + 1 == state.stages_in_cycle:
        # Спутник закрытия этапа, а не отдельное действие: auto=1, чтобы отмена
        # снесла оба разом. Иначе останется stage_done с индексом вне лестницы.
        events.append(_event(state, "cycle_done", today, auto=True))
    return events


def window_end(state: State, today: date, note: str | None = None) -> list[Event]:
    if state.mode != MODE_WINDOW:
        raise TransitionError("Окна сейчас нет, этап уже идёт")
    return [_event(state, "window_end", today, note=note)]


def window_drink(state: State, today: date, note: str | None = None) -> list[Event]:
    if state.mode != MODE_WINDOW:
        raise TransitionError("Идёт этап — выпивка здесь считается срывом")
    return [_event(state, "window_drink", today, note=note)]


def catch_up(state: State, today: date) -> list[Event]:
    """Автоматический выход из окна. Дата — `window_ends_on + 1`, а не «сегодня»:
    журнал получается такой же, как если бы приложение работало непрерывно."""
    if state.mode == MODE_WINDOW and state.window_ends_on is not None \
            and today > state.window_ends_on:
        return [_event(state, "stage_start", state.window_ends_on + timedelta(days=1),
                       auto=True)]
    return []


# --- статистика -------------------------------------------------------------

@dataclass(frozen=True)
class Stats:
    sober_days: int          # дни этапа без срыва — только они
    longest_streak: int      # окно рвёт серию, даже если в нём не пил
    window_days: int
    cycles_done: int
    relapses: int
    windows_closed: int
    windows_dry: int         # окна, в которых не было ни одной выпивки


def compute_stats(events: Sequence[Event], today: date) -> Stats:
    if not events:
        return Stats(0, 0, 0, 0, 0, 0, 0)

    relapse_days = {e.local_date for e in events if e.kind == "relapse"}

    sober = window_days = streak = longest = 0
    state: State | None = None
    i = 0
    day = events[0].local_date
    while day <= today:
        while i < len(events) and events[i].local_date <= day:
            state = apply_event(state, events[i])
            i += 1
        assert state is not None
        if state.mode == MODE_STAGE and day not in relapse_days:
            sober += 1
            streak += 1
            longest = max(longest, streak)
        else:
            streak = 0
            if state.mode == MODE_WINDOW:
                window_days += 1
        day += timedelta(days=1)

    windows_closed = windows_dry = 0
    in_window = False
    dry = True
    for event in events:
        if event.kind == "stage_done":
            in_window, dry = True, True
        elif event.kind == "window_drink":
            dry = False
        elif event.kind in ("window_end", "stage_start") and in_window:
            windows_closed += 1
            windows_dry += int(dry)
            in_window = False

    return Stats(
        sober_days=sober,
        longest_streak=longest,
        window_days=window_days,
        cycles_done=sum(1 for e in events if e.kind == "cycle_done"),
        relapses=sum(1 for e in events if e.kind == "relapse"),
        windows_closed=windows_closed,
        windows_dry=windows_dry,
    )
