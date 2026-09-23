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


def _row_week_id(row: dict[str, Any]) -> str:
    return str(
        pick(
            row,
            "ID_SEMANA_OBRA_GRUE",
            "ID_SEMANA_OBRA_GRUESA",
            default="",
        )
    ).strip()


def _rows_for_week(
    rows: list[dict[str, Any]],
    week_id: Any,
) -> list[dict[str, Any]]:
    target = str(week_id or "").strip()
    if not target:
        return []

    return [
        row for row in rows
        if _row_week_id(row) == target
    ]


def _sum_alias(
    rows: list[dict[str, Any]],
    *keys: str,
) -> float:
    total = 0.0
    for row in rows:
        value = to_float_or_none(
            pick(row, *keys, default=None)
        )
        if value is not None:
            total += value
    return total


def _week_metrics_from_sources(
    week_row: dict[str, Any],
    detail_rows: list[dict[str, Any]],
    guide_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    week_id = _row_week_id(week_row)

    detail_week = _rows_for_week(
        detail_rows,
        week_id,
    )
    guides_week = _rows_for_week(
        guide_rows,
        week_id,
    )

    projected = _sum_alias(
        detail_week,
        "M3_PROGRAMADOS",
        "M3_PROYECTADOS",
        "M3 PROGRAMADOS",
        "M3 PROYECTADOS",
    )

    geometric = _sum_alias(
        detail_week,
        "M3_GEOMETRICO",
        "M3_GEOMETRICOS",
        "M3 GEOMETRICO",
        "M3 GEOMETRICOS",
    )

    # Los m³ reales se obtienen de las guías efectivamente recibidas.
    # Así el KPI semanal y la tabla diaria provienen de la misma fuente.
    if guides_week:
        real = _sum_alias(
            guides_week,
            "CANTIDAD",
            "M3",
            "M3_GUIA",
        )
    else:
        # Fallback para semanas antiguas donde no existan guías cargadas.
        real = _sum_alias(
            detail_week,
            "M3_REALES",
            "M3_REAL",
            "M3 REALES",
        )

    compliance = (
        real / projected
        if projected > 0
        else None
    )

    loss = (
        max((real - geometric) / real, 0.0)
        if real > 0
        else None
    )

    return {
        "week_id": week_id,
        "projected": projected,
        "real": real,
        "geometric": geometric,
        "compliance": compliance,
        "loss": loss,
        "guide_count": len(guides_week),
        "guide_m3": _sum_alias(
            guides_week,
            "CANTIDAD",
            "M3",
            "M3_GUIA",
        ),
    }


def _last_three_weeks(
    weeks: list[dict[str, Any]],
    current_week: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if current_week is None:
        return []

    ordered = sorted_weeks(weeks)
    current_id = _row_week_id(current_week)

    current_index = None
    for idx, row in enumerate(ordered):
        if _row_week_id(row) == current_id:
            current_index = idx
            break

    if current_index is None:
        return [current_week]

    start = max(0, current_index - 2)
    return ordered[start: current_index + 1]


def build_weekly_summary(
    weeks: list[dict[str, Any]],
    current_week: dict[str, Any] | None,
    detail_rows: list[dict[str, Any]],
    guide_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    V1.2.1:
    La producción semanal deja de depender de las columnas virtuales
    almacenadas en INFORME.

    Fuentes:
    - DETALLE_PROGRAMA -> m³ proyectados y geométricos
    - GUIAS -> m³ reales, cantidad de guías y distribución diaria
    - SEMANAS_OBRA_GRUESA -> identifica la semana actual y las dos anteriores
    """

    if current_week is None:
        return {
            "weeks": [],
            "current": {
                "projected": None,
                "real": None,
                "geometric": None,
                "compliance": None,
                "loss": None,
            },
            "daily": [],
            "guides_total": 0,
            "m3_total": 0.0,
        }

    source_weeks = _last_three_weeks(
        weeks,
        current_week,
    )

    metrics = [
        _week_metrics_from_sources(
            week_row,
            detail_rows,
            guide_rows,
        )
        for week_row in source_weeks
    ]

    # Asegura siempre tres posiciones para los minigráficos.
    padded: list[dict[str, Any]] = []
    missing = 3 - len(metrics)

    for _ in range(max(0, missing)):
        padded.append(
            {
                "projected": None,
                "real": None,
                "geometric": None,
                "compliance": None,
                "loss": None,
                "guide_count": 0,
                "guide_m3": 0.0,
            }
        )

    padded.extend(metrics)

    labels = [
        ("Hace 2 semanas", "Hace 2"),
        ("Semana anterior", "Anterior"),
        ("Semana actual", "Actual"),
    ]

    chart_weeks = []
    for metric, (label, short) in zip(padded[-3:], labels):
        chart_weeks.append(
            {
                **metric,
                "label": label,
                "short": short,
            }
        )

    current = chart_weeks[-1]

    current_id = _row_week_id(current_week)
    current_guides = _rows_for_week(
        guide_rows,
        current_id,
    )

    week_start = _week_date(
        current_week,
        end=False,
    )

    day_names = [
        "Lunes",
        "Martes",
        "Miércoles",
        "Jueves",
        "Viernes",
        "Sábado",
    ]

    buckets = [
        {
            "day": day,
            "guides": 0,
            "m3": 0.0,
        }
        for day in day_names
    ]

    other_guides = 0
    other_m3 = 0.0

    for row in current_guides:
        guide_date = parse_appsheet_date(
            pick(
                row,
                "FECHA_EMISION",
                "FECHA",
                default=None,
            )
        )

        qty = to_float_or_none(
            pick(
                row,
                "CANTIDAD",
                "M3",
                "M3_GUIA",
                default=0,
            )
        ) or 0.0

        offset = None
        if week_start and guide_date:
            offset = (guide_date - week_start).days

        if offset is not None and 0 <= offset <= 5:
            buckets[offset]["guides"] += 1
            buckets[offset]["m3"] += qty
        else:
            # Evita que el total de la tabla sea distinto a sus filas.
            # Si aparece una guía sin fecha válida o fuera de lunes-sábado,
            # se hace visible en vez de esconderla dentro del total.
            other_guides += 1
            other_m3 += qty

    daily_rows = list(buckets)

    if other_guides > 0 or abs(other_m3) > 1e-9:
        daily_rows.append(
            {
                "day": "Otros / sin fecha",
                "guides": other_guides,
                "m3": other_m3,
            }
        )

    guides_total = sum(
        row["guides"]
        for row in daily_rows
    )
    m3_total = sum(
        row["m3"]
        for row in daily_rows
    )

    # El KPI M³ reales debe coincidir con el total de guías de la tabla.
    current["real"] = m3_total
    current["guide_count"] = guides_total
    current["guide_m3"] = m3_total

    if current.get("projected") not in (None, 0):
        current["compliance"] = (
            m3_total / current["projected"]
        )
    else:
        current["compliance"] = None

    if m3_total > 0 and current.get("geometric") is not None:
        current["loss"] = max(
            (m3_total - current["geometric"]) / m3_total,
            0.0,
        )
    else:
        current["loss"] = None

    # Reemplazar también la última semana de la serie de tendencias
    # con los valores reconciliados de la tabla diaria.
    chart_weeks[-1] = current

    return {
        "weeks": chart_weeks,
        "current": current,
        "daily": daily_rows,
        "guides_total": guides_total,
        "m3_total": m3_total,
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
