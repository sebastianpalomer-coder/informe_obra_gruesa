from __future__ import annotations

import base64
import logging
import os
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .appsheet_client import AppSheetClient
from .concrete_certificate_parser import (
    ConcreteCertificate,
    ConcreteCertificateParseError,
    parse_concrete_certificate,
)


TABLE_CERTIFICATES = os.getenv(
    "CONCRETE_CERTIFICATES_TABLE", "TABLA_CERTIFICADO_HORMIGON"
).strip() or "TABLA_CERTIFICADO_HORMIGON"
TABLE_GUIDES = os.getenv(
    "CONCRETE_GUIDES_TABLE", "GUIAS"
).strip() or "GUIAS"
TABLE_RESISTANCE = os.getenv(
    "CONCRETE_RESISTANCE_TABLE", "TABLA_RESISTENCIA"
).strip() or "TABLA_RESISTENCIA"

CERT_KEY = "ID_CERTIFICADO"
GUIDE_KEY = "ID_REGISTRO"
RESISTANCE_KEY = "ID_MUESTRA"

LAB_COLUMN = os.getenv(
    "CONCRETE_CERTIFICATE_LAB_COLUMN", "NOMBRE_LABORATORIO"
).strip()
OBSERVATION_COLUMN = os.getenv(
    "CONCRETE_CERTIFICATE_OBSERVATION_COLUMN", ""
).strip()

logger = logging.getLogger(__name__)


class ConcreteCertificateServiceError(RuntimeError):
    pass


def _now_appsheet() -> str:
    return datetime.now(ZoneInfo("America/Santiago")).strftime("%m/%d/%Y %H:%M:%S")


def _date_appsheet(value) -> str:
    return value.strftime("%Y-%m-%d") if value else ""


def _to_number_or_blank(value: float | None) -> Any:
    if value is None:
        return ""
    return float(value)


def _decode_pdf(content_base64: str) -> bytes:
    raw = str(content_base64 or "").strip()
    if not raw:
        raise ConcreteCertificateServiceError("content_base64 está vacío.")
    try:
        pdf_bytes = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise ConcreteCertificateServiceError("content_base64 no es Base64 válido.") from exc
    if not pdf_bytes:
        raise ConcreteCertificateServiceError("El PDF recibido está vacío.")
    return pdf_bytes


def _certificate_payload(cert: ConcreteCertificate) -> dict[str, Any]:
    return {
        "certificate_number": cert.certificate_number,
        "laboratory": cert.laboratory,
        "issue_date": _date_appsheet(cert.issue_date),
        "guide_number": cert.guide_number,
        "sample_ticket_number": cert.sample_ticket_number,
        "concrete_grade": cert.concrete_grade,
        "placement": cert.placement,
        "real_result_count": cert.real_result_count,
        "preliminary_age_days": cert.preliminary_age_days,
        "preliminary_strength_mpa": cert.preliminary_strength_mpa,
        "r28_1_mpa": cert.r28_1_mpa,
        "r28_2_mpa": cert.r28_2_mpa,
        "r28_replicated": cert.r28_replicated,
        "observation": cert.observation,
        "results": [
            {
                "specimen_no": r.specimen_no,
                "test_date": _date_appsheet(r.test_date),
                "age_days": r.age_days,
                "strength_mpa": r.strength_mpa,
            }
            for r in cert.results
        ],
    }


def parse_concrete_certificate_payload(
    *,
    content_base64: str,
    nombre_archivo: str = "",
) -> dict[str, Any]:
    pdf_bytes = _decode_pdf(content_base64)
    cert = parse_concrete_certificate(pdf_bytes, filename=nombre_archivo)
    return {
        "ok": True,
        "status": "PARSED",
        "nombre_archivo": nombre_archivo,
        **_certificate_payload(cert),
    }


