"""Русские формулировки чисел и дат. Нужны и шаблонам, и текстам отказов."""

from datetime import date

MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня",
          "июля", "августа", "сентября", "октября", "ноября", "декабря")


def ru_date(value: date) -> str:
    return f"{value.day} {MONTHS[value.month - 1]}"


def plural(n: int, one: str, few: str, many: str) -> str:
    """1 неделя, 2 недели, 5 недель."""
    tail = abs(n) % 100
    if 11 <= tail <= 14:
        return many
    tail %= 10
    if tail == 1:
        return one
    if 2 <= tail <= 4:
        return few
    return many


# Как событие называется в журнале на экране истории.
EVENT_LABELS = {
    "stage_start": "Этап начат",
    "relapse": "Срыв",
    "stage_done": "Этап закрыт",
    "cycle_done": "Цикл пройден",
    "window_end": "Этап начат",
    "window_drink": "Выпил в окне",
}

# Что именно отменяет кнопка. Автоматических событий здесь нет — они не отменяются.
UNDO_LABELS = {
    "relapse": "срыв",
    "stage_done": "закрытие этапа",
    "window_end": "начало этапа",
    "window_drink": "выпивку в окне",
}


def days(n: int) -> str:
    return f"{n} {plural(n, 'день', 'дня', 'дней')}"


def weeks(n: int) -> str:
    return f"{n} {plural(n, 'неделя', 'недели', 'недель')}"
