"""SQLite: схема, журнал, единственная строка состояния.

Здесь нет ни одного правила предметной области — только хранение. Состояние в
таблице `state` — кэш: любой записи событий предшествует пересчёт через
`logic.apply_event`, а `undo` пересобирает состояние с нуля.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date
from pathlib import Path

from . import logic
from .clock import now_utc_iso

DB_PATH = Path(os.environ.get("ALCODRY_DB", "data/tracker.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT    NOT NULL,
    local_date    TEXT    NOT NULL,
    kind          TEXT    NOT NULL CHECK (kind IN (
                      'stage_start','relapse','stage_done',
                      'cycle_done','window_end','window_drink')),
    stage_index   INTEGER NOT NULL,
    penalty_weeks INTEGER NOT NULL,
    cycle_no      INTEGER NOT NULL,
    auto          INTEGER NOT NULL DEFAULT 0,
    note          TEXT
);

CREATE TABLE IF NOT EXISTS state (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    mode           TEXT    NOT NULL CHECK (mode IN ('stage','window')),
    stage_index    INTEGER NOT NULL,
    penalty_weeks  INTEGER NOT NULL,
    start_date     TEXT    NOT NULL,
    window_ends_on TEXT,
    cycle_no       INTEGER NOT NULL
);
"""

def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    if path != ":memory:":
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection, today: date) -> None:
    """Схема и, если журнал пуст, первое событие."""
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"] == 0:
        _append(conn, None, logic.start_journal(today))


# --- чтение -----------------------------------------------------------------

def _row_to_event(row: sqlite3.Row) -> logic.Event:
    return logic.Event(
        kind=row["kind"],
        local_date=date.fromisoformat(row["local_date"]),
        stage_index=row["stage_index"],
        penalty_weeks=row["penalty_weeks"],
        cycle_no=row["cycle_no"],
        auto=bool(row["auto"]),
        note=row["note"],
        id=row["id"],
        ts=row["ts"],
    )


def all_events(conn: sqlite3.Connection) -> list[logic.Event]:
    rows = conn.execute("SELECT * FROM events ORDER BY id").fetchall()
    return [_row_to_event(r) for r in rows]


def stored_state(conn: sqlite3.Connection) -> logic.State | None:
    row = conn.execute("SELECT * FROM state WHERE id = 1").fetchone()
    if row is None:
        return None
    return logic.State(
        mode=row["mode"],
        stage_index=row["stage_index"],
        penalty_weeks=row["penalty_weeks"],
        start_date=date.fromisoformat(row["start_date"]),
        window_ends_on=(date.fromisoformat(row["window_ends_on"])
                        if row["window_ends_on"] else None),
        cycle_no=row["cycle_no"],
    )


def current_state(conn: sqlite3.Connection, today: date) -> logic.State:
    """Состояние с уже применённым автовыходом из окна."""
    state = stored_state(conn)
    assert state is not None, "init_db не вызывали"
    catch_up = logic.catch_up(state, today)
    if catch_up:
        state = _append(conn, state, catch_up)
    return state


# --- запись -----------------------------------------------------------------

def _append(conn: sqlite3.Connection, state: logic.State | None,
            events: list[logic.Event]) -> logic.State:
    ts = now_utc_iso()
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        for event in events:
            conn.execute(
                "INSERT INTO events (ts, local_date, kind, stage_index,"
                " penalty_weeks, cycle_no, auto, note)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (ts, event.local_date.isoformat(), event.kind, event.stage_index,
                 event.penalty_weeks, event.cycle_no, int(event.auto), event.note),
            )
        state = logic.apply_all(state, events)
        _save_state(conn, state)
    return state


def _save_state(conn: sqlite3.Connection, state: logic.State) -> None:
    conn.execute(
        "INSERT INTO state (id, mode, stage_index, penalty_weeks, start_date,"
        " window_ends_on, cycle_no) VALUES (1, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(id) DO UPDATE SET mode=excluded.mode,"
        " stage_index=excluded.stage_index, penalty_weeks=excluded.penalty_weeks,"
        " start_date=excluded.start_date, window_ends_on=excluded.window_ends_on,"
        " cycle_no=excluded.cycle_no",
        (state.mode, state.stage_index, state.penalty_weeks,
         state.start_date.isoformat(),
         state.window_ends_on.isoformat() if state.window_ends_on else None,
         state.cycle_no),
    )


def act(conn: sqlite3.Connection, action, today: date,
        note: str | None = None) -> logic.State:
    """Выполнить действие из `logic` поверх актуального состояния."""
    state = current_state(conn, today)
    return _append(conn, state, action(state, today, note))


# --- отмена -----------------------------------------------------------------

def undoable(conn: sqlite3.Connection) -> logic.Event | None:
    """Последнее пользовательское событие. Автоматические не отменяются."""
    row = conn.execute(
        "SELECT * FROM events WHERE auto = 0 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return _row_to_event(row) if row else None


def undo(conn: sqlite3.Connection) -> logic.Event:
    """Снести последнее пользовательское действие вместе со всем, что журнал
    дописал после него автоматически, и пересобрать состояние с нуля."""
    target = undoable(conn)
    if target is None:
        raise logic.TransitionError("Отменять нечего")
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM events WHERE id >= ?", (target.id,))
        state = logic.rebuild_state_from_events(all_events(conn))
        assert state is not None, "в журнале не осталось стартового события"
        _save_state(conn, state)
    return target
