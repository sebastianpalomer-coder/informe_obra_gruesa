from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from .appsheet_client import AppSheetClient


TABLE_FACTURAS = os.getenv(
    "FIERRO_FACTURAS_TABLE", "FIERRO_FACTURAS"
).strip() or "FIERRO_FACTURAS"

TABLE_FACTURAS_DETALLE = os.getenv(
    "FIERRO_FACTURAS_DETALLE_TABLE", "FIERRO_FACTURAS_DETALLE"
).strip() or "FIERRO_FACTURAS_DETALLE"

TABLE_FACTURA_GUIAS = os.getenv(
    "FIERRO_FACTURAS_GUIAS_TABLE", "FIERRO_FACTURAS_GUIAS"
).strip() or "FIERRO_FACTURAS_GUIAS"

TABLE_GUIAS = os.getenv(
    "FIERRO_GUIAS_TABLE", "FIERRO_GUIAS"
).strip() or "FIERRO_GUIAS"

TABLE_GUIAS_DETALLE = os.getenv(
    "FIERRO_GUIAS_DETALLE_TABLE", "FIERRO_GUIAS_DETALLE"
).strip() or "FIERRO_GUIAS_DETALLE"

FACTURA_KEY = "ID_FACTURA_FIERRO"
FACTURA_DETALLE_KEY = "ID_DETALLE_FACTURA"
FACTURA_GUIA_KEY = "ID_FACTURA_GUIA"
GUIA_KEY = "ID_GUIA_FIERRO"
GUIA_DETALLE_KEY = "ID_DETALLE_GUIA"

EPS_KG = Decimal("0.01")
EPS_PRICE = Decimal("0.01")
EPS_MONEY = Decimal("1")

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InvoiceGuideReconciliationResult:
    invoice_id: str
    status: str
    guides_referenced: int
    guides_linked: int
    lines_invoice: int
    lines_guides: int
    kg_invoice: Decimal
    kg_guides: Decimal
    missing_guides: tuple[str, ...]
    project_mismatches: tuple[str, ...]
    quantity_issues: tuple[str, ...]
    money_issues: tuple[str, ...]
    observation: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id_factura_fierro": self.invoice_id,
            "estado_revision": self.status,
            "guias_referenciadas": self.guides_referenced,
            "guias_vinculadas": self.guides_linked,
            "lineas_factura": self.lines_invoice,
            "lineas_guias": self.lines_guides,
            "kg_factura": float(self.kg_invoice),
            "kg_guias": float(self.kg_guides),
            "guias_faltantes": list(self.missing_guides),
            "diferencias_proyecto": list(self.project_mismatches),
            "diferencias_cantidad": list(self.quantity_issues),
            "diferencias_monto": list(self.money_issues),
            "observacion": self.observation,
        }


def _digits(value: Any) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _to_decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))

    text = str(value).strip()
    if not text:
        return Decimal("0")

    text = text.replace("$", "").replace(" ", "")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        # AppSheet normalmente entrega punto decimal, pero aceptamos coma decimal.
        parts = text.split(",")
        if len(parts[-1]) <= 2:
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")

    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _money_int(value: Any) -> Decimal:
    return _to_decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _norm_hornada(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().upper())


def _material_key(row: dict[str, Any]) -> tuple[Decimal, Decimal, str]:
    return (
        _to_decimal(row.get("DIAMETRO_MM")),
        _to_decimal(row.get("LARGO_M")),
        _norm_hornada(row.get("HORNADA")),
    )


def _fmt_material(key: tuple[Decimal, Decimal, str]) -> str:
    diameter, length, heat = key
    d = f"{diameter.normalize()}"
    l = f"{length.normalize()}"
    return f"Ø{d} x {l} m / {heat or 'SIN HORNADA'}"


def _find_by_key_optional(
    appsheet: AppSheetClient,
    table: str,
    key_name: str,
    key_value: Any,
) -> dict[str, Any] | None:
    rows = appsheet.find_rows(table, key_rows=[{key_name: key_value}])
    return rows[0] if rows else None


def _aggregate_details(
    rows: list[dict[str, Any]],
    *,
    kg_column: str,
) -> dict[tuple[Decimal, Decimal, str], dict[str, Any]]:
    result: dict[tuple[Decimal, Decimal, str], dict[str, Any]] = {}
    for row in rows:
        key = _material_key(row)
        bucket = result.setdefault(
            key,
            {
                "kg": Decimal("0"),
                "total_item": Decimal("0"),
                "prices": set(),
                "rows": 0,
            },
        )
        bucket["kg"] += _to_decimal(row.get(kg_column))
        bucket["total_item"] += _money_int(row.get("TOTAL_ITEM"))
        price = _to_decimal(row.get("PRECIO_KG"))
        bucket["prices"].add(price)
        bucket["rows"] += 1
    return result


