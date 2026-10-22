from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO
import re
import unicodedata
from typing import Iterable

from pypdf import PdfReader


class ConcreteCertificateParseError(ValueError):
    pass


@dataclass(frozen=True)
class ResistanceResult:
    specimen_no: int | None
    test_date: date | None
    age_days: int
    strength_mpa: float


@dataclass(frozen=True)
class ConcreteCertificate:
    certificate_number: str
    laboratory: str
    issue_date: date | None
    guide_number: str
    sample_ticket_number: str
    concrete_grade: str
    placement: str
    results: tuple[ResistanceResult, ...]
    preliminary_age_days: int | None
    preliminary_strength_mpa: float | None
    r28_1_mpa: float | None
    r28_2_mpa: float | None
    r28_replicated: bool
    observation: str
    text: str

    @property
    def real_result_count(self) -> int:
        return len(self.results)


_MONTHS = {
    "JAN": 1, "ENE": 1, "ENERO": 1, "JANUARY": 1,
    "FEB": 2, "FEBRERO": 2, "FEBRUARY": 2,
    "MAR": 3, "MARZO": 3, "MARCH": 3,
    "APR": 4, "ABR": 4, "ABRIL": 4, "APRIL": 4,
    "MAY": 5, "MAYO": 5,
    "JUN": 6, "JUNIO": 6, "JUNE": 6,
    "JUL": 7, "JULIO": 7, "JULY": 7,
    "AUG": 8, "AGO": 8, "AGOSTO": 8, "AUGUST": 8,
    "SEP": 9, "SEPT": 9, "SEPTIEMBRE": 9, "SETIEMBRE": 9, "SEPTEMBER": 9,
    "OCT": 10, "OCTUBRE": 10, "OCTOBER": 10,
    "NOV": 11, "NOVIEMBRE": 11, "NOVEMBER": 11,
    "DEC": 12, "DIC": 12, "DICIEMBRE": 12, "DECEMBER": 12,
}


