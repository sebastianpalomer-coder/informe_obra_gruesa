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
from .fierro_invoice_parser import FierroInvoice, parse_fierro_invoice


TABLE_PDF = os.getenv(
    "FIERRO_FACTURAS_PDF_TABLE",
    "FIERRO_FACTURAS_PDF",
).strip() or "FIERRO_FACTURAS_PDF"

TABLE_FACTURAS = os.getenv(
    "FIERRO_FACTURAS_TABLE",
    "FIERRO_FACTURAS",
).strip() or "FIERRO_FACTURAS"

TABLE_DETALLE = os.getenv(
    "FIERRO_FACTURAS_DETALLE_TABLE",
    "FIERRO_FACTURAS_DETALLE",
).strip() or "FIERRO_FACTURAS_DETALLE"

TABLE_GUIAS = os.getenv(
    "FIERRO_FACTURAS_GUIAS_TABLE",
    "FIERRO_FACTURAS_GUIAS",
).strip() or "FIERRO_FACTURAS_GUIAS"

PDF_KEY = "ID_ARCHIVO"
FACTURA_KEY = "ID_FACTURA_FIERRO"
DETALLE_KEY = "ID_DETALLE_FACTURA"
GUIA_KEY = "ID_FACTURA_GUIA"

APPSHEET_PATH = os.getenv(
    "FIERRO_FACTURAS_APPSHEET_PATH",
    "FIERRO_FACTURAS",
).strip().strip("/")

logger = logging.getLogger(__name__)


class FierroInvoiceServiceError(RuntimeError):
    pass


def _now_appsheet() -> str:
    now = datetime.now(ZoneInfo("America/Santiago"))
    return now.strftime("%m/%d/%Y %H:%M:%S")


def _date_appsheet(value) -> str:
    return value.strftime("%m/%d/%Y") if value else ""


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
    text = str(exc).strip() or exc.__class__.__name__
    return text[:1800]


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

    raw = os.getenv("FIERRO_FACTURA_PROJECT_MAP_JSON", "").strip()
    if not raw:
        return default

    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FierroInvoiceServiceError(
            "FIERRO_FACTURA_PROJECT_MAP_JSON no contiene JSON válido."
        ) from exc

    if not isinstance(decoded, dict):
        raise FierroInvoiceServiceError(
            "FIERRO_FACTURA_PROJECT_MAP_JSON debe ser un objeto JSON."
        )

    result = dict(default)
    for key, value in decoded.items():
        if str(key).strip() and str(value).strip():
            result[str(key)] = str(value)
    return result


def _resolve_project(address: str) -> str:
    normalized_address = _normalize_match_text(address)
    for needle, project in _project_map().items():
        if _normalize_match_text(needle) in normalized_address:
            return project
    return ""


def _validate_invoice(invoice: FierroInvoice, project: str) -> tuple[str, str]:
    notes: list[str] = []
    money_problem = False

    item_total = sum(item.total_item for item in invoice.items)
    if abs(item_total - invoice.neto_factura) > 1:
        money_problem = True
        notes.append(
            f"Suma de ítems ${item_total:,} distinta del neto ${invoice.neto_factura:,}."
        )

    expected_vat = int(
        (Decimal(invoice.neto_factura) * Decimal("0.19")).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )
    if abs(expected_vat - invoice.iva_factura) > 1:
        money_problem = True
        notes.append(
            f"IVA esperado ${expected_vat:,} distinto del IVA ${invoice.iva_factura:,}."
        )

    expected_total = invoice.neto_factura + invoice.iva_factura
    if expected_total != invoice.total_factura:
        money_problem = True
        notes.append(
            f"Neto + IVA ${expected_total:,} distinto del total ${invoice.total_factura:,}."
        )

    for item in invoice.items:
        expected_line = int(
            (item.kg_facturados * item.precio_kg).quantize(
                Decimal("1"),
                rounding=ROUND_HALF_UP,
            )
        )
        if abs(expected_line - item.total_item) > 1:
            money_problem = True
            notes.append(
                f"Línea {item.line_number}: kg x precio = ${expected_line:,}, "
                f"pero total ítem = ${item.total_item:,}."
            )

    if money_problem:
        status = "REVISAR_MONTO"
    elif not project:
        status = "REVISAR_PEDIDO"
        notes.append(
            "No se pudo identificar PROYECTO desde la dirección destino: "
            f"{invoice.direccion_destino or '[vacía]'}."
        )
    else:
        status = "PENDIENTE"
        notes.append(
            "Estructura y montos de factura consistentes. Pendiente conciliación con pedidos/guías."
        )

    return status, " ".join(notes)[:1800]


