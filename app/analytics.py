from __future__ import annotations

from datetime import date, timedelta
from typing import Any
import unicodedata

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


def _interpolated_date_for_value(
    points: list[tuple[date, float]],
    value: float,
) -> date | None:
    """
    Fecha equivalente del programa para un avance acumulado, interpolada
    linealmente entre semanas. La serie se normaliza como acumulada no
    decreciente para tolerar pequeñas correcciones de datos.
    """
    if not points:
        return None

    ordered = sorted(points, key=lambda item: item[0])
    normalized: list[tuple[date, float]] = []
    running_max: float | None = None

    for point_date, point_value in ordered:
        current = float(point_value)
        if running_max is None or current > running_max:
            running_max = current
        normalized.append((point_date, running_max))

    first_date, first_value = normalized[0]
    last_date, last_value = normalized[-1]

    if value <= first_value:
        return first_date
    if value >= last_value:
        return last_date

    for (d0, v0), (d1, v1) in zip(normalized, normalized[1:]):
        if v0 <= value <= v1:
            if abs(v1 - v0) <= 1e-9:
                return d0
            span_days = max((d1 - d0).days, 0)
            fraction = (value - v0) / (v1 - v0)
            return d0 + timedelta(days=round(span_days * fraction))

    return None


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
    lower_points = [
        (item["date"], item["lower"])
        for item in series
        if item.get("lower") is not None
    ]

    target = max((v for _, v in upper_points), default=None)
    planned_finish = None
    if target is not None:
        dates_at_target = [
            d for d, v in upper_points
            if abs(v - target) <= 1e-6
        ]
        if dates_at_target:
            planned_finish = min(dates_at_target)

    # Desfase ACTUAL contra programa. No es una proyección.
    # ATRASADO se mide contra banda inferior; ADELANTADO contra superior;
    # EN RANGO equivale a 0 días. La fecha se interpola entre semanas.
    reference_date = cutoff or _week_date(current_week, end=True)
    schedule_equivalent_date = None
    schedule_delay_days = None

    if reference_date is not None:
        if state == "ATRASADO":
            schedule_equivalent_date = _interpolated_date_for_value(
                lower_points, real
            )
        elif state == "ADELANTADO":
            schedule_equivalent_date = _interpolated_date_for_value(
                upper_points, real
            )
        else:
            schedule_equivalent_date = reference_date

        if schedule_equivalent_date is not None:
            schedule_delay_days = (reference_date - schedule_equivalent_date).days
            if state == "ATRASADO":
                schedule_delay_days = max(schedule_delay_days, 0)
            elif state == "ADELANTADO":
                schedule_delay_days = min(schedule_delay_days, 0)
            else:
                schedule_delay_days = 0

    finish_with_current_delay = None
    if planned_finish is not None and schedule_delay_days is not None:
        finish_with_current_delay = planned_finish + timedelta(
            days=schedule_delay_days
        )

    # Proyección TENDENCIAL según ritmo reciente.
    # Se mantiene independiente del desfase actual y usa las últimas
    # 6 semanas válidas, igual que la versión anterior.
    current_end = _week_date(current_week, end=True) or cutoff
    actual_points = [
        (item["date"], item["real"])
        for item in series
        if item.get("real") is not None
        and current_end is not None
        and item["date"] <= current_end
    ]

    completed_weeks_with_real = len(actual_points)
    projection_available = completed_weeks_with_real >= MIN_PROJECTION_WEEKS
    projection_points = (
        actual_points[-MIN_PROJECTION_WEEKS:] if projection_available else []
    )
    slope = _linear_slope(projection_points) if projection_available else None

    estimated_finish = None
    projection_deviation_days = None

    if projection_available and target is not None and current_end is not None:
        if real >= target:
            estimated_finish = current_end
        elif slope is not None and slope > 0:
            remaining = max(0.0, target - real)
            days_remaining = remaining / slope
            estimated_finish = current_end + timedelta(days=round(days_remaining))

        if estimated_finish and planned_finish:
            projection_deviation_days = (estimated_finish - planned_finish).days

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
        "schedule_equivalent_date": schedule_equivalent_date,
        "schedule_delay_days": schedule_delay_days,
        "finish_with_current_delay": finish_with_current_delay,
        "estimated_finish": estimated_finish,
        "projection_deviation_days": projection_deviation_days,
        "deviation_days": projection_deviation_days,
        "projection_available": projection_available,
        "projection_min_weeks": MIN_PROJECTION_WEEKS,
        "projection_completed_weeks": completed_weeks_with_real,
        "projection_slope_m3_day": slope,
        "projection_points": len(projection_points),
        "series": series,
    }


