import re
from datetime import date, timedelta


_WEEKDAYS_RU = {
    "понедельник": 0, "вторник": 1, "среду": 2, "среда": 2,
    "четверг": 3, "пятницу": 4, "пятница": 4, "субботу": 5,
    "суббота": 5, "воскресенье": 6, "воскресенье": 6,
}

_MONTHS_RU = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}


def extract_date_from_text(text: str) -> str | None:
    t = text.lower()
    today = date.today()

    if "послезавтра" in t:
        return (today + timedelta(days=2)).isoformat()
    if "завтра" in t:
        return (today + timedelta(days=1)).isoformat()
    if "сегодня" in t:
        return today.isoformat()

    # "в пятницу", "в понедельник" и т.д.
    for word, weekday in _WEEKDAYS_RU.items():
        if word in t:
            days_ahead = (weekday - today.weekday()) % 7 or 7
            return (today + timedelta(days=days_ahead)).isoformat()

    # "7 апреля", "15 января" и т.д.
    for month_name, month_num in _MONTHS_RU.items():
        match = re.search(rf"(\d{{1,2}})\s+{month_name}", t)
        if match:
            day = int(match.group(1))
            year = today.year
            d = date(year, month_num, day)
            if d < today:
                d = date(year + 1, month_num, day)
            return d.isoformat()

    return None