def _validate_invoice_internal(
    invoice: dict[str, Any],
    invoice_details: list[dict[str, Any]],
) -> list[str]:
    issues: list[str] = []
    net = _money_int(invoice.get("NETO_FACTURA"))
    iva = _money_int(invoice.get("IVA_FACTURA"))
    total = _money_int(invoice.get("TOTAL_FACTURA"))

    detail_total = sum(
        (_money_int(row.get("TOTAL_ITEM")) for row in invoice_details),
        Decimal("0"),
    )
    if abs(detail_total - net) > EPS_MONEY:
        issues.append(
            f"Factura: suma de ítems ${int(detail_total):,} distinta del neto ${int(net):,}."
        )

    expected_iva = (net * Decimal("0.19")).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    if abs(expected_iva - iva) > EPS_MONEY:
        issues.append(
            f"Factura: IVA esperado ${int(expected_iva):,} distinto de ${int(iva):,}."
        )

    if abs((net + iva) - total) > EPS_MONEY:
        issues.append(
            f"Factura: neto + IVA ${int(net + iva):,} distinto del total ${int(total):,}."
        )

    for row in invoice_details:
        kg = _to_decimal(row.get("KG_FACTURADOS"))
        price = _to_decimal(row.get("PRECIO_KG"))
        item_total = _money_int(row.get("TOTAL_ITEM"))
        expected = (kg * price).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        if abs(expected - item_total) > EPS_MONEY:
            issues.append(
                f"Factura detalle {row.get(FACTURA_DETALLE_KEY) or ''}: "
                f"kg x precio ${int(expected):,} distinto del total ítem ${int(item_total):,}."
            )

    return issues


def _resolve_unlinked_refs(
    appsheet: AppSheetClient,
    invoice: dict[str, Any],
    refs: list[dict[str, Any]],
    guides: list[dict[str, Any]],
) -> None:
    invoice_rut = _digits(invoice.get("RUT_EMISOR"))

    for ref in refs:
        if str(ref.get(GUIA_KEY) or "").strip():
            continue

        ref_number = str(ref.get("N_GUIA") or "").strip()
        if not ref_number:
            continue

        candidates = []
        for guide in guides:
            if str(guide.get("N_GUIA") or "").strip() != ref_number:
                continue
            guide_rut = _digits(guide.get("RUT_EMISOR"))
            if invoice_rut and guide_rut and invoice_rut != guide_rut:
                continue
            candidates.append(guide)

        if len(candidates) != 1:
            continue

        ref_id = str(ref.get(FACTURA_GUIA_KEY) or "").strip()
        guide_id = str(candidates[0].get(GUIA_KEY) or "").strip()
        if not ref_id or not guide_id:
            continue

        appsheet.edit_row(
            TABLE_FACTURA_GUIAS,
            {
                FACTURA_GUIA_KEY: ref_id,
                GUIA_KEY: guide_id,
            },
        )
        ref[GUIA_KEY] = guide_id