def _find_guide_id(appsheet: AppSheetClient, guide_number: str) -> str:
    guide_number = str(guide_number or "").strip()
    if not guide_number:
        raise ConcreteCertificateServiceError(
            "El certificado no contiene número de guía de despacho."
        )
    matches = [
        row for row in appsheet.find_rows(TABLE_GUIDES)
        if str(row.get("FOLIO") or "").strip() == guide_number
    ]
    if not matches:
        raise ConcreteCertificateServiceError(
            f"No existe GUIAS[FOLIO]={guide_number!r}; no se puede vincular el certificado."
        )
    if len(matches) > 1:
        raise ConcreteCertificateServiceError(
            f"Existen {len(matches)} guías con FOLIO={guide_number!r}; vínculo ambiguo."
        )
    guide_id = str(matches[0].get(GUIDE_KEY) or "").strip()
    if not guide_id:
        raise ConcreteCertificateServiceError(
            f"La guía {guide_number} no tiene {GUIDE_KEY}."
        )
    return guide_id


def _upsert_certificate(
    appsheet: AppSheetClient,
    cert: ConcreteCertificate,
    guide_id: str,
) -> None:
    row: dict[str, Any] = {
        CERT_KEY: cert.certificate_number,
        "ID_GUIA": guide_id,
        LAB_COLUMN: cert.laboratory,
        "FECHA_CERTIFICADO": _date_appsheet(cert.issue_date),
        "R_PRELIMINAR": _to_number_or_blank(cert.preliminary_strength_mpa),
        "EDAD_PRELIMINAR": cert.preliminary_age_days or "",
        "R_28_DIAS_1": _to_number_or_blank(cert.r28_1_mpa),
        "R_28_DIAS_2": _to_number_or_blank(cert.r28_2_mpa),
        "VIGENTE": True,
        "FECHA_REGISTRO": _now_appsheet(),
    }
    if OBSERVATION_COLUMN:
        row[OBSERVATION_COLUMN] = cert.observation

    existing = appsheet.find_rows(
        TABLE_CERTIFICATES,
        key_rows=[{CERT_KEY: cert.certificate_number}],
    )
    if existing:
        appsheet.edit_row(TABLE_CERTIFICATES, row)
    else:
        appsheet.add_rows(TABLE_CERTIFICATES, [row])


def _link_resistance_rows(
    appsheet: AppSheetClient,
    guide_id: str,
    certificate_number: str,
) -> int:
    rows = appsheet.find_rows(TABLE_RESISTANCE)
    linked = 0
    for row in rows:
        if str(row.get("ID_GUIA") or "").strip() != guide_id:
            continue
        sample_id = str(row.get(RESISTANCE_KEY) or "").strip()
        if not sample_id:
            continue
        current = str(row.get(CERT_KEY) or "").strip()
        if current == certificate_number:
            continue
        appsheet.edit_row(
            TABLE_RESISTANCE,
            {
                RESISTANCE_KEY: sample_id,
                CERT_KEY: certificate_number,
            },
        )
        linked += 1
    return linked


def process_concrete_certificate(
    *,
    content_base64: str,
    nombre_archivo: str = "",
    drive_file_id: str = "",
    modified_time: str = "",
) -> dict[str, Any]:
    pdf_bytes = _decode_pdf(content_base64)
    try:
        cert = parse_concrete_certificate(pdf_bytes, filename=nombre_archivo)
    except ConcreteCertificateParseError as exc:
        raise ConcreteCertificateServiceError(str(exc)) from exc

    appsheet = AppSheetClient()
    guide_id = _find_guide_id(appsheet, cert.guide_number)
    _upsert_certificate(appsheet, cert, guide_id)
    linked = _link_resistance_rows(
        appsheet,
        guide_id,
        cert.certificate_number,
    )

    logger.info(
        "concrete_certificate processed cert=%s guide=%s results=%s file=%s",
        cert.certificate_number,
        cert.guide_number,
        cert.real_result_count,
        drive_file_id,
    )

    return {
        "ok": True,
        "status": "UPSERTED",
        "drive_file_id": drive_file_id,
        "modified_time": modified_time,
        "id_guia": guide_id,
        "resistance_rows_linked": linked,
        **_certificate_payload(cert),
    }
