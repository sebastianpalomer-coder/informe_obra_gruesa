from __future__ import annotations

import ipaddress
import logging
import os
import re
import socket
from datetime import datetime
from html import unescape
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo
from typing import Any

import requests

from .appsheet_client import AppSheetClient
from .report_writer_client import ReportWriterClient
from .sample_ticket_parser import SampleTicket, parse_sample_ticket


TABLE_VISITS = os.getenv(
    "SAMPLE_VISITS_TABLE",
    "TABLA_VISITA_TOMA_MUESTRA",
).strip() or "TABLA_VISITA_TOMA_MUESTRA"

TABLE_GUIDES = os.getenv(
    "SAMPLE_GUIDES_TABLE",
    "GUIAS",
).strip() or "GUIAS"

VISIT_KEY = os.getenv(
    "SAMPLE_VISIT_KEY",
    "ID_VISITA",
).strip() or "ID_VISITA"

GUIDE_KEY = os.getenv(
    "SAMPLE_GUIDE_KEY",
    "ID_REGISTRO",
).strip() or "ID_REGISTRO"

GUIDE_FOLIO_COLUMN = os.getenv(
    "SAMPLE_GUIDE_FOLIO_COLUMN",
    "FOLIO",
).strip() or "FOLIO"

SAMPLE_TICKET_APPSHEET_PATH = os.getenv(
    "SAMPLE_TICKET_APPSHEET_PATH",
    "MUESTRAS_HORMIGON/BOLETAS_MUESTREO",
).strip().strip("/")

MAX_PDF_BYTES = int(
    os.getenv("SAMPLE_TICKET_MAX_BYTES", str(20 * 1024 * 1024))
)

logger = logging.getLogger(__name__)


class SampleTicketServiceError(RuntimeError):
    pass


def _now_appsheet() -> str:
    now_chile = datetime.now(ZoneInfo("America/Santiago"))
    return now_chile.strftime("%m/%d/%Y %H:%M:%S")


