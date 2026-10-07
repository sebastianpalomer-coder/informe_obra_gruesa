from __future__ import annotations

import io
import re
from dataclasses import dataclass

from pypdf import PdfReader


class SampleTicketParseError(RuntimeError):
    pass


@dataclass(frozen=True)
class SampleTicket:
    sample_number: str
    guide_number: str
    text: str


_SAMPLE_PATTERNS = (
    re.compile(r"MUESTRA\s*N[°º]?\s*[:#-]?\s*(\d{3,})", re.IGNORECASE),
    re.compile(r"MUESTRA\s*(?:NRO\.?|NO\.?|NUMERO)\s*[:#-]?\s*(\d{3,})", re.IGNORECASE),
)

_GUIDE_PATTERNS = (
    re.compile(r"GU[IÍ]A\s*N[°º]?\s*[:#-]?\s*(\d{3,})", re.IGNORECASE),
    re.compile(r"GU[IÍ]A\s*(?:NRO\.?|NO\.?|NUMERO)\s*[:#-]?\s*(\d{3,})", re.IGNORECASE),
)


def _normalize_text(value: str) -> str:
    text = str(value or "").replace("\u00a0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return text


def _find_first(patterns: tuple[re.Pattern[str], ...], text: str) -> str | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return None


def extract_pdf_text(pdf_bytes: bytes) -> str:
    if not pdf_bytes:
        raise SampleTicketParseError("El PDF de muestreo está vacío.")

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes), strict=False)
    except Exception as exc:
        raise SampleTicketParseError(
            f"No fue posible abrir el PDF de muestreo: {exc}"
        ) from exc

    if not reader.pages:
        raise SampleTicketParseError("El PDF de muestreo no contiene páginas.")

    pages: list[str] = []
    for page in reader.pages:
        text = ""
        try:
            text = page.extract_text(extraction_mode="layout") or ""
        except Exception:
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
        if text.strip():
            pages.append(text)

    combined = "\n\n".join(pages).strip()
    if not combined:
        raise SampleTicketParseError(
            "El PDF no contiene texto extraíble. "
            "Se requerirá OCR para este documento."
        )

    return _normalize_text(combined)


def parse_sample_ticket(pdf_bytes: bytes) -> SampleTicket:
    text = extract_pdf_text(pdf_bytes)

    sample_number = _find_first(_SAMPLE_PATTERNS, text)
    guide_number = _find_first(_GUIDE_PATTERNS, text)

    if not sample_number:
        raise SampleTicketParseError(
            "No se encontró el número de muestra en la boleta."
        )

    if not guide_number:
        raise SampleTicketParseError(
            "No se encontró el número de guía en la boleta."
        )

    return SampleTicket(
        sample_number=sample_number,
        guide_number=guide_number,
        text=text,
    )
