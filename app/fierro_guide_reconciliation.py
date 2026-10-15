from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .appsheet_client import AppSheetClient


TABLE_GUIAS = os.getenv(
    "FIERRO_GUIAS_TABLE", "FIERRO_GUIAS"
).strip() or "FIERRO_GUIAS"

TABLE_GUIAS_DETALLE = os.getenv(
    "FIERRO_GUIAS_DETALLE_TABLE", "FIERRO_GUIAS_DETALLE"
).strip() or "FIERRO_GUIAS_DETALLE"

TABLE_ASIGNACIONES = os.getenv(
    "FIERRO_GUIAS_PEDIDOS_TABLE", "FIERRO_GUIAS_PEDIDOS"
).strip() or "FIERRO_GUIAS_PEDIDOS"

# Reutiliza las mismas variables que ya usa el módulo de pedidos.
TABLE_PEDIDOS = os.getenv(
    "FIERRO_PEDIDOS_TABLE", "PEDIDOS_FIERRO"
).strip() or "PEDIDOS_FIERRO"

TABLE_PEDIDOS_DETALLE = os.getenv(
    "FIERRO_PEDIDOS_DETALLE_TABLE", "PEDIDOS_FIERRO_DETALLE"
).strip() or "PEDIDOS_FIERRO_DETALLE"

GUIA_KEY = "ID_GUIA_FIERRO"
GUIA_DETALLE_KEY = "ID_DETALLE_GUIA"
PEDIDO_KEY = "ID_PEDIDO_FIERRO"
PEDIDO_DETALLE_KEY = "ID_DETALLE_PEDIDO"
ASIGNACION_KEY = "ID_GUIA_PEDIDO"

AUTO = "AUTOMATICA"
MANUAL = "MANUAL"
TOLERANCE = Decimal("0.01")


@dataclass(frozen=True)
class ReconciliationResult:
    assignments_created: int
    orders_linked: int
    kg_assigned_auto: Decimal
    kg_assigned_manual: Decimal
    kg_unassigned: Decimal
    details_with_balance: int
    warnings: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "asignaciones_creadas": self.assignments_created,
            "pedidos_vinculados": self.orders_linked,
            "kg_asignados_automaticos": float(self.kg_assigned_auto),
            "kg_asignados_manuales": float(self.kg_assigned_manual),
            "kg_sin_asignar": float(self.kg_unassigned),
            "detalles_con_saldo": self.details_with_balance,
            "advertencias": list(self.warnings),
        }


def _stable_id(prefix: str, *parts: Any, length: int = 16) -> str:
    raw = "|".join(str(part or "").strip() for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}{digest}"


def _to_decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))

    text = str(value).strip().replace(" ", "")
    if not text:
        return Decimal("0")

    # AppSheet puede devolver 4,001.19 o 4001,19 según la configuración.
    if "," in text and "." in text:
        if text.rfind(".") > text.rfind(","):
            text = text.replace(",", "")
        else:
            text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        tail = text.rsplit(",", 1)[-1]
        if len(tail) <= 2:
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")

    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal("0")


