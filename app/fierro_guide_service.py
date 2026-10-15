from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import unicodedata
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo

from .appsheet_client import AppSheetClient
from .drive_client import DriveClient
from .fierro_guide_parser import FierroGuide, parse_fierro_guide
from .fierro_guide_reconciliation import reconcile_guide_orders


TABLE_PDF = os.getenv(
    "FIERRO_GUIAS_PDF_TABLE", "FIERRO_GUIAS_PDF"
).strip() or "FIERRO_GUIAS_PDF"

TABLE_GUIAS = os.getenv(
    "FIERRO_GUIAS_TABLE", "FIERRO_GUIAS"
).strip() or "FIERRO_GUIAS"

TABLE_DETALLE = os.getenv(
    "FIERRO_GUIAS_DETALLE_TABLE", "FIERRO_GUIAS_DETALLE"
).strip() or "FIERRO_GUIAS_DETALLE"

TABLE_FACTURA_GUIAS = os.getenv(
    "FIERRO_FACTURAS_GUIAS_TABLE", "FIERRO_FACTURAS_GUIAS"
).strip() or "FIERRO_FACTURAS_GUIAS"

TABLE_FACTURAS = os.getenv(
    "FIERRO_FACTURAS_TABLE", "FIERRO_FACTURAS"
).strip() or "FIERRO_FACTURAS"

PDF_KEY = "ID_ARCHIVO"
GUIA_KEY = "ID_GUIA_FIERRO"
DETALLE_KEY = "ID_DETALLE_GUIA"
FACTURA_KEY = "ID_FACTURA_FIERRO"
FACTURA_GUIA_KEY = "ID_FACTURA_GUIA"

APPSHEET_PATH = os.getenv(
    "FIERRO_GUIAS_APPSHEET_PATH", "FIERRO_GUIAS"
).strip().strip("/")

logger = logging.getLogger(__name__)


class FierroGuideServiceError(RuntimeError):
    pass


def _now_appsheet() -> str:
    return datetime.now(ZoneInfo("America/Santiago")).strftime("%m/%d/%Y %H:%M:%S")


def _date_appsheet(value) -> str:
    return value.strftime("%Y-%m-%d") if value else ""


