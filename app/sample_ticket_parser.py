from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from pypdf import PdfReader


class SampleTicketParseError(RuntimeError):
    pass


@dataclass(frozen=True)
class SampleTicket:
    sample_number: str
    guide_number: str
    text: str
    truck_number: str | None = None
    guide_m3: float | None = None
    product_code: str | None = None
    grade_type: str | None = None
    load_time: str | None = None
    plant_departure_time: str | None = None
    site_arrival_time: str | None = None
    placement: str | None = None
    sample_date: date | None = None
    sample_time: str | None = None
    ambient_temperature: float | None = None
    mix_temperature: float | None = None
    slump_cm: float | None = None
    specimen_type: str | None = None
    specimen_count: int | None = None
    test_ages: str | None = None
    specimen_compaction: str | None = None
    specimen_curing: str | None = None
    discharged_m3_at_sample: float | None = None
    discharge_start_time: str | None = None
    mixer_operator: str | None = None
    site_responsible: str | None = None
    lab_sampler: str | None = None


_SAMPLE_PATTERNS = (
    re.compile(r"MUESTRA\s*N[°º]?\s*[:#-]?\s*(\d{3,})", re.IGNORECASE),
    re.compile(r"MUESTRA\s*(?:NRO\.?|NO\.?|NUMERO)\s*[:#-]?\s*(\d{3,})", re.IGNORECASE),
)

_GUIDE_PATTERNS = (
    re.compile(r"GU[IÍ]A\s*N[°º]?\s*[:#-]?\s*(\d{3,})", re.IGNORECASE),
    re.compile(r"GU[IÍ]A\s*(?:NRO\.?|NO\.?|NUMERO)\s*[:#-]?\s*(\d{3,})", re.IGNORECASE),
)

_MONTHS_ES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