def _to_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return 0


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value or "").strip()
    if not text:
        return None

    # AppSheet está configurado en en-US; ISO también se usa en los servicios nuevos.
    formats = (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y/%m/%d",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _same_material(a: dict[str, Any], b: dict[str, Any]) -> bool:
    diameter_a = _to_decimal(a.get("DIAMETRO_MM"))
    diameter_b = _to_decimal(b.get("DIAMETRO_MM"))
    length_a = _to_decimal(a.get("LARGO_M"))
    length_b = _to_decimal(b.get("LARGO_M"))
    return abs(diameter_a - diameter_b) <= Decimal("0.001") and abs(
        length_a - length_b
    ) <= Decimal("0.001")


def _strip_previous_note(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    marker = "[Conciliación pedidos]"
    if marker in text:
        text = text.split(marker, 1)[0].rstrip()
    return text


def _apply_review(
    appsheet: AppSheetClient,
    guide: dict[str, Any],
    result: ReconciliationResult,
) -> None:
    guide_id = str(guide.get(GUIA_KEY) or "").strip()
    if not guide_id:
        return

    current_status = str(guide.get("ESTADO_REVISION") or "PENDIENTE").strip().upper()
    structural_statuses = {"REVISAR_MONTO", "REVISAR_CANTIDAD", "ERROR"}

    if current_status in structural_statuses:
        status = current_status
    elif result.kg_unassigned > TOLERANCE or result.warnings:
        status = "REVISAR_PEDIDO"
    else:
        # La guía queda pendiente hasta la conciliación con factura.
        status = "PENDIENTE"

    if result.kg_unassigned > TOLERANCE:
        reconciliation_note = (
            f"[Conciliación pedidos] Asignación automática parcial: "
            f"{result.kg_unassigned.normalize()} kg de guía sin pedido compatible. "
            "Revisar asignación manual."
        )
    elif result.warnings:
        reconciliation_note = (
            "[Conciliación pedidos] Requiere revisión: " + " ".join(result.warnings)
        )
    else:
        reconciliation_note = (
            "[Conciliación pedidos] Material de guía conciliado con pedidos por "
            "proyecto, diámetro y largo. Se priorizó el pedido vigente más reciente "
            "anterior a la guía. Pendiente conciliación con factura."
        )

    base = _strip_previous_note(guide.get("OBSERVACION_REVISION"))
    observation = f"{base} {reconciliation_note}".strip()[:1800]

    appsheet.edit_row(
        TABLE_GUIAS,
        {
            GUIA_KEY: guide_id,
            "ESTADO_REVISION": status,
            "OBSERVACION_REVISION": observation,
        },
    )


def reconcile_guide_orders(
    appsheet: AppSheetClient,
    guide_id: str,
) -> ReconciliationResult:
    """Concilia una guía contra pedidos por línea de material.

    Reglas:
    - mismo PROYECTO;
    - mismo DIAMETRO_MM y LARGO_M;
    - pedido emitido/requerido no posterior a la guía;
    - conserva asignaciones MANUALES;
    - recalcula únicamente asignaciones AUTOMATICAS de la guía actual;
    - prioriza el pedido más reciente anterior a la guía. Esta prioridad evita que,
      cuando faltan guías históricas, una guía nueva consuma primero saldos antiguos.
    """

    guide_rows = appsheet.find_rows(
        TABLE_GUIAS,
        key_rows=[{GUIA_KEY: guide_id}],
    )
    if not guide_rows:
        raise RuntimeError(f"No se encontró {TABLE_GUIAS}[{GUIA_KEY}]={guide_id!r}.")
    guide = guide_rows[0]

    project = str(guide.get("PROYECTO") or "").strip()
    guide_date = _parse_date(guide.get("FECHA_GUIA"))

    guide_details = [
        row
        for row in appsheet.find_rows(TABLE_GUIAS_DETALLE)
        if str(row.get(GUIA_KEY) or "").strip() == guide_id
        and str(row.get(GUIA_DETALLE_KEY) or "").strip()
    ]

    assignments = appsheet.find_rows(TABLE_ASIGNACIONES)
    current_auto = [
        row
        for row in assignments
        if str(row.get(GUIA_KEY) or "").strip() == guide_id
        and str(row.get("TIPO_ASIGNACION") or "").strip().upper() == AUTO
        and str(row.get(ASIGNACION_KEY) or "").strip()
    ]
    retained = [row for row in assignments if row not in current_auto]

    order_rows = appsheet.find_rows(TABLE_PEDIDOS)
    orders: dict[str, dict[str, Any]] = {
        str(row.get(PEDIDO_KEY) or "").strip(): row
        for row in order_rows
        if str(row.get(PEDIDO_KEY) or "").strip()
    }

    order_details = [
        row
        for row in appsheet.find_rows(TABLE_PEDIDOS_DETALLE)
        if str(row.get(PEDIDO_DETALLE_KEY) or "").strip()
        and str(row.get(PEDIDO_KEY) or "").strip() in orders
    ]

    assigned_to_order_detail: dict[str, Decimal] = {}
    manual_by_guide_detail: dict[str, Decimal] = {}
    for row in retained:
        kg = _to_decimal(row.get("KG_ASIGNADOS"))
        order_detail_id = str(row.get(PEDIDO_DETALLE_KEY) or "").strip()
        if order_detail_id:
            assigned_to_order_detail[order_detail_id] = (
                assigned_to_order_detail.get(order_detail_id, Decimal("0")) + kg
            )

        if str(row.get(GUIA_KEY) or "").strip() == guide_id:
            guide_detail_id = str(row.get(GUIA_DETALLE_KEY) or "").strip()
            if guide_detail_id:
                manual_by_guide_detail[guide_detail_id] = (
                    manual_by_guide_detail.get(guide_detail_id, Decimal("0")) + kg
                )

    warnings: list[str] = []
    new_rows: list[dict[str, Any]] = []
    linked_order_ids: set[str] = set()
    kg_auto = Decimal("0")
    kg_manual = sum(manual_by_guide_detail.values(), Decimal("0"))
    kg_unassigned = Decimal("0")
    details_with_balance = 0

    # Ordenamos para obtener resultados deterministas.
    guide_details.sort(key=lambda row: str(row.get(GUIA_DETALLE_KEY) or ""))

    for guide_detail in guide_details:
        guide_detail_id = str(guide_detail.get(GUIA_DETALLE_KEY) or "").strip()
        guide_kg = _to_decimal(guide_detail.get("KG_DESPACHADOS"))
        manual_kg = manual_by_guide_detail.get(guide_detail_id, Decimal("0"))
        remaining_guide = guide_kg - manual_kg

        if remaining_guide < -TOLERANCE:
            warnings.append(
                f"Detalle {guide_detail_id}: asignación manual {manual_kg} kg "
                f"supera los {guide_kg} kg despachados."
            )
            remaining_guide = Decimal("0")
        elif remaining_guide <= TOLERANCE:
            continue

        candidates: list[tuple[date, date, int, str, dict[str, Any], dict[str, Any]]] = []
        for order_detail in order_details:
            if not _same_material(guide_detail, order_detail):
                continue

            order_id = str(order_detail.get(PEDIDO_KEY) or "").strip()
            order = orders.get(order_id)
            if not order:
                continue

            if project and str(order.get("PROYECTO") or "").strip() != project:
                continue

            processing_status = str(order.get("ESTADO_PROCESAMIENTO") or "").strip().upper()
            if processing_status and processing_status != "PROCESADO":
                continue

            order_date = _parse_date(order.get("FECHA_PEDIDO")) or date.min
            required_date = _parse_date(order.get("FECHA_REQUERIDA_OBRA")) or order_date
            effective_date = required_date if required_date != date.min else order_date

            if guide_date and effective_date != date.min and effective_date > guide_date:
                continue

            order_detail_id = str(order_detail.get(PEDIDO_DETALLE_KEY) or "").strip()
            requested = _to_decimal(order_detail.get("KG_SOLICITADOS"))
            already = assigned_to_order_detail.get(order_detail_id, Decimal("0"))
            pending = requested - already
            if pending <= TOLERANCE:
                continue

            # Más reciente primero: fecha requerida, fecha pedido, N_PEDIDO.
            candidates.append(
                (
                    effective_date,
                    order_date,
                    _to_int(order.get("N_PEDIDO")),
                    order_detail_id,
                    order,
                    order_detail,
                )
            )

        candidates.sort(key=lambda item: (item[0], item[1], item[2], item[3]), reverse=True)

        for _effective, _order_date, _number, order_detail_id, order, order_detail in candidates:
            if remaining_guide <= TOLERANCE:
                break

            requested = _to_decimal(order_detail.get("KG_SOLICITADOS"))
            already = assigned_to_order_detail.get(order_detail_id, Decimal("0"))
            pending = requested - already
            if pending <= TOLERANCE:
                continue

            assigned = min(remaining_guide, pending)
            if assigned <= TOLERANCE:
                continue

            order_id = str(order.get(PEDIDO_KEY) or "").strip()
            assignment_id = _stable_id(
                "FGP_",
                guide_id,
                guide_detail_id,
                order_detail_id,
                AUTO,
            )
            new_rows.append(
                {
                    ASIGNACION_KEY: assignment_id,
                    GUIA_KEY: guide_id,
                    PEDIDO_KEY: order_id,
                    GUIA_DETALLE_KEY: guide_detail_id,
                    PEDIDO_DETALLE_KEY: order_detail_id,
                    "KG_ASIGNADOS": float(assigned),
                    "TIPO_ASIGNACION": AUTO,
                    "OBSERVACION": (
                        "Asignación automática por coincidencia exacta de proyecto, "
                        "diámetro y largo; prioridad al pedido más reciente anterior "
                        "a la guía."
                    ),
                }
            )
            assigned_to_order_detail[order_detail_id] = already + assigned
            remaining_guide -= assigned
            kg_auto += assigned
            linked_order_ids.add(order_id)

        if remaining_guide > TOLERANCE:
            kg_unassigned += remaining_guide
            details_with_balance += 1

    # Sólo después de calcular el nuevo reparto eliminamos el cálculo automático anterior.
    if current_auto:
        appsheet.delete_rows(
            TABLE_ASIGNACIONES,
            [{ASIGNACION_KEY: row[ASIGNACION_KEY]} for row in current_auto],
        )
    if new_rows:
        appsheet.add_rows(TABLE_ASIGNACIONES, new_rows)

    result = ReconciliationResult(
        assignments_created=len(new_rows),
        orders_linked=len(linked_order_ids),
        kg_assigned_auto=kg_auto,
        kg_assigned_manual=kg_manual,
        kg_unassigned=kg_unassigned,
        details_with_balance=details_with_balance,
        warnings=tuple(warnings),
    )
    _apply_review(appsheet, guide, result)
    return result
