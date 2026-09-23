from __future__ import annotations

from datetime import date, datetime
from typing import Any


MONTHS_ES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def first_value(data: dict, *keys: str, default: Any = "—") -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return default


def to_float(value: Any, default: float = 0.0) -> float:
    result = to_float_or_none(value)
    return default if result is None else result


def to_float_or_none(value: Any) -> float | None:
    if value in (None, "", "—"):
        return None

    if isinstance(value, bool):
        return float(value)

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    text = (
        text.replace("UF", "")
        .replace("$", "")
        .replace("m3", "")
        .replace("m³", "")
        .strip()
    )

    is_percent = text.endswith("%")
    if is_percent:
        text = text[:-1].strip()

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")

    try:
        value_num = float(text)
    except ValueError:
        return None

    return value_num / 100.0 if is_percent else value_num


def to_percent_ratio(value: Any) -> float | None:
    """Devuelve porcentaje como fracción: 75,5% -> 0.755."""
    if value in (None, "", "—"):
        return None

    if isinstance(value, str) and "%" in value:
        return to_float_or_none(value)

    n = to_float_or_none(value)
    if n is None:
        return None

    # AppSheet Percent normalmente entrega fracción. Si llega 75.5,
    # lo interpretamos como puntos porcentuales.
    if abs(n) > 1.5:
        return n / 100.0

    return n


def fmt_number(value: Any, decimals: int = 1) -> str:
    n = to_float_or_none(value)
    if n is None:
        return "—"

    if decimals == 0:
        return f"{n:,.0f}".replace(",", ".")

    s = f"{n:,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_percent(value: Any, decimals: int = 1) -> str:
    ratio = to_percent_ratio(value)
    if ratio is None:
        return "—"
    return f"{ratio * 100:.{decimals}f}".replace(".", ",") + "%"


def fmt_clp(value: Any) -> str:
    n = to_float_or_none(value)
    if n is None:
        return "—"
    return "$ " + f"{round(n):,}".replace(",", ".")


def fmt_uf(value: Any, decimals: int = 1) -> str:
    if to_float_or_none(value) is None:
        return "—"
    return f"{fmt_number(value, decimals)} UF"


def fmt_m3(value: Any, decimals: int = 1) -> str:
    if to_float_or_none(value) is None:
        return "—"
    return f"{fmt_number(value, decimals)} m³"


def fmt_signed_m3(value: Any, decimals: int = 1) -> str:
    n = to_float_or_none(value)
    if n is None:
        return "—"
    sign = "+" if n > 0 else ""
    return f"{sign}{fmt_number(n, decimals)} m³"


def parse_appsheet_date(value: Any) -> date | None:
    """
    Convierte fechas recibidas desde AppSheet API.

    La API de esta aplicación trabaja con Locale en-US, por lo que una fecha
    ambigua como 09/11/2026 corresponde a 11 de septiembre de 2026.
    Por eso MM/DD/YYYY se intenta antes que DD/MM/YYYY.
    """
    if value in (None, "", "—"):
        return None

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    text = str(value).strip()

    # ISO / DateTime ISO.
    iso = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso).date()
    except ValueError:
        pass

    candidates = [text]
    if len(text) >= 10:
        candidates.append(text[:10])

    for candidate in candidates:
        for pattern in (
            "%m/%d/%Y",  # AppSheet API con Locale en-US
            "%d/%m/%Y",  # fallback no ambiguo / entradas manuales
            "%Y-%m-%d",
        ):
            try:
                return datetime.strptime(candidate, pattern).date()
            except ValueError:
                pass

    return None


def fmt_date(value: Any) -> str:
    parsed = parse_appsheet_date(value)
    if parsed is None:
        return "—" if value in (None, "", "—") else str(value)
    return parsed.strftime("%d/%m/%Y")


def fmt_datetime(value: Any) -> str:
    if value in (None, "", "—"):
        return "—"

    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M")

    text = str(value).strip()
    for pattern in (
        "%Y-%m-%dT%H:%M:%S",
        "%m/%d/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(text[:19], pattern).strftime("%d/%m/%Y %H:%M")
        except ValueError:
            pass

    return text


def fmt_month_year(value: Any) -> str:
    parsed = parse_appsheet_date(value)
    if parsed is None:
        return "—"
    return f"{MONTHS_ES[parsed.month - 1]} {parsed.year}"


def fmt_days_deviation(value: Any) -> str:
    n = to_float_or_none(value)
    if n is None:
        return "—"

    days = int(round(n))
    if days > 0:
        return f"{days} días de atraso"
    if days < 0:
        return f"{abs(days)} días de adelanto"
    return "En fecha"


def fmt_floor(value: Any) -> str:
    n = to_float_or_none(value)
    if n is None:
        return str(value) if value not in (None, "", "—") else "—"

    if abs(n - round(n)) < 1e-9:
        return str(int(round(n)))
    return fmt_number(n, 1)