def _normalize_text(value: str) -> str:
    text = str(value or "").replace("\u00a0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.replace("\t", " ").rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip()


def _find_first(patterns: tuple[re.Pattern[str], ...], text: str) -> str | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return None


def _capture(text: str, pattern: str, *, flags: int = re.IGNORECASE) -> str | None:
    match = re.search(pattern, text, flags)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def _clean_text_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip(" \t\r\n:;,-")
    return cleaned or None


def _decimal(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = re.sub(r"[^0-9,.-]+", "", value).strip()
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    else:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _integer(value: str | None) -> int | None:
    if value is None:
        return None
    digits = re.sub(r"\D+", "", value)
    return int(digits) if digits else None


def _normalize_time(value: str | None) -> str | None:
    if value is None:
        return None
    match = re.search(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b", value)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    second = int(match.group(3) or 0)
    if hour > 23 or minute > 59 or second > 59:
        return None
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def _parse_spanish_date(value: str | None) -> date | None:
    if not value:
        return None
    plain = _strip_accents(value).lower()
    match = re.search(
        r"(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo)?\s*"
        r"(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(\d{4})",
        plain,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    day = int(match.group(1))
    month = _MONTHS_ES.get(match.group(2).lower())
    year = int(match.group(3))
    if not month:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _extract_people(text: str) -> tuple[str | None, str | None]:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        upper = _strip_accents(line).upper()
        if "RESPONSABLE EN OBRA" not in upper or "MUEST." not in upper:
            continue

        for previous_index in range(index - 1, max(-1, index - 5), -1):
            previous = lines[previous_index].strip()
            if not previous:
                continue
            parts = [part.strip() for part in re.split(r"\s{3,}", previous) if part.strip()]
            if len(parts) >= 2:
                responsible = _clean_text_value(parts[0])
                sampler = _clean_text_value(parts[-1])
                if sampler:
                    sampler = sampler.rstrip(".")
                return responsible, sampler
            break
    return None, None


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

    truck_number = _capture(
        text,
        r"CAMI[ÓO]N\s*N[°º]?\s*[:#-]?\s*([A-Za-z0-9-]+)",
    )
    guide_m3 = _decimal(
        _capture(text, r"CANT\.\s*\(en\s*m3\)\s*([0-9]+(?:[.,][0-9]+)?)")
    )
    product_code = _capture(
        text,
        r"C[ÓO]DIGO\s+DE\s+PRODUCTO\s+([A-Za-z0-9._/-]+)",
    )
    grade_type = _capture(
        text,
        r"GRADO\s*/\s*TIPO\s+([A-Za-z0-9._/-]+)",
    )
    load_time = _normalize_time(
        _capture(text, r"HORA\s+DE\s+CARGA\s+(\d{1,2}:\d{2}(?::\d{2})?)")
    )
    plant_departure_time = _normalize_time(
        _capture(text, r"SALIDA\s+PLANTA\s+(\d{1,2}:\d{2}(?::\d{2})?)")
    )
    site_arrival_time = _normalize_time(
        _capture(text, r"LLEGADA\s+A\s+OBRA\s+(\d{1,2}:\d{2}(?::\d{2})?)")
    )
    placement = _clean_text_value(
        _capture(
            text,
            r"^\s*COLOCADO\s+EN\s+([^\n]+)",
            flags=re.IGNORECASE | re.MULTILINE,
        )
    )

    sample_date_text = _capture(
        text,
        r"FECHA\s+DE\s+MUESTREO\s+(.+?)\s+HORA\s+MUESTREO",
        flags=re.IGNORECASE | re.DOTALL,
    )
    sample_date = _parse_spanish_date(sample_date_text)
    sample_time = _normalize_time(
        _capture(text, r"HORA\s+MUESTREO\s+(\d{1,2}:\d{2}(?::\d{2})?)")
    )

    ambient_temperature = _decimal(
        _capture(
            text,
            r"TEMPERATURA\s+AMBIENTE\s+([0-9]+(?:[.,][0-9]+)?)",
        )
    )
    mix_temperature = _decimal(
        _capture(
            text,
            r"TEMPERATURA\s+DE\s+MEZCLA\s+([0-9]+(?:[.,][0-9]+)?)",
        )
    )
    slump_cm = _decimal(
        _capture(text, r"ASENTAMIENTO\s+([0-9]+(?:[.,][0-9]+)?)")
    )
    specimen_type = _clean_text_value(
        _capture(text, r"PROBETA\s+EMPLEADA:\s*(.+?)\s+CANT\s*\.:", flags=re.IGNORECASE)
    )
    specimen_count = _integer(
        _capture(text, r"PROBETA\s+EMPLEADA:.*?CANT\s*\.:\s*(\d+)", flags=re.IGNORECASE)
    )
    test_ages = _clean_text_value(
        _capture(text, r"EDADES\s+DE\s+ENSAYO\s+([0-9][0-9,.;\s]*)")
    )

    specimen_compaction = _clean_text_value(
        _capture(
            text,
            r"COMPACTACI[ÓO]N\s+DE\s+PROBETAS:\s*(.+?)\s+CURADO\s+DE\s+PROBETAS\s+EN\s+OBRA:",
            flags=re.IGNORECASE,
        )
    )
    specimen_curing = _clean_text_value(
        _capture(
            text,
            r"CURADO\s+DE\s+PROBETAS\s+EN\s+OBRA:\s*([^\n]+)",
        )
    )
    discharged_m3_at_sample = _decimal(
        _capture(
            text,
            r"MUESTRA\s+SE\s+EXTRAE\s+A\s+([0-9]+(?:[.,][0-9]+)?)\s*m3\s+DESCARGADOS",
        )
    )
    discharge_start_time = _normalize_time(
        _capture(
            text,
            r"HORA\s+INICIO\s+DESCARGA\s+(\d{1,2}:\d{2}(?::\d{2})?)",
        )
    )
    mixer_operator = _clean_text_value(
        _capture(text, r"OPERADOR\s+MIXER\s*\(nombre\)\s*([^\n]+)")
    )
    site_responsible, lab_sampler = _extract_people(text)

    return SampleTicket(
        sample_number=sample_number,
        guide_number=guide_number,
        text=text,
        truck_number=truck_number,
        guide_m3=guide_m3,
        product_code=product_code,
        grade_type=grade_type,
        load_time=load_time,
        plant_departure_time=plant_departure_time,
        site_arrival_time=site_arrival_time,
        placement=placement,
        sample_date=sample_date,
        sample_time=sample_time,
        ambient_temperature=ambient_temperature,
        mix_temperature=mix_temperature,
        slump_cm=slump_cm,
        specimen_type=specimen_type,
        specimen_count=specimen_count,
        test_ages=test_ages,
        specimen_compaction=specimen_compaction,
        specimen_curing=specimen_curing,
        discharged_m3_at_sample=discharged_m3_at_sample,
        discharge_start_time=discharge_start_time,
        mixer_operator=mixer_operator,
        site_responsible=site_responsible,
        lab_sampler=lab_sampler,
    )