def reconcile_invoice_guides(
    appsheet: AppSheetClient,
    invoice_id: str,
) -> InvoiceGuideReconciliationResult:
    invoice_id = str(invoice_id or "").strip()
    if not invoice_id:
        raise RuntimeError("invoice_id está vacío.")

    invoice = _find_by_key_optional(
        appsheet, TABLE_FACTURAS, FACTURA_KEY, invoice_id
    )
    if not invoice:
        raise RuntimeError(
            f"No se encontró {TABLE_FACTURAS}[{FACTURA_KEY}]={invoice_id!r}."
        )

    invoice_details = [
        row
        for row in appsheet.find_rows(TABLE_FACTURAS_DETALLE)
        if str(row.get(FACTURA_KEY) or "").strip() == invoice_id
    ]
    refs = [
        row
        for row in appsheet.find_rows(TABLE_FACTURA_GUIAS)
        if str(row.get(FACTURA_KEY) or "").strip() == invoice_id
    ]
    all_guides = appsheet.find_rows(TABLE_GUIAS)

    # Permite recuperar vínculos históricos donde la referencia tenía N_GUIA,
    # pero todavía no se había completado ID_GUIA_FIERRO.
    _resolve_unlinked_refs(appsheet, invoice, refs, all_guides)

    guides_by_id = {
        str(row.get(GUIA_KEY) or "").strip(): row
        for row in all_guides
        if str(row.get(GUIA_KEY) or "").strip()
    }

    missing_guides: list[str] = []
    linked_guides: list[dict[str, Any]] = []
    seen_guide_ids: set[str] = set()
    for ref in refs:
        guide_number = str(ref.get("N_GUIA") or "").strip() or "SIN N°"
        guide_id = str(ref.get(GUIA_KEY) or "").strip()
        if not guide_id or guide_id not in guides_by_id:
            missing_guides.append(guide_number)
            continue
        if guide_id in seen_guide_ids:
            continue
        seen_guide_ids.add(guide_id)
        linked_guides.append(guides_by_id[guide_id])

    invoice_kg = _to_decimal(invoice.get("TOTAL_KG_FACTURADOS"))
    guide_kg = sum(
        (_to_decimal(row.get("TOTAL_KG_DESPACHADOS")) for row in linked_guides),
        Decimal("0"),
    )

    project_issues: list[str] = []
    quantity_issues: list[str] = []
    money_issues: list[str] = _validate_invoice_internal(invoice, invoice_details)

    invoice_project = str(invoice.get("PROYECTO") or "").strip()
    if not invoice_project:
        project_issues.append("Factura sin proyecto identificado.")

    if refs and not missing_guides:
        for guide in linked_guides:
            guide_project = str(guide.get("PROYECTO") or "").strip()
            guide_number = str(guide.get("N_GUIA") or "").strip()
            if not guide_project:
                project_issues.append(f"Guía {guide_number} sin proyecto identificado.")
            elif invoice_project and guide_project != invoice_project:
                project_issues.append(
                    f"Guía {guide_number}: proyecto {guide_project!r} distinto de "
                    f"factura {invoice_project!r}."
                )

    all_guide_details = appsheet.find_rows(TABLE_GUIAS_DETALLE)
    linked_guide_ids = {
        str(row.get(GUIA_KEY) or "").strip() for row in linked_guides
    }
    guide_details = [
        row
        for row in all_guide_details
        if str(row.get(GUIA_KEY) or "").strip() in linked_guide_ids
    ]

    # Sólo se compara en profundidad cuando están todas las guías referenciadas.
    if refs and not missing_guides:
        if abs(invoice_kg - guide_kg) > EPS_KG:
            quantity_issues.append(
                f"Kg totales: factura {invoice_kg} kg vs guías {guide_kg} kg."
            )

        inv_groups = _aggregate_details(invoice_details, kg_column="KG_FACTURADOS")
        guide_groups = _aggregate_details(guide_details, kg_column="KG_DESPACHADOS")
        all_keys = sorted(
            set(inv_groups) | set(guide_groups),
            key=lambda key: (key[0], key[1], key[2]),
        )

        for key in all_keys:
            inv = inv_groups.get(key)
            gui = guide_groups.get(key)
            label = _fmt_material(key)

            if inv is None:
                quantity_issues.append(
                    f"{label}: aparece en guía(s) pero no en factura ({gui['kg']} kg)."
                )
                continue
            if gui is None:
                quantity_issues.append(
                    f"{label}: aparece en factura pero no en guía(s) ({inv['kg']} kg)."
                )
                continue

            if abs(inv["kg"] - gui["kg"]) > EPS_KG:
                quantity_issues.append(
                    f"{label}: factura {inv['kg']} kg vs guía(s) {gui['kg']} kg."
                )
                continue

            if inv["prices"] != gui["prices"]:
                inv_prices = ", ".join(str(v) for v in sorted(inv["prices"]))
                gui_prices = ", ".join(str(v) for v in sorted(gui["prices"]))
                money_issues.append(
                    f"{label}: precio/kg factura [{inv_prices}] vs guía(s) [{gui_prices}]."
                )

            if abs(inv["total_item"] - gui["total_item"]) > EPS_MONEY:
                money_issues.append(
                    f"{label}: total ítem factura ${int(inv['total_item']):,} "
                    f"vs guía(s) ${int(gui['total_item']):,}."
                )

        guide_net = sum(
            (_money_int(row.get("NETO_GUIA")) for row in linked_guides), Decimal("0")
        )
        guide_iva = sum(
            (_money_int(row.get("IVA_GUIA")) for row in linked_guides), Decimal("0")
        )
        guide_total = sum(
            (_money_int(row.get("TOTAL_GUIA")) for row in linked_guides), Decimal("0")
        )
        invoice_net = _money_int(invoice.get("NETO_FACTURA"))
        invoice_iva = _money_int(invoice.get("IVA_FACTURA"))
        invoice_total = _money_int(invoice.get("TOTAL_FACTURA"))

        if abs(invoice_net - guide_net) > EPS_MONEY:
            money_issues.append(
                f"Neto: factura ${int(invoice_net):,} vs guías ${int(guide_net):,}."
            )
        if abs(invoice_iva - guide_iva) > EPS_MONEY:
            money_issues.append(
                f"IVA: factura ${int(invoice_iva):,} vs guías ${int(guide_iva):,}."
            )
        if abs(invoice_total - guide_total) > EPS_MONEY:
            money_issues.append(
                f"Total: factura ${int(invoice_total):,} vs guías ${int(guide_total):,}."
            )

    if project_issues:
        status = "REVISAR_PEDIDO"
        observation = " ".join(project_issues)
    elif money_issues and not refs:
        # Una factura internamente inconsistente no debe quedar PENDIENTE sólo
        # porque todavía no existan referencias de guía.
        status = "REVISAR_MONTO"
        observation = " ".join(money_issues)
    elif not refs:
        status = "PENDIENTE"
        observation = "Factura sin guías referenciadas para conciliación."
    elif missing_guides:
        status = "PENDIENTE"
        missing_text = ", ".join(sorted(set(missing_guides)))
        prefix = " ".join(money_issues)
        observation = (
            (prefix + " ") if prefix else ""
        ) + f"Pendiente guía(s) de despacho: {missing_text}."
    elif quantity_issues:
        status = "REVISAR_CANTIDAD"
        observation = " ".join(quantity_issues + money_issues)
    elif money_issues:
        status = "REVISAR_MONTO"
        observation = " ".join(money_issues)
    else:
        status = "VALIDADA"
        guide_numbers = ", ".join(
            str(row.get("N_GUIA") or "").strip() for row in linked_guides
        )
        observation = (
            f"Factura validada contra guía(s) {guide_numbers}. "
            f"{len(invoice_details)} líneas de factura conciliadas con "
            f"{len(guide_details)} líneas de guía; "
            f"{invoice_kg} kg facturados = {guide_kg} kg despachados. "
            "Materiales, hornadas, precios, neto, IVA y total coincidentes."
        )

    observation = observation[:1800]
    appsheet.edit_row(
        TABLE_FACTURAS,
        {
            FACTURA_KEY: invoice_id,
            "ESTADO_REVISION": status,
            "OBSERVACION_REVISION": observation,
        },
    )

    result = InvoiceGuideReconciliationResult(
        invoice_id=invoice_id,
        status=status,
        guides_referenced=len(refs),
        guides_linked=len(linked_guides),
        lines_invoice=len(invoice_details),
        lines_guides=len(guide_details),
        kg_invoice=invoice_kg,
        kg_guides=guide_kg,
        missing_guides=tuple(sorted(set(missing_guides))),
        project_mismatches=tuple(project_issues),
        quantity_issues=tuple(quantity_issues),
        money_issues=tuple(money_issues),
        observation=observation,
    )

    logger.info(
        "fierro_invoice_guide_reconciliation invoice=%s status=%s refs=%s linked=%s kg_invoice=%s kg_guides=%s qty_issues=%s money_issues=%s",
        invoice_id,
        status,
        len(refs),
        len(linked_guides),
        invoice_kg,
        guide_kg,
        len(quantity_issues),
        len(money_issues),
    )
    return result


