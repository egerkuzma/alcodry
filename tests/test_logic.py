"""Пункты 1–16 раздела 6 спецификации. Нумерация тестов совпадает со спекой."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app import logic
from helpers import D0, Journal, d

ONE_DAY = timedelta(days=1)


# 1
def test_start_from_scratch():
    j = Journal()
    s = j.state
    assert s.mode == "stage"
    assert s.stage_index == 0
    assert s.penalty_weeks == 0
    assert s.cycle_no == 1
    assert s.stage_weeks == 1
    assert s.start_date == D0
    assert s.end_date == d(7)
    assert s.can_close(d(6)) is False


# 2
def test_first_stage_closed_opens_window():
    j = Journal()
    s = j.do(logic.stage_done, d(7))
    assert s.mode == "window"
    assert s.window_ends_on == d(9)          # день закрытия входит в окно
    assert s.window_days_left(d(7)) == logic.STAGE_WINDOW_DAYS == 3
    assert s.window_days_left(d(9)) == 1


# 3
def test_window_end_starts_next_stage():
    j = Journal()
    j.do(logic.stage_done, d(7))
    s = j.do(logic.window_end, d(8))
    assert s.mode == "stage"
    assert s.stage_index == 1
    assert s.stage_weeks == 2
    assert s.penalty_weeks == 0
    assert s.start_date == d(8)
    assert s.end_date == d(22)


# 4
def test_relapse_extends_stage_without_advancing():
    j = Journal()
    s = j.do(logic.relapse, d(3))
    assert s.mode == "stage"
    assert s.stage_index == 0
    assert s.penalty_weeks == 1
    assert s.stage_weeks == 2
    assert s.start_date == d(3)               # отсчёт заново с нуля
    assert s.days_passed(d(3)) == 0
    assert s.end_date == d(17)


# 5
def test_two_relapses_in_a_row():
    j = Journal()
    j.do(logic.relapse, d(3))
    s = j.do(logic.relapse, d(5))
    assert s.stage_index == 0
    assert s.penalty_weeks == 2
    assert s.stage_weeks == 3
    assert s.start_date == d(5)


# 6
def test_five_clean_stages_close_the_cycle():
    j = Journal()
    for _ in range(4):
        j.close_stage()
    day = j.state.end_date
    s = j.do(logic.stage_done, day)           # пятый этап

    assert "cycle_done" in j.kinds()
    assert s.cycle_no == 2
    assert s.stage_index == 0
    assert s.mode == "window"
    assert s.window_ends_on == day + (logic.CYCLE_WINDOW_DAYS - 1) * ONE_DAY

    s = j.do(logic.window_end, day)
    assert s.stage_weeks == 1                 # лестница нового цикла с начала


# 7
def test_cycle_does_not_close_until_last_stage_is_honest():
    j = Journal()
    for _ in range(4):
        j.close_stage()
    assert j.state.stage_index == 4
    assert j.state.stage_weeks == 4

    for _ in range(3):
        s = j.do(logic.relapse, j.state.start_date + ONE_DAY)
        assert s.stage_index == 4             # срыв не двигает лестницу
        assert s.cycle_no == 1
        assert "cycle_done" not in j.kinds()

    s = j.do(logic.stage_done, j.state.end_date)
    assert "cycle_done" in j.kinds()
    assert s.cycle_no == 2


# 8
def test_early_close_is_rejected():
    j = Journal()
    with pytest.raises(logic.TransitionError):
        j.do(logic.stage_done, d(6))
    assert j.state.mode == "stage"            # состояние не тронуто
    assert len(j.events) == 1


# 9
def test_close_exactly_on_end_date_is_allowed():
    j = Journal()
    assert j.state.can_close(d(7)) is True
    s = j.do(logic.stage_done, d(7))
    assert s.mode == "window"


# 10
def test_penalty_is_capped_by_max_stage_weeks():
    j = Journal()
    for i in range(5):
        j.do(logic.relapse, d(i))
    assert j.state.penalty_weeks == 5         # штраф в журнале растёт дальше
    assert j.state.stage_weeks == logic.max_stage_weeks(1) == 4

    j = Journal()
    for _ in range(4):
        j.close_stage()
    assert j.state.base_weeks == 4            # последний этап лестницы
    s = j.do(logic.relapse, j.state.start_date + ONE_DAY)
    assert s.penalty_weeks == 1
    assert s.stage_weeks == 4                 # срыв длину уже не меняет


# 11
def test_window_drink_changes_nothing():
    j = Journal()
    before = j.do(logic.stage_done, d(7))
    after = j.do(logic.window_drink, d(8))
    assert after == before
    assert j.kinds()[-1] == "window_drink"    # но в журнале остался


# 12
def test_relapse_in_window_is_rejected():
    j = Journal()
    j.do(logic.stage_done, d(7))
    with pytest.raises(logic.TransitionError):
        j.do(logic.relapse, d(8))
    assert j.state.mode == "window"


# 13
def test_window_expires_by_itself():
    j = Journal()
    j.do(logic.stage_done, d(7))              # окно по d(9) включительно
    assert j.read(d(9)).mode == "window"      # последний день окна ещё окно

    s = j.read(d(12))                         # зашли только через три дня
    assert s.mode == "stage"
    assert s.start_date == d(10)              # window_ends_on + 1, а не «сегодня»
    assert s.stage_index == 1
    assert j.events[-1].kind == "stage_start"
    assert j.events[-1].auto is True
    assert j.read(d(12)) == s                 # повторное чтение ничего не пишет
    assert j.kinds().count("stage_start") == 2


# 14
def test_clean_cycle_takes_exactly_91_days():
    j = Journal()
    for _ in range(4):
        j.close_stage()
    day = j.state.end_date
    j.do(logic.stage_done, day)
    assert (day - D0).days == 91              # 1+2+3+3+4 недель


# 15
def test_ladder_length_is_never_hardcoded(monkeypatch):
    monkeypatch.setattr(logic, "stages_for_cycle", lambda cycle_no: [1, 2])

    j = Journal()
    assert j.state.stages_in_cycle == 2
    assert j.state.stage_weeks == 1

    j.close_stage()
    assert j.state.stage_index == 1
    assert j.state.stage_weeks == 2
    assert "cycle_done" not in j.kinds()

    s = j.do(logic.stage_done, j.state.end_date)
    assert "cycle_done" in j.kinds()          # цикл закрылся после двух этапов
    assert s.cycle_no == 2
    assert s.stage_index == 0

    j.do(logic.window_end, s.window_ends_on)
    for _ in range(3):
        j.do(logic.relapse, j.state.start_date)
    assert j.state.stage_weeks == logic.max_stage_weeks(2) == 2


# 16
def test_rebuild_matches_step_by_step_application():
    j = Journal()
    j.do(logic.relapse, d(2))
    j.do(logic.relapse, d(4))
    j.do(logic.stage_done, j.state.end_date)              # окно
    j.do(logic.window_drink, j.state.window_ends_on)
    j.read(j.state.window_ends_on + ONE_DAY)              # автовыход
    j.do(logic.relapse, j.state.start_date + ONE_DAY)
    j.do(logic.stage_done, j.state.end_date)
    j.do(logic.window_end, j.state.window_ends_on)
    j.close_stage()
    j.close_stage()
    j.do(logic.relapse, j.state.start_date + ONE_DAY)
    j.do(logic.stage_done, j.state.end_date)              # пятый этап и цикл
    j.do(logic.window_drink, j.state.window_ends_on)
    j.do(logic.window_end, j.state.window_ends_on)
    j.do(logic.relapse, j.state.start_date + ONE_DAY)     # уже второй цикл
    j.do(logic.stage_done, j.state.end_date)
    j.do(logic.window_end, j.state.window_ends_on)

    assert len(j.events) >= 20
    assert "cycle_done" in j.kinds()
    assert logic.rebuild_state_from_events(j.events) == j.state

    # и любой префикс журнала тоже воспроизводится
    step = None
    for i, event in enumerate(j.events, start=1):
        step = logic.apply_event(step, event)
        assert logic.rebuild_state_from_events(j.events[:i]) == step