def _datetime_appsheet(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        local = parsed.astimezone(ZoneInfo("America/Santiago"))
        return local.strftime("%m/%d/%Y %H:%M:%S")
    except Exception:
        return value


def _clean_error(exc: Exception) -> str:
    return (str(exc).strip() or exc.__class__.__name__)[:1800]


def _digits(value: Any) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _decimal_appsheet(value: Decimal) -> float:
    return float(value)


def _stable_id(prefix: str, *parts: Any, length: int = 16) -> str:
    raw = "|".join(str(part or "").strip() for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}{digest}"


def _normalize_match_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _project_map() -> dict[str, str]:
    default = {
        "ANTONIO BELLET 225": "Bellet",
        "TUCAPEL 1360": "Patio Doblado",
    }
    raw = os.getenv("FIERRO_GUIA_PROJECT_MAP_JSON", "").strip()
    if not raw:
        return default
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FierroGuideServiceError(
            "FIERRO_GUIA_PROJECT_MAP_JSON no contiene JSON válido."
        ) from exc
    if not isinstance(decoded, dict):
        raise FierroGuideServiceError(
            "FIERRO_GUIA_PROJECT_MAP_JSON debe ser un objeto JSON."
        )
    result = dict(default)
    for key, value in decoded.items():
        if str(key).strip() and str(value).strip():
            result[str(key)] = str(value)
    return result


def _resolve_project(address: str) -> str:
    normalized = _normalize_match_text(address)
    for needle, project in _project_map().items():
        if _normalize_match_text(needle) in normalized:
            return project
    return ""


def _find_by_key_optional(
    appsheet: AppSheetClient, table: str, key_name: str, key_value: Any
) -> dict[str, Any] | None:
    rows = appsheet.find_rows(table, key_rows=[{key_name: key_value}])
    return rows[0] if rows else None


def _validate_guide(guide: FierroGuide, project: str) -> tuple[str, str]:
    notes: list[str] = []
    money_problem = False
    quantity_problem = False

    item_total = sum(item.total_item for item in guide.items)
    if abs(item_total - guide.neto_guia) > 1:
        money_problem = True
        notes.append(
            f"Suma de ítems ${item_total:,} distinta del neto ${guide.neto_guia:,}."
        )

    expected_vat = int(
        (Decimal(guide.neto_guia) * Decimal("0.19")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    if abs(expected_vat - guide.iva_guia) > 1:
        money_problem = True
        notes.append(
            f"IVA esperado ${expected_vat:,} distinto del IVA ${guide.iva_guia:,}."
        )

    expected_total = guide.neto_guia + guide.iva_guia
    if expected_total != guide.total_guia:
        money_problem = True
        notes.append(
            f"Neto + IVA ${expected_total:,} distinto del total ${guide.total_guia:,}."
        )

    if guide.total_kg_documento is not None:
        if abs(guide.total_kg_despachados - guide.total_kg_documento) > Decimal("0.01"):
            quantity_problem = True
            notes.append(
                "Suma detalle "
                f"{guide.total_kg_despachados} kg distinta del total impreso "
                f"{guide.total_kg_documento} kg."
            )

    if money_problem:
        status = "REVISAR_MONTO"
    elif quantity_problem:
        status = "REVISAR_CANTIDAD"
    elif not project:
        status = "REVISAR_PEDIDO"
        notes.append(
            "No se pudo identificar PROYECTO desde la dirección destino: "
            f"{guide.direccion_destino or '[vacía]'}."
        )
    else:
        status = "PENDIENTE"
        notes.append(
            "Estructura, cantidades y montos de guía consistentes. "
            "Pendiente conciliación con pedidos/facturas."
        )

    return status, " ".join(notes)[:1800]


def _delete_children(appsheet: AppSheetClient, guide_id: str) -> None:
    rows = appsheet.find_rows(TABLE_DETALLE)
    keys = [
        {DETALLE_KEY: row.get(DETALLE_KEY)}
        for row in rows
        if str(row.get(GUIA_KEY) or "").strip() == guide_id
        and str(row.get(DETALLE_KEY) or "").strip()
    ]
    if keys:
        appsheet.delete_rows(TABLE_DETALLE, keys)


def _make_appsheet_file_path(name: str) -> str:
    return f"{APPSHEET_PATH}/{name}" if APPSHEET_PATH else name


def _link_existing_invoice_refs(
    appsheet: AppSheetClient, guide: FierroGuide, guide_id: str
) -> int:
    refs = appsheet.find_rows(TABLE_FACTURA_GUIAS)
    if not refs:
        return 0

    invoices = {
        str(row.get(FACTURA_KEY) or "").strip(): row
        for row in appsheet.find_rows(TABLE_FACTURAS)
        if str(row.get(FACTURA_KEY) or "").strip()
    }

    updated = 0
    for ref in refs:
        if str(ref.get("N_GUIA") or "").strip() != str(guide.numero_guia):
            continue

        invoice = invoices.get(str(ref.get(FACTURA_KEY) or "").strip())
        if invoice and _digits(invoice.get("RUT_EMISOR")) != _digits(guide.rut_emisor):
            continue

        ref_key = str(ref.get(FACTURA_GUIA_KEY) or "").strip()
        if not ref_key:
            continue

        current = str(ref.get(GUIA_KEY) or "").strip()
        if current == guide_id:
            continue
        if current and current != guide_id:
            logger.warning(
                "guia_fierro invoice_ref_conflict ref=%s current=%s new=%s",
                ref_key,
                current,
                guide_id,
            )
            continue

        appsheet.edit_row(
            TABLE_FACTURA_GUIAS,
            {FACTURA_GUIA_KEY: ref_key, GUIA_KEY: guide_id},
        )
        updated += 1

    return updated


def process_fierro_guide(
    drive_file_id: str, nombre_archivo: str = ""
) -> dict[str, Any]:
    file_id = str(drive_file_id or "").strip()
    if not file_id:
        raise FierroGuideServiceError("drive_file_id está vacío.")

    appsheet = AppSheetClient()
    drive = DriveClient()

    existing_pdf = _find_by_key_optional(appsheet, TABLE_PDF, PDF_KEY, file_id)
    if existing_pdf:
        existing_status = str(existing_pdf.get("ESTADO_PROCESAMIENTO") or "").upper()
        existing_guide_id = str(existing_pdf.get(GUIA_KEY) or "").strip()
        if existing_status == "PROCESADO" and existing_guide_id:
            reconciliation = reconcile_guide_orders(
                appsheet,
                existing_guide_id,
            )
            refreshed = _find_by_key_optional(
                appsheet, TABLE_GUIAS, GUIA_KEY, existing_guide_id
            ) or {}
            return {
                "ok": True,
                "status": "already_processed_reconciled",
                "drive_file_id": file_id,
                "id_guia_fierro": existing_guide_id,
                "estado_revision": str(
                    refreshed.get("ESTADO_REVISION") or ""
                ).strip(),
                "conciliacion_pedidos": reconciliation.as_dict(),
            }

    pdf_row_created = bool(existing_pdf)

    try:
        pdf_bytes, mime_type, drive_name, meta = drive.download_fierro_guide_by_id(file_id)
        file_name = (nombre_archivo or drive_name or "guia.pdf").strip()

        if mime_type and mime_type != "application/pdf" and not file_name.lower().endswith(".pdf"):
            raise FierroGuideServiceError(
                f"El archivo {file_name!r} no es PDF (MIME {mime_type!r})."
            )

        pdf_row = {
            PDF_KEY: file_id,
            "NOMBRE_ARCHIVO": file_name,
            "ARCHIVO_GUIA": _make_appsheet_file_path(file_name),
            "FECHA_ARCHIVO": _datetime_appsheet(meta.get("createdTime")),
            "ESTADO_PROCESAMIENTO": "PROCESANDO",
            "OBSERVACION_PROCESAMIENTO": "",
        }
        if existing_pdf:
            appsheet.edit_row(TABLE_PDF, pdf_row)
        else:
            appsheet.add_rows(TABLE_PDF, [pdf_row])
            pdf_row_created = True

        guide = parse_fierro_guide(pdf_bytes, filename=file_name)
        guide_id = _stable_id("FG_", _digits(guide.rut_emisor), guide.numero_guia)

        existing_guide = _find_by_key_optional(appsheet, TABLE_GUIAS, GUIA_KEY, guide_id)
        if existing_guide:
            previous_file = str(existing_guide.get(PDF_KEY) or "").strip()
            if previous_file and previous_file != file_id:
                message = (
                    f"Guía {guide.numero_guia} ya registrada desde otro archivo Drive "
                    f"({previous_file}). No se duplicó cabecera ni detalle."
                )
                appsheet.edit_row(
                    TABLE_PDF,
                    {
                        PDF_KEY: file_id,
                        GUIA_KEY: guide_id,
                        "ESTADO_PROCESAMIENTO": "PROCESADO",
                        "FECHA_PROCESAMIENTO": _now_appsheet(),
                        "OBSERVACION_PROCESAMIENTO": message,
                    },
                )
                return {
                    "ok": True,
                    "status": "duplicate_guide",
                    "drive_file_id": file_id,
                    "id_guia_fierro": guide_id,
                    "numero_guia": guide.numero_guia,
                }

        project = _resolve_project(guide.direccion_destino)
        review_status, review_observation = _validate_guide(guide, project)

        header_row = {
            GUIA_KEY: guide_id,
            "PROYECTO": project,
            "N_GUIA": int(guide.numero_guia),
            "FECHA_GUIA": _date_appsheet(guide.fecha_guia),
            "RUT_EMISOR": guide.rut_emisor,
            "RAZON_SOCIAL_EMISOR": guide.razon_social_emisor,
            "ORDEN_COMPRA": guide.orden_compra,
            "DIRECCION_DESTINO": guide.direccion_destino,
            "COMUNA_DESTINO": guide.comuna_destino,
            "CHOFER": guide.chofer,
            "RUT_CHOFER": guide.rut_chofer,
            "PATENTE": guide.patente,
            "TOTAL_KG_DESPACHADOS": _decimal_appsheet(guide.total_kg_despachados),
            "NETO_GUIA": guide.neto_guia,
            "IVA_GUIA": guide.iva_guia,
            "TOTAL_GUIA": guide.total_guia,
            PDF_KEY: file_id,
            "ESTADO_REVISION": review_status,
            "OBSERVACION_REVISION": review_observation,
        }

        if existing_guide:
            appsheet.edit_row(TABLE_GUIAS, header_row)
        else:
            appsheet.add_rows(TABLE_GUIAS, [header_row])

        _delete_children(appsheet, guide_id)

        detail_rows: list[dict[str, Any]] = []
        for item in guide.items:
            detail_rows.append(
                {
                    DETALLE_KEY: _stable_id(
                        "FGD_",
                        guide_id,
                        item.line_number,
                        item.codigo_producto,
                        item.hornada,
                    ),
                    GUIA_KEY: guide_id,
                    "CODIGO_PRODUCTO": item.codigo_producto,
                    "DESCRIPCION": item.descripcion,
                    "DIAMETRO_MM": _decimal_appsheet(item.diametro_mm),
                    "LARGO_M": _decimal_appsheet(item.largo_m),
                    "HORNADA": item.hornada,
                    "KG_DESPACHADOS": _decimal_appsheet(item.kg_despachados),
                    "PRECIO_KG": _decimal_appsheet(item.precio_kg),
                    "TOTAL_ITEM": item.total_item,
                }
            )
        if detail_rows:
            appsheet.add_rows(TABLE_DETALLE, detail_rows)

        linked_invoice_refs = _link_existing_invoice_refs(appsheet, guide, guide_id)
        reconciliation = reconcile_guide_orders(appsheet, guide_id)
        refreshed_guide = _find_by_key_optional(
            appsheet, TABLE_GUIAS, GUIA_KEY, guide_id
        ) or {}
        final_review_status = str(
            refreshed_guide.get("ESTADO_REVISION") or review_status
        ).strip()

        appsheet.edit_row(
            TABLE_PDF,
            {
                PDF_KEY: file_id,
                GUIA_KEY: guide_id,
                "ESTADO_PROCESAMIENTO": "PROCESADO",
                "FECHA_PROCESAMIENTO": _now_appsheet(),
                "OBSERVACION_PROCESAMIENTO": "",
            },
        )

        logger.info(
            "guia_fierro processed file=%s guide=%s items=%s project=%s status=%s links=%s",
            file_id,
            guide.numero_guia,
            len(guide.items),
            project or "<sin proyecto>",
            final_review_status,
            linked_invoice_refs,
        )

        return {
            "ok": True,
            "status": "processed",
            "drive_file_id": file_id,
            "id_guia_fierro": guide_id,
            "numero_guia": guide.numero_guia,
            "proyecto": project,
            "items": len(guide.items),
            "total_kg_despachados": _decimal_appsheet(guide.total_kg_despachados),
            "facturas_vinculadas": linked_invoice_refs,
            "estado_revision": final_review_status,
            "conciliacion_pedidos": reconciliation.as_dict(),
        }

    except Exception as exc:
        logger.exception("guia_fierro processing_error file=%s", file_id)
        if pdf_row_created:
            try:
                appsheet.edit_row(
                    TABLE_PDF,
                    {
                        PDF_KEY: file_id,
                        "ESTADO_PROCESAMIENTO": "ERROR",
                        "FECHA_PROCESAMIENTO": _now_appsheet(),
                        "OBSERVACION_PROCESAMIENTO": _clean_error(exc),
                    },
                )
            except Exception:
                logger.exception("guia_fierro unable_to_store_error file=%s", file_id)
        raise