def reconcile_invoices_for_guide(
    appsheet: AppSheetClient,
    guide_id: str,
) -> list[InvoiceGuideReconciliationResult]:
    guide_id = str(guide_id or "").strip()
    if not guide_id:
        return []

    guide = _find_by_key_optional(appsheet, TABLE_GUIAS, GUIA_KEY, guide_id)
    if not guide:
        return []

    guide_number = str(guide.get("N_GUIA") or "").strip()
    guide_rut = _digits(guide.get("RUT_EMISOR"))
    invoices = {
        str(row.get(FACTURA_KEY) or "").strip(): row
        for row in appsheet.find_rows(TABLE_FACTURAS)
        if str(row.get(FACTURA_KEY) or "").strip()
    }

    invoice_ids: set[str] = set()
    refs = appsheet.find_rows(TABLE_FACTURA_GUIAS)
    for ref in refs:
        ref_invoice_id = str(ref.get(FACTURA_KEY) or "").strip()
        if not ref_invoice_id:
            continue

        current_guide_id = str(ref.get(GUIA_KEY) or "").strip()
        same_number = str(ref.get("N_GUIA") or "").strip() == guide_number
        if current_guide_id != guide_id and not same_number:
            continue

        invoice = invoices.get(ref_invoice_id)
        if not invoice:
            continue
        invoice_rut = _digits(invoice.get("RUT_EMISOR"))
        if guide_rut and invoice_rut and guide_rut != invoice_rut:
            continue

        ref_id = str(ref.get(FACTURA_GUIA_KEY) or "").strip()
        if same_number and not current_guide_id and ref_id:
            appsheet.edit_row(
                TABLE_FACTURA_GUIAS,
                {FACTURA_GUIA_KEY: ref_id, GUIA_KEY: guide_id},
            )

        if current_guide_id in {"", guide_id}:
            invoice_ids.add(ref_invoice_id)

    results = [
        reconcile_invoice_guides(appsheet, invoice_id)
        for invoice_id in sorted(invoice_ids)
    ]
    return results
