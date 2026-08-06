"""Пункт 17 раздела 6: отмена последнего действия.

Отмена живёт в слое хранения, поэтому здесь есть sqlite — но по-прежнему нет HTTP.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app import db, logic
from helpers import D0, d

ONE_DAY = timedelta(days=1)


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    db.init_db(connection, D0)
    yield connection
    connection.close()


def assert_consistent(connection):
    """Журнал и строка состояния не разошлись."""
    assert logic.rebuild_state_from_events(db.all_events(connection)) \
        == db.stored_state(connection)


def test_undo_restores_previous_state(conn):
    before = db.current_state(conn, d(2))
    db.act(conn, logic.relapse, d(2))
    assert db.stored_state(conn).penalty_weeks == 1

    undone = db.undo(conn)
    assert undone.kind == "relapse"
    assert db.stored_state(conn) == before
    assert_consistent(conn)


def test_undo_restores_mode(conn):
    before = db.current_state(conn, d(7))
    db.act(conn, logic.stage_done, d(7))
    assert db.stored_state(conn).mode == "window"

    db.undo(conn)
    restored = db.stored_state(conn)
    assert restored == before
    assert restored.mode == "stage"
    assert restored.stage_index == 0
    assert restored.start_date == D0
    assert_consistent(conn)


def test_undo_ignores_automatic_events(conn):
    before = db.current_state(conn, d(7))
    db.act(conn, logic.stage_done, d(7))
    state = db.current_state(conn, d(12))          # окно истекло, дописан автовыход
    assert state.mode == "stage"
    assert db.all_events(conn)[-1].auto is True

    assert db.undoable(conn).kind == "stage_done"  # кнопка обещает отменить его
    undone = db.undo(conn)
    assert undone.kind == "stage_done"

    restored = db.stored_state(conn)
    assert restored == before                      # автовыход снесён вместе с ним
    assert [e.kind for e in db.all_events(conn)] == ["stage_start"]
    assert_consistent(conn)


def test_undo_of_a_relapse_after_automatic_start(conn):
    db.act(conn, logic.stage_done, d(7))
    db.current_state(conn, d(12))                  # автовыход, этап с d(10)
    before = db.stored_state(conn)
    db.act(conn, logic.relapse, d(12))

    db.undo(conn)
    assert db.stored_state(conn) == before         # авто-старт этапа на месте
    assert db.all_events(conn)[-1].auto is True
    assert_consistent(conn)


def test_undo_of_the_last_stage_takes_cycle_done_with_it(conn):
    """`cycle_done` — спутник закрытия этапа, а не отдельное действие.
    Останься он один, состояние получит индекс этапа вне лестницы."""
    day = D0
    for _ in range(4):                             # четыре этапа начисто
        state = db.current_state(conn, day)
        day = state.end_date
        db.act(conn, logic.stage_done, day)
        db.act(conn, logic.window_end, day)
    before = db.current_state(conn, day)
    assert before.stage_index == 4

    day = before.end_date
    after = db.act(conn, logic.stage_done, day)    # пятый этап, цикл закрыт
    assert after.cycle_no == 2
    assert [e.kind for e in db.all_events(conn)][-2:] == ["stage_done", "cycle_done"]

    assert db.undoable(conn).kind == "stage_done"
    db.undo(conn)
    restored = db.stored_state(conn)
    assert restored == before                      # снова пятый этап первого цикла
    assert restored.stage_index < restored.stages_in_cycle
    assert restored.stage_weeks == 4               # состояние читаемо, лестница цела
    assert "cycle_done" not in [e.kind for e in db.all_events(conn)]
    assert_consistent(conn)


def test_nothing_to_undo(conn):
    assert db.undoable(conn) is None               # в журнале только авто-старт
    with pytest.raises(logic.TransitionError):
        db.undo(conn)
    assert_consistent(conn)


def test_rejected_action_leaves_no_trace(conn):
    with pytest.raises(logic.TransitionError):
        db.act(conn, logic.stage_done, d(6))       # досрочно
    assert len(db.all_events(conn)) == 1
    assert_consistent(conn)
