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

# Número mínimo de semanas cerradas con avance real antes de
# publicar una proyección de término en el informe ejecutivo.
MIN_PROJECTION_WEEKS = 6


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

    # Proyección lineal del ritmo reciente.
    #
    # V1.2.5:
    # No se publica una fecha estimada hasta contar con al menos
    # 6 semanas cerradas que tengan un valor real acumulado.
    #
    # Una vez alcanzado el mínimo, la pendiente se calcula usando
    # precisamente las últimas 6 semanas válidas. Esto evita que las
    # primeras semanas de excavación / arranque generen proyecciones
    # extremadamente inestables.
    current_end = _week_date(current_week, end=True) or cutoff
    actual_points = [
        (item["date"], item["real"])
        for item in series
        if item.get("real") is not None
        and current_end is not None
        and item["date"] <= current_end
    ]

    completed_weeks_with_real = len(actual_points)
    projection_available = (
        completed_weeks_with_real >= MIN_PROJECTION_WEEKS
    )

    projection_points = (
        actual_points[-MIN_PROJECTION_WEEKS:]
        if projection_available
        else []
    )

    slope = (
        _linear_slope(projection_points)
        if projection_available
        else None
    )

    estimated_finish = None
    deviation_days = None

    if (
        projection_available
        and target is not None
        and current_end is not None
    ):
        if real >= target:
            estimated_finish = current_end
        elif slope is not None and slope > 0:
            remaining = max(0.0, target - real)
            days_remaining = remaining / slope
            estimated_finish = current_end + timedelta(
                days=round(days_remaining)
            )

        if estimated_finish and planned_finish:
            deviation_days = (
                estimated_finish - planned_finish
            ).days

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
        "projection_available": projection_available,
        "projection_min_weeks": MIN_PROJECTION_WEEKS,
        "projection_completed_weeks": completed_weeks_with_real,
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


def _program_week_id(row: dict[str, Any]) -> str:
    return str(
        pick(
            row,
            "ID_SEMANA_OBRA_GRUE",
            "ID_SEMANA_OBRA_GRUESA",
            default="",
        )
    ).strip()


def _program_metric_row(
    program_rows: list[dict[str, Any]],
    week_id: Any,
) -> dict[str, Any] | None:
    target = str(week_id or "").strip()
    if not target:
        return None

    matches = [
        row for row in program_rows
        if _program_week_id(row) == target
    ]

    if not matches:
        return None

    # Si por alguna razón existen varias filas para la misma semana,
    # usar la última físicamente disponible.
    matches.sort(
        key=lambda row: (
            int(to_float_or_none(row.get("_RowNumber")) or 0),
            str(row.get("ID_SEMANA_PROGRAMA", "")),
        )
    )
    return matches[-1]


def _program_metrics(
    program_row: dict[str, Any] | None,
) -> dict[str, Any]:
    if not program_row:
        return {
            "projected": None,
            "real": None,
            "geometric": None,
            "compliance": None,
            "loss": None,
        }

    return {
        "projected": to_float_or_none(
            pick(
                program_row,
                "M3 PROGRAMADOS",
                "M3_PROGRAMADOS",
                default=None,
            )
        ),
        "real": to_float_or_none(
            pick(
                program_row,
                "M3 REALES",
                "M3_REALES",
                default=None,
            )
        ),
        "geometric": to_float_or_none(
            pick(
                program_row,
                "M3 GEOMETRICOS",
                "M3_GEOMETRICOS",
                default=None,
            )
        ),
        "compliance": to_percent_ratio(
            pick(
                program_row,
                "% CUMPLIMIENTO SEMANAL",
                "% CUMPLIMIENTO SEMA",
                "%_CUMPLIMIENTO_SEMANAL",
                "CUMPLIMIENTO_SEMANAL",
                default=None,
            )
        ),
        "loss": to_percent_ratio(
            pick(
                program_row,
                "% PERDIDA SEMANAL",
                "%_PERDIDA_SEMANAL",
                "PERDIDA_SEMANAL",
                default=None,
            )
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
    program_rows: list[dict[str, Any]],
    guide_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    V1.2.2

    Fuente oficial de los cinco indicadores semanales y de los cinco
    minigráficos: PROGRAMA_SEMANAL.

    PROGRAMA_SEMANAL contiene una fila por semana con:
    - M3 PROGRAMADOS
    - M3 REALES
    - M3 GEOMETRICOS
    - % CUMPLIMIENTO SEMANAL
    - % PERDIDA SEMANAL

    La tabla diaria de guías sigue construyéndose desde GUIAS porque debe
    mostrar el detalle real por fecha de emisión.
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
            "program_real": None,
            "daily_real_difference": None,
        }

    source_weeks = _last_three_weeks(
        weeks,
        current_week,
    )

    metrics: list[dict[str, Any]] = []
    for week_row in source_weeks:
        week_id = _row_week_id(week_row)
        program_row = _program_metric_row(
            program_rows,
            week_id,
        )
        values = _program_metrics(program_row)
        metrics.append(
            {
                **values,
                "week_id": week_id,
                "program_id": (
                    program_row.get("ID_SEMANA_PROGRAMA")
                    if program_row
                    else None
                ),
            }
        )

    # Siempre tres posiciones para mantener los minigráficos estables.
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
                "week_id": None,
                "program_id": None,
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

    current = dict(chart_weeks[-1])

    # ------------------------------------------------------------
    # Detalle diario de guías de la semana actual
    # ------------------------------------------------------------
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

    # Diagnóstico interno: no altera el KPI de PROGRAMA_SEMANAL.
    program_real = current.get("real")
    difference = None
    if program_real is not None:
        difference = m3_total - program_real

    return {
        "weeks": chart_weeks,
        "current": current,
        "daily": daily_rows,
        "guides_total": guides_total,
        "m3_total": m3_total,
        "program_real": program_real,
        "daily_real_difference": difference,
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