def _find_by_key_optional(
    appsheet: AppSheetClient,
    table: str,
    key_name: str,
    key_value: Any,
) -> dict[str, Any] | None:
    rows = appsheet.find_rows(
        table,
        key_rows=[{key_name: key_value}],
    )
    return rows[0] if rows else None


def _delete_children(
    appsheet: AppSheetClient,
    table: str,
    child_key: str,
    invoice_id: str,
) -> None:
    rows = appsheet.find_rows(table)
    keys = [
        {child_key: row.get(child_key)}
        for row in rows
        if str(row.get(FACTURA_KEY) or "").strip() == invoice_id
        and str(row.get(child_key) or "").strip()
    ]
    if keys:
        appsheet.delete_rows(table, keys)


def _upsert_header(
    appsheet: AppSheetClient,
    row: dict[str, Any],
) -> None:
    existing = _find_by_key_optional(
        appsheet,
        TABLE_FACTURAS,
        FACTURA_KEY,
        row[FACTURA_KEY],
    )
    if existing:
        appsheet.edit_row(TABLE_FACTURAS, row)
    else:
        appsheet.add_rows(TABLE_FACTURAS, [row])


def _make_appsheet_file_path(name: str) -> str:
    if APPSHEET_PATH:
        return f"{APPSHEET_PATH}/{name}"
    return name


