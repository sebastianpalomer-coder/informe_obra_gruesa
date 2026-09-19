from __future__ import annotations

from datetime import datetime, date
from typing import Any


def first_value(data: dict, *keys: str, default: Any = "—") -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return default


def to_float(value: Any, default: float = 0.0) -> float:
    if value in (None, "", "—"):
        return default
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    text = text.replace("UF", "").replace("$", "").replace("m3", "").replace("m³", "").strip()

    if text.endswith("%"):
        text = text[:-1].strip()
        text = text.replace(".", "").replace(",", ".")
        try:
            return float(text) / 100.0
        except ValueError:
            return default

    # AppSheet / Chilean formatting support.
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")

    try:
        return float(text)
    except ValueError:
        return default


def fmt_number(value: Any, decimals: int = 1) -> str:
    n = to_float(value)
    if decimals == 0:
        return f"{n:,.0f}".replace(",", ".")
    s = f"{n:,.{decimals}f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def fmt_percent(value: Any, decimals: int = 1) -> str:
    if value in (None, "", "—"):
        return "—"
    n = to_float(value)
    # Numeric AppSheet percent is normally a unit fraction.
    if isinstance(value, (int, float)) and abs(n) <= 1.5:
        n *= 100.0
    elif isinstance(value, str) and "%" not in value and abs(n) <= 1.5:
        n *= 100.0
    return f"{n:.{decimals}f}".replace(".", ",") + "%"


def fmt_clp(value: Any) -> str:
    n = round(to_float(value))
    return "$ " + f"{n:,}".replace(",", ".")


def fmt_uf(value: Any, decimals: int = 1) -> str:
    return f"{fmt_number(value, decimals)} UF"


def fmt_m3(value: Any, decimals: int = 1) -> str:
    return f"{fmt_number(value, decimals)} m³"


def fmt_date(value: Any) -> str:
    if value in (None, "", "—"):
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")

    text = str(value).strip()
    for pattern in (
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%d/%m/%Y",
        "%m/%d/%Y",
    ):
        try:
            return datetime.strptime(text[:19], pattern).strftime("%d/%m/%Y")
        except ValueError:
            pass
    return text


def fmt_datetime(value: Any) -> str:
    if value in (None, "", "—"):
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M")
    return str(value)
