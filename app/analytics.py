from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .formatters import (
    parse_appsheet_date,
    to_float_or_none,
    to_percent_ratio,
)


LOWER_KEYS = (
    "M3 ACUMULADO INFERIOR",
    "M3_ACUMULADO_INFERIOR",
)
UPPER_KEYS = (
    "M3 ACUMULADO SUPERIOR",
    "M3_ACUMULADO_SUPERIOR",
)
REAL_KEYS = (
    "M3 ACUMULADO REAL",
    "M3_ACUMULADO_REAL",
)


def pick(row: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
    return default


def _numeric(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    return to_float_or_none(pick(row, *keys))


def _week_date(row: dict[str, Any], end: bool = True) -> date | None:
    return parse_appsheet_date(
        pick(
            row,
            "FECHA_TERMINO" if end else "FECHA_INICIO",
            "FECHA_TERMINO_SEMANA" if end else "FECHA_INICIO_SEMANA",
        )
    )


def find_week(
    weeks: list[dict[str, Any]],
    week_id: Any,
) -> dict[str, Any] | None:
    target = str(week_id or "").strip()
    if not target:
        return None

    for row in weeks:
        current = str(
            pick(
                row,
                "ID_SEMANA_OBRA_GRUE",
                "ID_SEMANA_OBRA_GRUESA",
                default="",
            )
        ).strip()
        if current == target:
            return row

    return None


def sorted_weeks(weeks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        weeks,
        key=lambda row: (
            _week_date(row, end=True) or date.max,
            str(pick(row, "SEMANA", "SEMANA.", default="")),
        ),
    )


def curve_series(
    weeks: list[dict[str, Any]],
    current_week: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    current_end = _week_date(current_week or {}, end=True)
    result: list[dict[str, Any]] = []

    for row in sorted_weeks(weeks):
        end_date = _week_date(row, end=True)
        if end_date is None:
            continue

        lower = _numeric(row, LOWER_KEYS)
        upper = _numeric(row, UPPER_KEYS)
        real = _numeric(row, REAL_KEYS)

        # Mantener las semanas del programa si hay al menos una curva definida.
        if lower is None and upper is None and real is None:
            continue

        week_num = pick(row, "SEMANA", "SEMANA.", default=None)
        label = f"S{week_num}" if week_num not in (None, "") else end_date.strftime("%d/%m")

        result.append(
            {
                "date": end_date,
                "label": label,
                "lower": lower,
                "upper": upper,
                # No prolongar la curva real después de la semana de corte.
                "real": (
                    real
                    if current_end is None or end_date <= current_end
                    else None
                ),
            }
        )

    return result


def _linear_slope(points: list[tuple[date, float]]) -> float | None:
    """Pendiente de regresión lineal en m³/día."""
    if len(points) < 2:
        return None

    origin = points[0][0]
    xs = [(d - origin).days for d, _ in points]
    ys = [v for _, v in points]

    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)

    denominator = sum((x - x_mean) ** 2 for x in xs)
    if denominator <= 0:
        return None

    numerator = sum(
        (x - x_mean) * (y - y_mean)
        for x, y in zip(xs, ys)
    )

    slope = numerator / denominator
    return slope if slope > 0 else None


def build_general_summary(
    data: dict[str, Any],
    weeks: list[dict[str, Any]],
    current_week: dict[str, Any] | None,
) -> dict[str, Any]:
    if current_week is None:
        return {
            "available": False,
            "state": "SIN DATOS",
        }

    lower = _numeric(current_week, LOWER_KEYS)
    upper = _numeric(current_week, UPPER_KEYS)
    real = _numeric(current_week, REAL_KEYS)

    if lower is None or upper is None or real is None:
        return {
            "available": False,
            "state": "SIN DATOS",
            "lower": lower,
            "upper": upper,
            "real": real,
        }

    gap_lower = real - lower
    gap_upper = real - upper

    eps = 1e-6
    if real < lower - eps:
        state = "ATRASADO"
    elif real > upper + eps:
        state = "ADELANTADO"
    else:
        state = "EN RANGO"

    compliance_lower = (real / lower) if lower > 0 else None
    compliance_upper = (real / upper) if upper > 0 else None

    # Plazo total de la obra, calculado en backend para no depender del
    # formato de fecha que reciba una VC de AppSheet.
    start_project = parse_appsheet_date(data.get("FECHA_INICIO_OBRA"))
    end_project = parse_appsheet_date(data.get("FECHA_TERMINO_OBRA"))
    cutoff = parse_appsheet_date(data.get("FECHA_CORTE")) or _week_date(current_week, end=True)

    elapsed_ratio = None
    elapsed_days = None
    total_days = None
    if start_project and end_project and cutoff and end_project > start_project:
        total_days = (end_project - start_project).days
        elapsed_days = (cutoff - start_project).days
        elapsed_ratio = max(0.0, min(elapsed_days / total_days, 1.0))

    series = curve_series(weeks, current_week)

    # Objetivo final OG = máximo acumulado de banda superior.
    upper_points = [
        (item["date"], item["upper"])
        for item in series
        if item.get("upper") is not None
    ]

    target = max((v for _, v in upper_points), default=None)
    planned_finish = None
    if target is not None:
        dates_at_target = [
            d for d, v in upper_points
            if abs(v - target) <= 1e-6
        ]
        if dates_at_target:
            # Primer día en que la banda superior llega al objetivo final.
            planned_finish = min(dates_at_target)

    # Proyección lineal del ritmo reciente: últimas 3 semanas disponibles.
    current_end = _week_date(current_week, end=True) or cutoff
    actual_points = [
        (item["date"], item["real"])
        for item in series
        if item.get("real") is not None
        and current_end is not None
        and item["date"] <= current_end
    ]

    projection_points = actual_points[-3:]
    slope = _linear_slope(projection_points)
    estimated_finish = None
    deviation_days = None

    if target is not None and current_end is not None:
        if real >= target:
            estimated_finish = current_end
        elif slope is not None and slope > 0:
            remaining = max(0.0, target - real)
            days_remaining = remaining / slope
            estimated_finish = current_end + timedelta(days=round(days_remaining))

        if estimated_finish and planned_finish:
            deviation_days = (estimated_finish - planned_finish).days

    return {
        "available": True,
        "lower": lower,
        "upper": upper,
        "real": real,
        "gap_lower": gap_lower,
        "gap_upper": gap_upper,
        "compliance_lower": compliance_lower,
        "compliance_upper": compliance_upper,
        "state": state,
        "week_start": _week_date(current_week, end=False),
        "week_end": _week_date(current_week, end=True),
        "elapsed_ratio": elapsed_ratio,
        "elapsed_days": elapsed_days,
        "total_days": total_days,
        "target_final": target,
        "planned_finish_og": planned_finish,
        "estimated_finish": estimated_finish,
        "deviation_days": deviation_days,
        "projection_slope_m3_day": slope,
        "projection_points": len(projection_points),
        "series": series,
    }


def _loss(real: Any, geometric: Any, existing: Any = None) -> float | None:
    existing_ratio = to_percent_ratio(existing)
    if existing_ratio is not None:
        return existing_ratio

    real_n = to_float_or_none(real)
    geometric_n = to_float_or_none(geometric)
    if real_n is None or geometric_n is None or real_n <= 0:
        return None

    return max((real_n - geometric_n) / real_n, 0.0)


def build_weekly_summary(data: dict[str, Any]) -> dict[str, Any]:
    weeks = [
        {
            "label": "Hace 2 semanas",
            "short": "Hace 2",
            "projected": to_float_or_none(data.get("M3_PROGRAMADOS_2SEM")),
            "real": to_float_or_none(data.get("M3_REALES_2SEM")),
            "geometric": to_float_or_none(data.get("M3_GEOMETRICOS_2SEM")),
            "compliance": to_percent_ratio(data.get("CUMPLIMIENTO_2SEM")),
            "loss": _loss(
                data.get("M3_REALES_2SEM"),
                data.get("M3_GEOMETRICOS_2SEM"),
                data.get("%_PERDIDA_2SEM"),
            ),
        },
        {
            "label": "Semana anterior",
            "short": "Anterior",
            "projected": to_float_or_none(data.get("M3_PROGRAMADOS_SEM_ANT")),
            "real": to_float_or_none(data.get("M3_REALES_SEM_ANT")),
            "geometric": to_float_or_none(data.get("M3_GEOMETRICOS_SEM_ANT")),
            "compliance": to_percent_ratio(data.get("CUMPLIMIENTO_SEM_ANT")),
            "loss": _loss(
                data.get("M3_REALES_SEM_ANT"),
                data.get("M3_GEOMETRICOS_SEM_ANT"),
                data.get("%_PERDIDA_SEM_ANT"),
            ),
        },
        {
            "label": "Semana actual",
            "short": "Actual",
            "projected": to_float_or_none(data.get("M3_PROGRAMADOS_SEMANA")),
            "real": to_float_or_none(data.get("M3_REALES_SEMANA")),
            "geometric": to_float_or_none(data.get("M3_GEOMETRICOS_SEMANA")),
            "compliance": to_percent_ratio(data.get("CUMPLIMIENTO_SEMANA")),
            "loss": _loss(
                data.get("M3_REALES_SEMANA"),
                data.get("M3_GEOMETRICOS_SEMANA"),
                data.get("%_PERDIDA_SEM"),
            ),
        },
    ]

    daily = [
        ("Lunes", "GUIAS_LUN", "M3_LUN"),
        ("Martes", "GUIAS_MAR", "M3_MAR"),
        ("Miércoles", "GUIAS_MIE", "M3_MIE"),
        ("Jueves", "GUIAS_JUE", "M3_JUE"),
        ("Viernes", "GUIAS_VIE", "M3_VIE"),
        ("Sábado", "GUIAS_SAB", "M3_SAB"),
    ]

    daily_rows = [
        {
            "day": day,
            "guides": to_float_or_none(data.get(guides_key)) or 0,
            "m3": to_float_or_none(data.get(m3_key)) or 0.0,
        }
        for day, guides_key, m3_key in daily
    ]

    current = weeks[-1]

    return {
        "weeks": weeks,
        "current": current,
        "daily": daily_rows,
        "guides_total": to_float_or_none(data.get("GUIAS_SEMANA")) or sum(r["guides"] for r in daily_rows),
        "m3_total": to_float_or_none(data.get("M3_GUIAS_SEMANA")) or sum(r["m3"] for r in daily_rows),
    }


def build_invoice_summary(
    invoices: list[dict[str, Any]],
    cutoff_value: Any,
    data: dict[str, Any],
) -> dict[str, Any]:
    cutoff = parse_appsheet_date(cutoff_value)
    valid: list[tuple[date, dict[str, Any]]] = []

    for row in invoices:
        invoice_date = parse_appsheet_date(
            pick(row, "FECHA_EMISION", "FECHA", default=None)
        )
        if invoice_date is None:
            continue
        if cutoff is not None and invoice_date > cutoff:
            continue
        valid.append((invoice_date, row))

    if cutoff:
        month_rows = [
            row for d, row in valid
            if d.year == cutoff.year and d.month == cutoff.month
        ]
    else:
        month_rows = []

    def total(rows: list[dict[str, Any]], key: str) -> float:
        return sum(to_float_or_none(row.get(key)) or 0.0 for row in rows)

    accumulated_rows = [row for _, row in valid]

    return {
        "cutoff": cutoff,
        "count_month": len(month_rows),
        "net_month": total(month_rows, "NETO_FACTURA"),
        "iva_month": total(month_rows, "IVA_FACTURA"),
        "total_month": total(month_rows, "TOTAL_FACTURA"),
        "count_accum": len(accumulated_rows),
        "net_accum": total(accumulated_rows, "NETO_FACTURA"),
        "total_accum": total(accumulated_rows, "TOTAL_FACTURA"),
        "uf_pending": to_float_or_none(data.get("UF_POR_FACTURAR_OC")),
        "m3_invoiced": to_float_or_none(data.get("M3_FACTURADOS_OC")),
        "m3_contract": to_float_or_none(data.get("M3_OC_HORMIGON")),
        "m3_consumed": to_float_or_none(data.get("M3_CONSUMIDOS_OC")),
        "m3_balance": to_float_or_none(data.get("M3_SALDO_OC")),
        "oc_consumption": to_percent_ratio(data.get("PORC_CONSUMO_OC_HORMIGON")),
    }


def build_floor_map(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for row in rows:
        key = str(row.get("ID_PISO", "")).strip()
        if not key:
            continue

        # El usuario definió N PISO como el número real que debe aparecer
        # en el pie de fotografía. PISO queda como fallback.
        display = row.get("N PISO")
        if display in (None, ""):
            display = row.get("PISO")

        result[key] = display

    return result