def _clean_error(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text[:1800]


def _digits(value: Any) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _safe_filename_part(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip())
    return text.strip("_") or "sin_dato"


def _validate_external_http_url(value: str) -> str:
    url = str(value or "").strip()
    if not url:
        raise SampleTicketServiceError("URL_QR_MUESTREO está vacía.")

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise SampleTicketServiceError(
            "El QR debe contener una URL http o https."
        )

    if not parsed.hostname:
        raise SampleTicketServiceError("La URL del QR no contiene host.")

    hostname = parsed.hostname.lower().strip(".")
    if hostname in {"localhost", "localhost.localdomain"}:
        raise SampleTicketServiceError("Host de QR no permitido.")

    try:
        infos = socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SampleTicketServiceError(
            f"No fue posible resolver el host del QR: {hostname}."
        ) from exc

    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise SampleTicketServiceError(
                "La URL del QR resuelve a una dirección de red no permitida."
            )

    return url


def _get_with_safe_redirects(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    *,
    max_redirects: int = 5,
) -> requests.Response:
    current_url = _validate_external_http_url(url)

    for _ in range(max_redirects + 1):
        try:
            response = session.get(
                current_url,
                headers=headers,
                timeout=(15, 90),
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as exc:
            raise SampleTicketServiceError(
                f"No fue posible descargar la boleta desde el QR: {exc}"
            ) from exc

        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location", "").strip()
            response.close()
            if not location:
                raise SampleTicketServiceError(
                    "El servidor del QR respondió con una redirección sin destino."
                )
            current_url = _validate_external_http_url(
                urljoin(current_url, location)
            )
            continue

        return response

    raise SampleTicketServiceError(
        f"La URL del QR superó el máximo de {max_redirects} redirecciones."
    )


def _read_response_limited(response: requests.Response) -> bytes:
    content_length = response.headers.get("Content-Length", "").strip()
    if content_length.isdigit() and int(content_length) > MAX_PDF_BYTES:
        raise SampleTicketServiceError(
            f"El archivo supera el máximo permitido de {MAX_PDF_BYTES} bytes."
        )

    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_PDF_BYTES:
            raise SampleTicketServiceError(
                f"El archivo supera el máximo permitido de {MAX_PDF_BYTES} bytes."
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _extract_pdf_link_from_html(html: str, base_url: str) -> str | None:
    hrefs = re.findall(
        r"href\s*=\s*[\"']([^\"']+)[\"']",
        html,
        flags=re.IGNORECASE,
    )
    candidates: list[str] = []
    for href in hrefs:
        candidate = urljoin(base_url, unescape(href.strip()))
        if ".pdf" in candidate.lower():
            candidates.append(candidate)
    return candidates[0] if candidates else None


def download_sample_ticket(url: str) -> tuple[bytes, str]:
    current_url = _validate_external_http_url(url)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; HotelBelletSampleTicket/1.0; +https://openai.com/)"
        ),
        "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8",
    }

    with requests.Session() as session:
        for attempt in range(2):
            response = _get_with_safe_redirects(
                session,
                current_url,
                headers,
            )

            try:
                response.raise_for_status()
                body = _read_response_limited(response)
            finally:
                response.close()

            content_type = (
                response.headers.get("Content-Type", "")
                .split(";", 1)[0]
                .strip()
                .lower()
            )

            if body.startswith(b"%PDF-") or content_type == "application/pdf":
                if not body.startswith(b"%PDF-"):
                    raise SampleTicketServiceError(
                        "La URL declaró application/pdf, pero el contenido no parece ser un PDF válido."
                    )
                return body, response.url

            if attempt == 0 and content_type in {"text/html", "application/xhtml+xml"}:
                try:
                    html = body.decode(response.encoding or "utf-8", errors="replace")
                except Exception:
                    html = body.decode("utf-8", errors="replace")
                pdf_link = _extract_pdf_link_from_html(html, response.url)
                if pdf_link:
                    current_url = _validate_external_http_url(pdf_link)
                    continue

            raise SampleTicketServiceError(
                "El QR no devolvió un PDF descargable. "
                f"Content-Type recibido: {content_type or 'desconocido'}."
            )

    raise SampleTicketServiceError("No fue posible resolver el PDF del QR.")


def _resolve_guide(
    appsheet: AppSheetClient,
    guide_number: str,
) -> dict[str, Any]:
    wanted = _digits(guide_number)
    rows = appsheet.find_rows(TABLE_GUIDES)

    candidates = [
        row
        for row in rows
        if _digits(row.get(GUIDE_FOLIO_COLUMN)) == wanted
    ]

    if not candidates:
        raise SampleTicketServiceError(
            f"No se encontró la guía {guide_number} en {TABLE_GUIDES}[{GUIDE_FOLIO_COLUMN}]."
        )

    if len(candidates) == 1:
        return candidates[0]

    transex = [
        row
        for row in candidates
        if "TRANSEX" in str(row.get("PROVEEDOR") or "").upper()
        or _digits(row.get("RUT_EMISOR")) == "884176002"
    ]
    if len(transex) == 1:
        return transex[0]

    validated = [
        row
        for row in (transex or candidates)
        if "VALIDADA" in " ".join(str(v) for v in row.values()).upper()
    ]
    if len(validated) == 1:
        return validated[0]

    raise SampleTicketServiceError(
        f"La guía {guide_number} aparece más de una vez en {TABLE_GUIDES}; "
        "no se puede determinar automáticamente cuál corresponde."
    )


def _archive_ticket(
    writer: ReportWriterClient,
    pdf_bytes: bytes,
    ticket: SampleTicket,
) -> str:
    filename = (
        f"Boleta_Muestreo_{_safe_filename_part(ticket.sample_number)}_"
        f"Guia_{_safe_filename_part(ticket.guide_number)}.pdf"
    )

    result = writer.upload_or_replace_pdf(
        pdf_bytes,
        filename,
        folder_key="sample_tickets",
        appsheet_path=SAMPLE_TICKET_APPSHEET_PATH,
    )
    return result.relative_path


def process_sample_ticket(id_visita: str) -> dict[str, Any]:
    appsheet = AppSheetClient()
    writer = ReportWriterClient()

    visit = appsheet.find_by_key(
        TABLE_VISITS,
        VISIT_KEY,
        id_visita,
    )

    qr_url = str(visit.get("URL_QR_MUESTREO") or "").strip()
    if not qr_url:
        raise SampleTicketServiceError(
            f"{TABLE_VISITS}[URL_QR_MUESTREO] está vacío para {id_visita}."
        )

    logger.info(
        "sample_ticket stage=visita_encontrada id=%s",
        id_visita,
    )

    appsheet.edit_row(
        TABLE_VISITS,
        {
            VISIT_KEY: id_visita,
            "ESTADO_PROCESAMIENTO_BOLETA": "PROCESANDO",
            "OBSERVACION_PROCESAMIENTO_BOLETA": "",
        },
    )

    archived_path = ""
    sample_number = ""
    guide_number = ""

    try:
        pdf_bytes, final_url = download_sample_ticket(qr_url)
        logger.info(
            "sample_ticket stage=pdf_descargado id=%s bytes=%s url_final=%s",
            id_visita,
            len(pdf_bytes),
            final_url,
        )

        ticket = parse_sample_ticket(pdf_bytes)
        sample_number = ticket.sample_number
        guide_number = ticket.guide_number
        logger.info(
            "sample_ticket stage=pdf_parseado id=%s muestra=%s guia=%s",
            id_visita,
            sample_number,
            guide_number,
        )

        archived_path = _archive_ticket(writer, pdf_bytes, ticket)
        logger.info(
            "sample_ticket stage=pdf_archivado id=%s path=%s",
            id_visita,
            archived_path,
        )

        guide = _resolve_guide(appsheet, guide_number)
        guide_key = str(guide.get(GUIDE_KEY) or "").strip()
        if not guide_key:
            raise SampleTicketServiceError(
                f"La guía {guide_number} no tiene valor en {GUIDE_KEY}."
            )

        appsheet.edit_row(
            TABLE_VISITS,
            {
                VISIT_KEY: id_visita,
                "ID_GUIA": guide_key,
                "ARCHIVO_BOLETA_MUESTREO": archived_path,
                "N_MUESTRA_LAB": sample_number,
                "ESTADO_PROCESAMIENTO_BOLETA": "PROCESADO",
                "OBSERVACION_PROCESAMIENTO_BOLETA": "",
            },
        )

        logger.info(
            "sample_ticket stage=procesado id=%s muestra=%s guia=%s id_guia=%s",
            id_visita,
            sample_number,
            guide_number,
            guide_key,
        )

        return {
            "ok": True,
            "id_visita": id_visita,
            "muestra": sample_number,
            "guia": guide_number,
            "id_guia": guide_key,
            "archivo_boleta": archived_path,
        }

    except Exception as exc:
        logger.exception(
            "sample_ticket stage=error id=%s",
            id_visita,
        )

        error_row: dict[str, Any] = {
            VISIT_KEY: id_visita,
            "ESTADO_PROCESAMIENTO_BOLETA": "ERROR",
            "OBSERVACION_PROCESAMIENTO_BOLETA": _clean_error(exc),
        }
        if archived_path:
            error_row["ARCHIVO_BOLETA_MUESTREO"] = archived_path
        if sample_number:
            error_row["N_MUESTRA_LAB"] = sample_number

        try:
            appsheet.edit_row(TABLE_VISITS, error_row)
        except Exception:
            logger.exception(
                "sample_ticket stage=error_no_registrado id=%s",
                id_visita,
            )

        raise