def _strip_accents(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def _upper(value: str) -> str:
    return _strip_accents(value).upper()


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _to_float(value: str) -> float | None:
    text = str(value or "").strip().replace(" ", "")
    if not text or text == "-":
        return None
    # Resistencias MPa: 47,6 / 47.6. No interpretar 2.440 como 2440 aquí.
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _parse_date_tokens(day: str, month: str, year: str) -> date | None:
    key = _upper(month).replace(".", "")
    month_no = _MONTHS.get(key)
    if month_no is None:
        key3 = key[:3]
        month_no = _MONTHS.get(key3)
    if month_no is None:
        return None
    try:
        return date(int(year), month_no, int(day))
    except ValueError:
        return None


def _parse_flexible_date(value: str) -> date | None:
    text = _clean(value)
    m = re.search(r"\b(\d{1,2})[-/\s]+([A-Za-zÁÉÍÓÚáéíóúÑñ]{3,12})[-/\s]+(\d{4})\b", text)
    if m:
        return _parse_date_tokens(m.group(1), m.group(2), m.group(3))
    m = re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b", text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def _extract_text(pdf_bytes: bytes) -> str:
    if not pdf_bytes:
        raise ConcreteCertificateParseError("El certificado PDF está vacío.")
    pages: list[str] = []
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        for page in reader.pages:
            pages.append(page.extract_text() or "")
    except Exception as exc:
        raise ConcreteCertificateParseError(f"No fue posible leer el PDF: {exc}") from exc
    text = "\n".join(pages).strip()
    if not text:
        raise ConcreteCertificateParseError("El PDF no contiene texto extraíble.")
    return text


def _extract_certificate_number(text: str) -> str:
    patterns = [
        r"INFORME\s+DE\s+ENSAYO(?:\s+OFICIAL)?\s*N[°ºO]?\s*[:\-]?\s*([0-9][0-9.\-/]*[0-9])",
        r"CERTIFICADO\s*N[°ºO]?\s*[:\-]?\s*([0-9][0-9.\-/]*[0-9])",
        r"INFORME\s+DE\s+ENSAYO(?:\s+OFICIAL)?\s*N[°ºO]?\s*[:\-]?\s*([A-Z0-9][A-Z0-9.\-/]+?)(?=INSCRIPCION|FECHA|\s)",
    ]
    upper = _upper(text)
    for pattern in patterns:
        m = re.search(pattern, upper, flags=re.I)
        if m:
            return m.group(1).strip(" .;:")
    raise ConcreteCertificateParseError("No se pudo identificar el número de certificado.")


def _extract_issue_date(text: str) -> date | None:
    for pattern in (
        r"FECHA\s+DE\s+EMISI[OÓ]N\s*[:\-]?\s*([^\n]+)",
        r"FECHA\s+CERTIFICADO\s*[:\-]?\s*([^\n]+)",
    ):
        m = re.search(pattern, text, flags=re.I)
        if m:
            parsed = _parse_flexible_date(m.group(1))
            if parsed:
                return parsed
    return None


def _extract_guide_number(text: str) -> str:
    upper = _upper(text)
    patterns = [
        r"GUIA\s+DE\s+DESPACHO\s*N[°ºO]?\s*[:\-]?\s*(\d{4,10})",
        r"GUIA\s*N[°ºO]?\s*[:\-]?\s*(\d{4,10})",
    ]
    for pattern in patterns:
        m = re.search(pattern, upper)
        if m:
            return m.group(1)
    return ""


def _extract_simple_field(text: str, label_regex: str, max_len: int = 120) -> str:
    m = re.search(label_regex + r"\s*:\s*([^\n]{1," + str(max_len) + r"})", text, flags=re.I)
    if not m:
        return ""
    value = _clean(m.group(1))
    # Cortar cuando la extracción horizontal arrastra el siguiente encabezado.
    value = re.split(
        r"\s{2,}|\s+(?:GUIA|CAMION|PLANTA|CODIGO|CANTIDAD|COMPACTACION|CURADO|FECHA)\b",
        value,
        maxsplit=1,
        flags=re.I,
    )[0]
    return value.strip(" .;:")


def _extract_lab(text: str) -> str:
    upper = _upper(text)
    if "TECNHOR" in upper:
        return "TECNHOR"
    # Fallback conservador: evita inventar un laboratorio.
    return ""


def _iter_result_lines(text: str) -> Iterable[ResistanceResult]:
    # Línea típica TECNHOR:
    # 1 09 Oct 2026 3 Húmeda No No Cor. 17.640 839 2.440 47,6
    # La expresión exige un valor MPa final; filas pendientes con '-' no cuentan.
    pattern = re.compile(
        r"^\s*(?P<spec>\d{1,3})\s+"
        r"(?P<day>\d{1,2})\s+(?P<month>[A-Za-zÁÉÍÓÚáéíóúÑñ]{3,12})\s+(?P<year>\d{4})\s+"
        r"(?P<age>\d{1,3})\s+.*?"
        r"(?P<strength>\d{1,3}(?:[.,]\d{1,3})?)\s*$",
        flags=re.I,
    )
    for raw in text.splitlines():
        line = _clean(raw)
        m = pattern.match(line)
        if not m:
            continue
        age = int(m.group("age"))
        strength = _to_float(m.group("strength"))
        if strength is None or not (0 < strength < 200):
            continue
        yield ResistanceResult(
            specimen_no=int(m.group("spec")),
            test_date=_parse_date_tokens(m.group("day"), m.group("month"), m.group("year")),
            age_days=age,
            strength_mpa=round(strength, 3),
        )


def _normalise_results(results: tuple[ResistanceResult, ...]) -> tuple[
    int | None, float | None, float | None, float | None, bool, str
]:
    prelim = [r for r in results if r.age_days < 28]
    preliminary_age = max((r.age_days for r in prelim), default=None)
    preliminary_strength = None
    if preliminary_age is not None:
        values = [r.strength_mpa for r in prelim if r.age_days == preliminary_age]
        if values:
            preliminary_strength = round(sum(values) / len(values), 3)

    values28 = [r.strength_mpa for r in results if r.age_days == 28]
    r28_1 = values28[0] if values28 else None
    replicated = False
    if len(values28) >= 2:
        r28_2 = values28[1]
    elif len(values28) == 1:
        r28_2 = values28[0]
        replicated = True
    else:
        r28_2 = None

    notes: list[str] = []
    if replicated:
        notes.append(
            "El certificado informa un solo resultado real a 28 días; "
            "R_28_DIAS_2 replica R_28_DIAS_1 para mantener la estructura de cálculo."
        )
    if preliminary_age is not None:
        count_same_age = sum(1 for r in prelim if r.age_days == preliminary_age)
        notes.append(
            f"Resultado preliminar calculado con {count_same_age} resultado(s) "
            f"real(es) a {preliminary_age} día(s)."
        )
    return preliminary_age, preliminary_strength, r28_1, r28_2, replicated, " ".join(notes)


def parse_concrete_certificate(pdf_bytes: bytes, filename: str = "") -> ConcreteCertificate:
    text = _extract_text(pdf_bytes)
    certificate_number = _extract_certificate_number(text)
    results = tuple(_iter_result_lines(text))
    if not results:
        # Un certificado preliminar podría eventualmente llegar sin resultados,
        # pero no es útil para poblar la tabla de resistencia y debe revisarse.
        raise ConcreteCertificateParseError(
            f"Certificado {certificate_number}: no se encontraron resultados reales de resistencia."
        )

    prelim_age, prelim_value, r28_1, r28_2, replicated, observation = _normalise_results(results)

    return ConcreteCertificate(
        certificate_number=certificate_number,
        laboratory=_extract_lab(text),
        issue_date=_extract_issue_date(text),
        guide_number=_extract_guide_number(text),
        sample_ticket_number=_extract_simple_field(text, r"N[°ºO]?\s+DE\s+BOLETA\s+DE\s+MUESTREO"),
        concrete_grade=(
            (re.search(
                r"GRADO\s*/\s*TIPO\s*:\s*(.+?)(?=\s+GU[IÍ]A\s+DE\s+DESPACHO|$)",
                text,
                flags=re.I,
            ).group(1).strip()
             if re.search(
                r"GRADO\s*/\s*TIPO\s*:\s*(.+?)(?=\s+GU[IÍ]A\s+DE\s+DESPACHO|$)",
                text,
                flags=re.I,
             ) else _extract_simple_field(text, r"GRADO\s*/\s*TIPO"))
        ),
        placement=_extract_simple_field(text, r"COLOCADO\s+EN(?:\s*\(1\))?"),
        results=results,
        preliminary_age_days=prelim_age,
        preliminary_strength_mpa=prelim_value,
        r28_1_mpa=r28_1,
        r28_2_mpa=r28_2,
        r28_replicated=replicated,
        observation=observation,
        text=text,
    )