# ============================================================
# SUMINISTRO Y FACTURACIÓN DE FIERRO
# ============================================================

def _normalize_fierro_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper()
    text = "".join(ch if ch.isalnum() else " " for ch in text)
    return " ".join(text.split())


def _fierro_project(
    data: dict[str, Any],
    summary_rows: list[dict[str, Any]],
) -> str:
    """
    Resuelve el nombre usado por las tablas de fierro.

    Ejemplo actual:
    OBRA[NOMBRE_OBRA] = "Hotel Bellet"
    tablas de fierro[PROYECTO] = "Bellet"
    """
    explicit = pick(
        data,
        "FIERRO_PROYECTO",
        "PROYECTO_FIERRO",
        default=None,
    )
    candidates = [
        explicit,
        data.get("NOMBRE_OBRA"),
        data.get("DIRECCION_OBRA"),
    ]
    normalized_candidates = [
        _normalize_fierro_text(value)
        for value in candidates
        if str(value or "").strip()
    ]

    for row in summary_rows:
        project = str(row.get("PROYECTO") or "").strip()
        project_norm = _normalize_fierro_text(project)
        if not project_norm:
            continue
        for candidate in normalized_candidates:
            if project_norm == candidate or project_norm in candidate or candidate in project_norm:
                return project

    if explicit not in (None, ""):
        return str(explicit).strip()

    name = str(data.get("NOMBRE_OBRA") or "").strip()
    name_norm = _normalize_fierro_text(name)
    if "BELLET" in name_norm:
        return "Bellet"
    if "PATIO DOBLADO" in name_norm or "PATIO" in name_norm:
        return "Patio Doblado"
    return name


def _same_fierro_project(value: Any, target: str) -> bool:
    left = _normalize_fierro_text(value)
    right = _normalize_fierro_text(target)
    if not left or not right:
        return False
    return left == right or left in right or right in left


def _fierro_row_date(row: dict[str, Any], *keys: str) -> date | None:
    return parse_appsheet_date(pick(row, *keys, default=None))


def _fierro_before_cutoff(
    row: dict[str, Any],
    cutoff: date | None,
    *date_keys: str,
) -> bool:
    if cutoff is None:
        return True
    row_date = _fierro_row_date(row, *date_keys)
    return row_date is not None and row_date <= cutoff


def _diameter_label(value: Any) -> str:
    n = to_float_or_none(value)
    if n is None:
        return str(value or "—")
    if abs(n - round(n)) <= 1e-9:
        return f"Ø{int(round(n))}"
    return f"Ø{n:.1f}".replace(".", ",")


def _diameter_sort_key(label: str) -> tuple[int, float | str]:
    raw = str(label).replace("Ø", "").replace(",", ".").strip()
    try:
        return (0, float(raw))
    except ValueError:
        return (1, raw)


def _zero_small_difference(value: float, base: float, tolerance: float = 0.01) -> float:
    value = max(float(value), 0.0)
    if base > 0 and value / base <= tolerance:
        return 0.0
    return value


