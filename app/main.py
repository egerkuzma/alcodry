"""HTTP-слой: тонкая обёртка над `logic` и `db`.

Здесь нет ни одного правила предметной области. Единственная содержательная
работа — превратить `TransitionError` в 409 и состояние в JSON.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db, logic, ru
from .clock import today

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = db.connect()
    db.init_db(conn, today())
    conn.close()
    yield


app = FastAPI(title="alcodry", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.trim_blocks = True
templates.env.lstrip_blocks = True
templates.env.filters["ru_date"] = ru.ru_date
templates.env.filters["days"] = ru.days
templates.env.filters["weeks"] = ru.weeks
templates.env.filters["plural"] = ru.plural


def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


@app.exception_handler(logic.TransitionError)
async def transition_error(request: Request, exc: logic.TransitionError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


def status_payload(state: logic.State, day: date) -> dict:
    if state.mode == logic.MODE_WINDOW:
        return {
            "mode": "window",
            "window_ends_on": state.window_ends_on.isoformat(),
            "window_days_left": state.window_days_left(day),
            "next_stage_no": state.stage_index + 1,
            "next_stage_weeks": state.stage_weeks,
            "cycle_no": state.cycle_no,
        }
    return {
        "mode": "stage",
        "stage_no": state.stage_index + 1,
        "stages_in_cycle": state.stages_in_cycle,
        "base_weeks": state.base_weeks,
        "penalty_weeks": state.penalty_weeks,
        "stage_weeks": state.stage_weeks,
        "days_passed": state.days_passed(day),
        "days_total": state.stage_weeks * 7,
        "days_left": state.days_left(day),
        "can_close": state.can_close(day),
        "cycle_no": state.cycle_no,
        "start_date": state.start_date.isoformat(),
        "end_date": state.end_date.isoformat(),
    }


# --- экраны -----------------------------------------------------------------
# Действия интерфейса отвечают тем же блоком, что и рисовали: отказ показывается
# строкой в нём, а не кодом ответа — 409 htmx бы просто не вставил. Проверка
# всё та же серверная, `db.act` до журнала не доходит.

def render(request: Request, template: str, conn, day: date,
           error: str | None = None):
    state = db.current_state(conn, day)
    return templates.TemplateResponse(request, template, {
        "state": state,
        "today": day,
        "error": error,
        "max_weeks": logic.max_stage_weeks(state.cycle_no),
    })


def ui_action(request: Request, conn, action):
    day = today()
    error = None
    try:
        db.act(conn, action, day)
    except logic.TransitionError as exc:
        error = str(exc)
    return render(request, "_panel.html", conn, day, error)


@app.get("/")
def index(request: Request, conn=Depends(get_conn)):
    return render(request, "index.html", conn, today())


@app.get("/ui/panel")
def ui_panel(request: Request, conn=Depends(get_conn)):
    return render(request, "_panel.html", conn, today())


@app.post("/ui/relapse")
def ui_relapse(request: Request, conn=Depends(get_conn)):
    return ui_action(request, conn, logic.relapse)


@app.post("/ui/stage-done")
def ui_stage_done(request: Request, conn=Depends(get_conn)):
    return ui_action(request, conn, logic.stage_done)


@app.post("/ui/window-end")
def ui_window_end(request: Request, conn=Depends(get_conn)):
    return ui_action(request, conn, logic.window_end)


@app.post("/ui/window-drink")
def ui_window_drink(request: Request, conn=Depends(get_conn)):
    return ui_action(request, conn, logic.window_drink)


def by_days(events: list[logic.Event]) -> list[tuple[date, list[logic.Event]]]:
    """Журнал по дням, от новых к старым; внутри дня — тоже от новых."""
    days: list[tuple[date, list[logic.Event]]] = []
    for event in reversed(events):
        if not days or days[-1][0] != event.local_date:
            days.append((event.local_date, []))
        days[-1][1].append(event)
    return days


def render_history(request: Request, template: str, conn, day: date,
                   error: str | None = None, undone: str | None = None):
    events = db.all_events(conn)
    target = db.undoable(conn)
    return templates.TemplateResponse(request, template, {
        "today": day,
        "stats": logic.compute_stats(events, day),
        "days": by_days(events),
        "labels": ru.EVENT_LABELS,
        "first_id": events[0].id if events else None,
        "undoable": target,
        "undo_label": ru.UNDO_LABELS.get(target.kind, "действие") if target else None,
        "error": error,
        "undone": undone,
    })


@app.get("/history")
def history(request: Request, conn=Depends(get_conn)):
    day = today()
    db.current_state(conn, day)          # автовыход из окна виден и здесь
    return render_history(request, "history.html", conn, day)


@app.post("/ui/undo")
def ui_undo(request: Request, conn=Depends(get_conn)):
    day = today()
    error = undone = None
    try:
        event = db.undo(conn)
        undone = f"{ru.UNDO_LABELS.get(event.kind, event.kind)} " \
                 f"{ru.ru_date(event.local_date)}"
    except logic.TransitionError as exc:
        error = str(exc)
    db.current_state(conn, day)
    return render_history(request, "_history.html", conn, day, error, undone)


# --- API --------------------------------------------------------------------

@app.get("/healthz")
def healthz(conn=Depends(get_conn)):
    state = db.stored_state(conn)
    if state is None:
        return JSONResponse(status_code=503, content={"status": "no state"})
    return {"status": "ok", "today": today().isoformat()}


@app.get("/api/status")
def api_status(conn=Depends(get_conn)):
    day = today()
    return status_payload(db.current_state(conn, day), day)


@app.post("/api/relapse")
def api_relapse(note: str | None = None, conn=Depends(get_conn)):
    day = today()
    return status_payload(db.act(conn, logic.relapse, day, note), day)


@app.post("/api/stage-done")
def api_stage_done(note: str | None = None, conn=Depends(get_conn)):
    day = today()
    return status_payload(db.act(conn, logic.stage_done, day, note), day)


@app.post("/api/window-end")
def api_window_end(note: str | None = None, conn=Depends(get_conn)):
    day = today()
    return status_payload(db.act(conn, logic.window_end, day, note), day)


@app.post("/api/window-drink")
def api_window_drink(note: str | None = None, conn=Depends(get_conn)):
    day = today()
    return status_payload(db.act(conn, logic.window_drink, day, note), day)


@app.post("/api/undo")
def api_undo(conn=Depends(get_conn)):
    day = today()
    undone = db.undo(conn)
    return {
        "undone": {
            "kind": undone.kind,
            "label": ru.UNDO_LABELS.get(undone.kind, undone.kind),
            "local_date": undone.local_date.isoformat(),
        },
        "status": status_payload(db.current_state(conn, day), day),
    }
