"""Статистика экрана истории. В разделе 6 её нет, но определения тонкие:
трезвый день считается по восстановленному режиму, а не по наличию событий.
"""

from __future__ import annotations

from datetime import timedelta

from app import logic
from helpers import D0, Journal, d

ONE_DAY = timedelta(days=1)


def stats(j: Journal, today):
    return logic.compute_stats(j.events, today)


def test_stage_days_are_sober_days():
    j = Journal()
    s = stats(j, d(6))
    assert s.sober_days == 7                  # d(0)..d(6)
    assert s.longest_streak == 7
    assert s.window_days == 0


def test_relapse_day_is_not_sober():
    j = Journal()
    j.do(logic.relapse, d(2))
    s = stats(j, d(4))
    assert s.sober_days == 4                  # d(0), d(1), d(3), d(4)
    assert s.longest_streak == 2
    assert s.relapses == 1


def test_silence_after_a_relapse_does_not_invent_events():
    """Пользователь отметил срыв и не заходил неделю: дни восстанавливаются
    как дни идущего этапа."""
    j = Journal()
    j.do(logic.relapse, d(2))
    s = stats(j, d(10))
    assert s.sober_days == 10                 # всё, кроме дня срыва
    assert s.longest_streak == 8              # d(3)..d(10)


def test_window_days_are_counted_apart_and_break_the_streak():
    j = Journal()
    j.do(logic.stage_done, d(7))              # окно d(7)..d(9)
    j.do(logic.window_end, d(9))
    s = stats(j, d(16))
    assert s.window_days == 2                 # d(7), d(8); d(9) — уже этап
    assert s.sober_days == 15                 # 7 дней первого этапа + 8 второго
    assert s.longest_streak == 8              # окно оборвало серию из семи
    assert s.windows_closed == 1
    assert s.windows_dry == 1                 # в окне не пил


def test_dry_windows():
    j = Journal()
    j.do(logic.stage_done, d(7))
    j.do(logic.window_drink, d(8))
    j.do(logic.window_end, d(9))
    s = stats(j, d(16))
    assert s.windows_closed == 1
    assert s.windows_dry == 0
    assert s.sober_days == 15                 # выпивка в окне трезвости не портит

    j.do(logic.stage_done, j.state.end_date)  # второе окно ещё не кончилось
    s = stats(j, j.state.window_ends_on)
    assert s.windows_closed == 1              # незакрытое окно не считается
    assert s.windows_dry == 0


def test_automatic_window_exit_closes_the_window():
    j = Journal()
    j.do(logic.stage_done, d(7))
    j.read(d(12))                             # автовыход, этап с d(10)
    s = stats(j, d(12))
    assert s.window_days == 3                 # d(7)..d(9)
    assert s.windows_closed == 1
    assert s.windows_dry == 1
    assert s.sober_days == 10                 # 7 + d(10)..d(12)


def test_cycles_and_empty_journal():
    assert logic.compute_stats([], D0) == logic.Stats(0, 0, 0, 0, 0, 0, 0)

    j = Journal()
    for _ in range(4):
        j.close_stage()
    day = j.state.end_date
    j.do(logic.stage_done, day)
    s = stats(j, day)
    assert s.cycles_done == 1
    assert s.sober_days == 91                 # чистый цикл целиком
    assert s.longest_streak == 91             # окна нулевой длины серию не рвут