def build_fierro_summary(
    data: dict[str, Any],
    summary_rows: list[dict[str, Any]],
    order_rows: list[dict[str, Any]],
    order_detail_rows: list[dict[str, Any]],
    guide_rows: list[dict[str, Any]],
    guide_detail_rows: list[dict[str, Any]],
    assignment_rows: list[dict[str, Any]],
    invoice_rows: list[dict[str, Any]],
    invoice_detail_rows: list[dict[str, Any]],
    cutoff: date | None,
    week_start: date | None,
    week_end: date | None,
) -> dict[str, Any]:
    """
    Resumen ejecutivo de SUMINISTRO de fierro.

    Importante: "recibido" describe material ingresado a obra respaldado por
    guías. No representa fierro instalado ni avance físico de estructura.
    Todos los acumulados respetan FECHA_CORTE para que un informe histórico no
    incorpore documentos posteriores.
    """
    project = _fierro_project(data, summary_rows)

    budget_row = next(
        (
            row for row in summary_rows
            if _same_fierro_project(row.get("PROYECTO"), project)
        ),
        None,
    )
    budget_kg = to_float_or_none((budget_row or {}).get("KG_PRESUPUESTO"))
    budget_price_kg = to_float_or_none(
        (budget_row or {}).get("PRECIO_PRESUPUESTO_KG")
    )

    selected_orders = [
        row for row in order_rows
        if _same_fierro_project(row.get("PROYECTO"), project)
        and _fierro_before_cutoff(row, cutoff, "FECHA_PEDIDO")
    ]
    order_ids = {
        str(
            pick(
                row,
                "ID_PEDIDO_FIERRO",
                "ID_PEDIDO_FIERRO ",
                default="",
            )
            or ""
        ).strip()
        for row in selected_orders
    }
    order_ids.discard("")

    selected_order_details = [
        row for row in order_detail_rows
        if str(row.get("ID_PEDIDO_FIERRO") or "").strip() in order_ids
    ]
    requested_kg = sum(
        to_float_or_none(row.get("KG_SOLICITADOS")) or 0.0
        for row in selected_order_details
    )

    selected_guides = [
        row for row in guide_rows
        if _same_fierro_project(row.get("PROYECTO"), project)
        and _fierro_before_cutoff(row, cutoff, "FECHA_GUIA")
    ]
    guide_ids = {
        str(row.get("ID_GUIA_FIERRO") or "").strip()
        for row in selected_guides
        if str(row.get("ID_GUIA_FIERRO") or "").strip()
    }
    selected_guide_details = [
        row for row in guide_detail_rows
        if str(row.get("ID_GUIA_FIERRO") or "").strip() in guide_ids
    ]
    received_kg = sum(
        to_float_or_none(row.get("TOTAL_KG_DESPACHADOS")) or 0.0
        for row in selected_guides
    )

    selected_assignments = [
        row for row in assignment_rows
        if str(row.get("ID_GUIA_FIERRO") or "").strip() in guide_ids
    ]
    assigned_to_orders_kg = sum(
        to_float_or_none(row.get("KG_ASIGNADOS")) or 0.0
        for row in selected_assignments
    )
    assigned_to_orders_kg = min(assigned_to_orders_kg, received_kg)
    received_without_order_kg = _zero_small_difference(
        received_kg - assigned_to_orders_kg,
        received_kg,
    )

    selected_invoices = [
        row for row in invoice_rows
        if _same_fierro_project(row.get("PROYECTO"), project)
        and _fierro_before_cutoff(row, cutoff, "FECHA_EMISION")
    ]
    invoice_ids = {
        str(row.get("ID_FACTURA_FIERRO") or "").strip()
        for row in selected_invoices
        if str(row.get("ID_FACTURA_FIERRO") or "").strip()
    }
    selected_invoice_details = [
        row for row in invoice_detail_rows
        if str(row.get("ID_FACTURA_FIERRO") or "").strip() in invoice_ids
    ]

    invoiced_kg = sum(
        to_float_or_none(row.get("TOTAL_KG_FACTURADOS")) or 0.0
        for row in selected_invoices
    )
    net_invoiced = sum(
        to_float_or_none(row.get("NETO_FACTURA")) or 0.0
        for row in selected_invoices
    )

    # El precio usado para estimar lo pendiente se toma sólo desde facturas
    # validadas, para que una factura observada no distorsione el promedio.
    validated_invoices_for_price = [
        row for row in selected_invoices
        if str(row.get("ESTADO_REVISION") or "").strip().upper() == "VALIDADA"
    ]
    validated_price_kg = sum(
        to_float_or_none(row.get("TOTAL_KG_FACTURADOS")) or 0.0
        for row in validated_invoices_for_price
    )
    validated_price_net = sum(
        to_float_or_none(row.get("NETO_FACTURA")) or 0.0
        for row in validated_invoices_for_price
    )
    avg_price_kg = (
        validated_price_net / validated_price_kg
        if validated_price_kg > 0
        else None
    )

    pending_receive_kg = max(requested_kg - received_kg, 0.0)
    pending_invoice_kg = max(received_kg - invoiced_kg, 0.0)
    invoiced_without_received_kg = _zero_small_difference(
        invoiced_kg - received_kg,
        invoiced_kg,
    )
    estimated_net_pending = (
        pending_invoice_kg * avg_price_kg
        if avg_price_kg is not None
        else None
    )
    if pending_invoice_kg <= 1e-9:
        net_committed = net_invoiced
    elif estimated_net_pending is not None:
        net_committed = net_invoiced + estimated_net_pending
    else:
        net_committed = None

    requested_ratio_budget = (
        requested_kg / budget_kg
        if budget_kg is not None and budget_kg > 0
        else None
    )
    received_ratio_budget = (
        received_kg / budget_kg
        if budget_kg is not None and budget_kg > 0
        else None
    )
    invoiced_ratio_received = (
        invoiced_kg / received_kg
        if received_kg > 0
        else None
    )
    order_reconciliation_ratio = (
        assigned_to_orders_kg / received_kg
        if received_kg > 0
        else None
    )
    invoice_coverage_ratio = (
        min(invoiced_kg, received_kg) / received_kg
        if received_kg > 0
        else None
    )

    requested_by_diameter: dict[str, float] = {}
    for row in selected_order_details:
        label = _diameter_label(row.get("DIAMETRO_MM"))
        requested_by_diameter[label] = (
            requested_by_diameter.get(label, 0.0)
            + (to_float_or_none(row.get("KG_SOLICITADOS")) or 0.0)
        )

    received_by_diameter: dict[str, float] = {}
    for row in selected_guide_details:
        label = _diameter_label(row.get("DIAMETRO_MM"))
        received_by_diameter[label] = (
            received_by_diameter.get(label, 0.0)
            + (to_float_or_none(row.get("KG_DESPACHADOS")) or 0.0)
        )

    invoiced_by_diameter: dict[str, float] = {}
    for row in selected_invoice_details:
        label = _diameter_label(row.get("DIAMETRO_MM"))
        invoiced_by_diameter[label] = (
            invoiced_by_diameter.get(label, 0.0)
            + (to_float_or_none(row.get("KG_FACTURADOS")) or 0.0)
        )

    diameter_rows: list[dict[str, Any]] = []
    for label in sorted(
        set(requested_by_diameter) | set(received_by_diameter) | set(invoiced_by_diameter),
        key=_diameter_sort_key,
    ):
        requested_d = requested_by_diameter.get(label, 0.0)
        received_d = received_by_diameter.get(label, 0.0)
        invoiced_d = invoiced_by_diameter.get(label, 0.0)
        diameter_rows.append(
            {
                "diameter": label,
                "requested": requested_d,
                "received": received_d,
                "invoiced": invoiced_d,
                "pending_receive": max(requested_d - received_d, 0.0),
                "received_ratio_requested": (
                    received_d / requested_d if requested_d > 0 else None
                ),
            }
        )

    guide_statuses = [
        str(row.get("ESTADO_REVISION") or "").strip().upper()
        for row in selected_guides
    ]
    invoice_statuses = [
        str(row.get("ESTADO_REVISION") or "").strip().upper()
        for row in selected_invoices
    ]
    guide_alert_count = sum(
        1 for status in guide_statuses
        if status.startswith("REVISAR") or status.startswith("ERROR")
    )
    guide_pending_count = sum(1 for status in guide_statuses if status == "PENDIENTE")
    invoice_validated_count = sum(1 for status in invoice_statuses if status == "VALIDADA")
    invoice_alert_count = sum(1 for status in invoice_statuses if status != "VALIDADA")

    current_end = week_end or cutoff
    current_start = week_start
    if current_end is not None and current_start is None:
        current_start = current_end - timedelta(days=6)

    guides_week = []
    invoices_week = []
    if current_start is not None and current_end is not None:
        guides_week = [
            row for row in selected_guides
            if (
                (d := _fierro_row_date(row, "FECHA_GUIA")) is not None
                and current_start <= d <= current_end
            )
        ]
        invoices_week = [
            row for row in selected_invoices
            if (
                (d := _fierro_row_date(row, "FECHA_EMISION")) is not None
                and current_start <= d <= current_end
            )
        ]

    weekly_trend: list[dict[str, Any]] = []
    if current_start is not None and current_end is not None:
        labels = ["Hace 2 semanas", "Semana anterior", "Semana actual"]
        for idx, weeks_back in enumerate((2, 1, 0)):
            start = current_start - timedelta(days=7 * weeks_back)
            end = current_end - timedelta(days=7 * weeks_back)
            g_rows = [
                row for row in selected_guides
                if (
                    (d := _fierro_row_date(row, "FECHA_GUIA")) is not None
                    and start <= d <= end
                )
            ]
            i_rows = [
                row for row in selected_invoices
                if (
                    (d := _fierro_row_date(row, "FECHA_EMISION")) is not None
                    and start <= d <= end
                )
            ]
            weekly_trend.append(
                {
                    "label": labels[idx],
                    "start": start,
                    "end": end,
                    "guides": len(g_rows),
                    "received_kg": sum(
                        to_float_or_none(row.get("TOTAL_KG_DESPACHADOS")) or 0.0
                        for row in g_rows
                    ),
                    "invoices": len(i_rows),
                    "invoiced_kg": sum(
                        to_float_or_none(row.get("TOTAL_KG_FACTURADOS")) or 0.0
                        for row in i_rows
                    ),
                }
            )

    alerts: list[str] = []
    if received_without_order_kg > 0:
        alerts.append(
            f"{received_without_order_kg:.0f} kg recibidos sin pedido conciliado."
        )
    if invoiced_without_received_kg > 0:
        alerts.append(
            f"{invoiced_without_received_kg:.0f} kg facturados por sobre lo recibido al corte."
        )
    if guide_alert_count > 0:
        alerts.append(f"{guide_alert_count} guía(s) requieren revisión.")
    if invoice_alert_count > 0:
        alerts.append(f"{invoice_alert_count} factura(s) no están validadas.")

    available = bool(
        budget_row
        or selected_orders
        or selected_guides
        or selected_invoices
    )

    return {
        "available": available,
        "project": project,
        "cutoff": cutoff,
        "budget_kg": budget_kg,
        "budget_price_kg": budget_price_kg,
        "requested_kg": requested_kg,
        "received_kg": received_kg,
        "invoiced_kg": invoiced_kg,
        "pending_receive_kg": pending_receive_kg,
        "pending_invoice_kg": pending_invoice_kg,
        "received_without_order_kg": received_without_order_kg,
        "invoiced_without_received_kg": invoiced_without_received_kg,
        "requested_ratio_budget": requested_ratio_budget,
        "received_ratio_budget": received_ratio_budget,
        "invoiced_ratio_received": invoiced_ratio_received,
        "assigned_to_orders_kg": assigned_to_orders_kg,
        "order_reconciliation_ratio": order_reconciliation_ratio,
        "invoice_coverage_ratio": invoice_coverage_ratio,
        "net_invoiced": net_invoiced,
        "avg_price_kg": avg_price_kg,
        "estimated_net_pending": estimated_net_pending,
        "net_committed": net_committed,
        "diameters": diameter_rows,
        "orders_count": len(selected_orders),
        "guides_count": len(selected_guides),
        "invoices_count": len(selected_invoices),
        "guides_week": len(guides_week),
        "invoices_week": len(invoices_week),
        "received_week_kg": sum(
            to_float_or_none(row.get("TOTAL_KG_DESPACHADOS")) or 0.0
            for row in guides_week
        ),
        "invoiced_week_kg": sum(
            to_float_or_none(row.get("TOTAL_KG_FACTURADOS")) or 0.0
            for row in invoices_week
        ),
        "guide_alert_count": guide_alert_count,
        "guide_pending_count": guide_pending_count,
        "invoice_validated_count": invoice_validated_count,
        "invoice_alert_count": invoice_alert_count,
        "weekly_trend": weekly_trend,
        "alerts": alerts,
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