def process_fierro_invoice(
    drive_file_id: str,
    nombre_archivo: str = "",
) -> dict[str, Any]:
    file_id = str(drive_file_id or "").strip()
    if not file_id:
        raise FierroInvoiceServiceError("drive_file_id está vacío.")

    appsheet = AppSheetClient()
    drive = DriveClient()

    existing_pdf = _find_by_key_optional(
        appsheet,
        TABLE_PDF,
        PDF_KEY,
        file_id,
    )

    if existing_pdf:
        existing_status = str(existing_pdf.get("ESTADO_PROCESAMIENTO") or "").upper()
        existing_invoice_id = str(existing_pdf.get(FACTURA_KEY) or "").strip()
        if existing_status == "PROCESADO" and existing_invoice_id:
            return {
                "ok": True,
                "status": "already_processed",
                "drive_file_id": file_id,
                "id_factura_fierro": existing_invoice_id,
            }

    pdf_row_created = bool(existing_pdf)

    try:
        pdf_bytes, mime_type, drive_name, meta = drive.download_fierro_invoice_by_id(file_id)
        file_name = (nombre_archivo or drive_name or "factura.pdf").strip()

        if mime_type and mime_type != "application/pdf" and not file_name.lower().endswith(".pdf"):
            raise FierroInvoiceServiceError(
                f"El archivo {file_name!r} no es PDF (MIME {mime_type!r})."
            )

        initial_pdf_row = {
            PDF_KEY: file_id,
            "NOMBRE_ARCHIVO": file_name,
            "ARCHIVO_FACTURA": _make_appsheet_file_path(file_name),
            "FECHA_ARCHIVO": _datetime_appsheet(meta.get("createdTime")),
            "ESTADO_PROCESAMIENTO": "PROCESANDO",
            "OBSERVACION_PROCESAMIENTO": "",
        }

        if existing_pdf:
            appsheet.edit_row(TABLE_PDF, initial_pdf_row)
        else:
            appsheet.add_rows(TABLE_PDF, [initial_pdf_row])
            pdf_row_created = True

        invoice = parse_fierro_invoice(pdf_bytes)
        invoice_id = _stable_id(
            "FF_",
            _digits(invoice.rut_emisor),
            invoice.numero_factura,
        )

        existing_invoice = _find_by_key_optional(
            appsheet,
            TABLE_FACTURAS,
            FACTURA_KEY,
            invoice_id,
        )

        if existing_invoice:
            previous_file = str(existing_invoice.get(PDF_KEY) or "").strip()
            if previous_file and previous_file != file_id:
                duplicate_message = (
                    f"Factura {invoice.numero_factura} ya registrada desde otro archivo "
                    f"Drive ({previous_file}). No se duplicó cabecera ni detalle."
                )
                appsheet.edit_row(
                    TABLE_PDF,
                    {
                        PDF_KEY: file_id,
                        FACTURA_KEY: invoice_id,
                        "ESTADO_PROCESAMIENTO": "PROCESADO",
                        "FECHA_PROCESAMIENTO": _now_appsheet(),
                        "OBSERVACION_PROCESAMIENTO": duplicate_message,
                    },
                )
                return {
                    "ok": True,
                    "status": "duplicate_invoice",
                    "drive_file_id": file_id,
                    "id_factura_fierro": invoice_id,
                    "numero_factura": invoice.numero_factura,
                }

        project = _resolve_project(invoice.direccion_destino)
        review_status, review_observation = _validate_invoice(invoice, project)

        header_row = {
            FACTURA_KEY: invoice_id,
            "PROYECTO": project,
            "N_FACTURA": int(invoice.numero_factura),
            "RUT_EMISOR": invoice.rut_emisor,
            "RAZON_SOCIAL_EMISOR": invoice.razon_social_emisor,
            "FECHA_EMISION": _date_appsheet(invoice.fecha_emision),
            "FECHA_VENCIMIENTO": _date_appsheet(invoice.fecha_vencimiento),
            "ORDEN_COMPRA": invoice.orden_compra,
            "DIRECCION_DESTINO": invoice.direccion_destino,
            "COMUNA_DESTINO": invoice.comuna_destino,
            "NETO_FACTURA": invoice.neto_factura,
            "IVA_FACTURA": invoice.iva_factura,
            "TOTAL_FACTURA": invoice.total_factura,
            "TOTAL_KG_FACTURADOS": _decimal_appsheet(invoice.total_kg_facturados),
            PDF_KEY: file_id,
            "ESTADO_REVISION": review_status,
            "OBSERVACION_REVISION": review_observation,
        }

        _upsert_header(appsheet, header_row)

        # Reintentos seguros: antes de volver a insertar detalle/referencias,
        # se eliminan exclusivamente los hijos de esta factura.
        _delete_children(appsheet, TABLE_DETALLE, DETALLE_KEY, invoice_id)
        _delete_children(appsheet, TABLE_GUIAS, GUIA_KEY, invoice_id)

        detail_rows: list[dict[str, Any]] = []
        for item in invoice.items:
            detail_rows.append(
                {
                    DETALLE_KEY: _stable_id(
                        "FFD_",
                        invoice_id,
                        item.line_number,
                        item.codigo_producto,
                        item.hornada,
                    ),
                    FACTURA_KEY: invoice_id,
                    "CODIGO_PRODUCTO": item.codigo_producto,
                    "DESCRIPCION": item.descripcion,
                    "DIAMETRO_MM": _decimal_appsheet(item.diametro_mm),
                    "LARGO_M": _decimal_appsheet(item.largo_m),
                    "HORNADA": item.hornada,
                    "KG_FACTURADOS": _decimal_appsheet(item.kg_facturados),
                    "PRECIO_KG": _decimal_appsheet(item.precio_kg),
                    "TOTAL_ITEM": item.total_item,
                }
            )

        if detail_rows:
            appsheet.add_rows(TABLE_DETALLE, detail_rows)

        guide_rows: list[dict[str, Any]] = []
        for ref in invoice.guias:
            guide_rows.append(
                {
                    GUIA_KEY: _stable_id(
                        "FFG_",
                        invoice_id,
                        ref.numero,
                        _date_appsheet(ref.fecha),
                    ),
                    FACTURA_KEY: invoice_id,
                    "N_GUIA": int(ref.numero),
                    "FECHA_GUIA": _date_appsheet(ref.fecha),
                }
            )

        if guide_rows:
            appsheet.add_rows(TABLE_GUIAS, guide_rows)

        appsheet.edit_row(
            TABLE_PDF,
            {
                PDF_KEY: file_id,
                FACTURA_KEY: invoice_id,
                "ESTADO_PROCESAMIENTO": "PROCESADO",
                "FECHA_PROCESAMIENTO": _now_appsheet(),
                "OBSERVACION_PROCESAMIENTO": "",
            },
        )

        logger.info(
            "factura_fierro processed file=%s invoice=%s items=%s guides=%s project=%s status=%s",
            file_id,
            invoice.numero_factura,
            len(invoice.items),
            len(invoice.guias),
            project or "<sin proyecto>",
            review_status,
        )

        return {
            "ok": True,
            "status": "processed",
            "drive_file_id": file_id,
            "id_factura_fierro": invoice_id,
            "numero_factura": invoice.numero_factura,
            "proyecto": project,
            "items": len(invoice.items),
            "guias": len(invoice.guias),
            "total_kg_facturados": _decimal_appsheet(invoice.total_kg_facturados),
            "estado_revision": review_status,
        }

    except Exception as exc:
        logger.exception("factura_fierro processing_error file=%s", file_id)
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
                logger.exception(
                    "factura_fierro unable_to_store_error file=%s",
                    file_id,
                )
        raise
