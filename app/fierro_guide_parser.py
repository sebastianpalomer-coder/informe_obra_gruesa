from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from pypdf import PdfReader


class FierroGuideParseError(RuntimeError):
    pass


@dataclass(frozen=True)
class FierroGuideItem:
    line_number: int
    codigo_producto: str
    descripcion: str
    diametro_mm: Decimal
    largo_m: Decimal
    hornada: str
    kg_despachados: Decimal
    precio_kg: Decimal
    total_item: int


@dataclass(frozen=True)
class FierroGuide:
    numero_guia: str
    rut_emisor: str
    razon_social_emisor: str
    fecha_guia: date
    orden_compra: str
    direccion_destino: str
    comuna_destino: str
    chofer: str
    rut_chofer: str
    patente: str
    neto_guia: int
    iva_guia: int
    total_guia: int
    total_kg_documento: Decimal | None
    items: tuple[FierroGuideItem, ...]
    raw_text: str

    @property
    def total_kg_despachados(self) -> Decimal:
        return sum((item.kg_despachados for item in self.items), Decimal("0"))


def _clean_text(value: str) -> str:
    text = value.replace("\u00a0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def _optional_group(pattern: str, text: str, *, flags: int = 0) -> str:
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else ""


def _first_group(pattern: str, text: str, *, flags: int = 0, field: str) -> str:
    value = _optional_group(pattern, text, flags=flags)
    if not value:
        raise FierroGuideParseError(f"No fue posible extraer {field}.")
    return value


def _parse_date(value: str) -> date:
    normalized = str(value or "").strip().replace("-", "/")
    try:
        return datetime.strptime(normalized, "%d/%m/%Y").date()
    except ValueError as exc:
        raise FierroGuideParseError(f"Fecha inválida en guía: {value!r}.") from exc


def _parse_decimal(value: str) -> Decimal:
    text = str(value or "").strip().replace("$", "").replace(" ", "")
    if not text:
        return Decimal("0")

    # En estas guías DSC las comas son separadores de miles (12,967 / 1,447,200).
    # Si aparece una sola coma con 1-2 decimales, se interpreta como decimal.
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+", text):
        text = text.replace(",", "")
    elif re.fullmatch(r"\d+,\d{1,2}", text):
        text = text.replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", text):
        text = text.replace(".", "")
    elif "," in text and "." not in text:
        text = text.replace(",", ".")

    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise FierroGuideParseError(f"Número inválido en guía: {value!r}.") from exc


def _parse_money_int(value: str) -> int:
    return int(_parse_decimal(value).quantize(Decimal("1")))


def extract_pdf_text(pdf_bytes: bytes) -> str:
    if not pdf_bytes.startswith(b"%PDF-"):
        raise FierroGuideParseError("El archivo recibido no parece ser un PDF válido.")

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:
        raise FierroGuideParseError(f"No fue posible leer el PDF: {exc}") from exc

    text = _clean_text("\n".join(pages))
    if not text:
        raise FierroGuideParseError(
            "El PDF no contiene texto extraíble. Este módulo todavía no usa OCR."
        )
    return text


def _guide_number(text: str, filename: str) -> str:
    patterns = [
        r"GU[IÍ]A\s+DE\s+DESPACHO\s+ELECTR[ÓO]NICA.*?N[°º]?\s*(\d{3,})",
        r"N[°º]\s*(\d{3,})",
    ]
    for pattern in patterns:
        value = _optional_group(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if value:
            return value

    # En el PDF real de DSC el encabezado rojo es imagen y pypdf no extrae el
    # folio. El archivo original sí incluye el número en el nombre.
    base = str(filename or "")
    candidates = re.findall(r"(?<!\d)(\d{4,8})(?!\d)", base)
    if candidates:
        return candidates[-1]

    raise FierroGuideParseError(
        "No fue posible extraer N_GUIA del PDF ni del nombre del archivo."
    )


def _parse_items(text: str) -> tuple[FierroGuideItem, ...]:
    pattern = re.compile(
        r"(?m)^\s*(?P<code>[A-Z0-9_-]+)\s+"
        r"(?P<qty>\d+(?:[.,]\d+)?)\s+"
        r"(?P<desc>FE\s+A630-420H\s+\d+(?:[.,]\d+)?mm\s+x\s+"
        r"\d+(?:[.,]\d+)?\s*mts?\.\s*Hornada:\[(?P<hornada>[^\]]+)\])\s+"
        r"(?P<qty2>\d+(?:[.,]\d+)?)\s+"
        r"(?P<total>[\d.,]+)\s*$",
        re.IGNORECASE,
    )

    items: list[FierroGuideItem] = []
    for index, match in enumerate(pattern.finditer(text), start=1):
        description = re.sub(r"\s+", " ", match.group("desc")).strip()
        material = re.search(
            r"(?P<diameter>\d+(?:[.,]\d+)?)mm\s+x\s+"
            r"(?P<length>\d+(?:[.,]\d+)?)\s*mts?",
            description,
            re.IGNORECASE,
        )
        if not material:
            raise FierroGuideParseError(
                f"No fue posible interpretar diámetro/largo del ítem {index}: {description!r}."
            )

        qty = _parse_decimal(match.group("qty"))
        qty2 = _parse_decimal(match.group("qty2"))
        if qty != qty2:
            raise FierroGuideParseError(
                f"Cantidad inconsistente en línea {index}: {qty} vs {qty2}."
            )

        total = _parse_money_int(match.group("total"))
        price = (Decimal(total) / qty) if qty else Decimal("0")
        price = price.quantize(Decimal("0.0001")).normalize()

        items.append(
            FierroGuideItem(
                line_number=index,
                codigo_producto=match.group("code").strip(),
                descripcion=description,
                diametro_mm=_parse_decimal(material.group("diameter")),
                largo_m=_parse_decimal(material.group("length")),
                hornada=match.group("hornada").strip(),
                kg_despachados=qty,
                precio_kg=price,
                total_item=total,
            )
        )

    if not items:
        raise FierroGuideParseError(
            "No se encontraron líneas de fierro reconocibles en la guía."
        )

    return tuple(items)


def parse_fierro_guide(pdf_bytes: bytes, filename: str = "") -> FierroGuide:
    text = extract_pdf_text(pdf_bytes)

    numero = _guide_number(text, filename)
    fecha = _parse_date(
        _first_group(
            r"EMISION\s*:\s*(\d{2}[/\-]\d{2}[/\-]\d{4})",
            text,
            flags=re.IGNORECASE,
            field="FECHA_GUIA",
        )
    )

    orden_compra = _optional_group(
        r"Orden\s+de\s+Compra\s+([A-Z0-9-]+)\s+\d{2}[/\-]\d{2}[/\-]\d{4}",
        text,
        flags=re.IGNORECASE,
    )

    direccion = _first_group(
        r"LUGAR\s+DESP\.\s*:\s*[^\n]*\nDIRECCION\s*:\s*([^\n]+?)(?:\s+FLETE\s*$|$)",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
        field="DIRECCION_DESTINO",
    )
    direccion = re.sub(r"\s+FLETE\s*$", "", direccion, flags=re.IGNORECASE).strip()

    comuna = _optional_group(
        r"PATENTE\s*:\s*[A-Z0-9-]+[^\n]*\nCOMUNA\s*:\s*([^\n]+)$",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    chofer = _optional_group(
        r"CHOFER\s*:\s*([^\n]+?)(?:\s+19%\s+IVA|$)",
        text,
        flags=re.IGNORECASE,
    )
    rut_chofer = _optional_group(
        r"RUT\s*:\s*([0-9.]+-[0-9Kk])\s+PATENTE",
        text,
        flags=re.IGNORECASE,
    )
    patente = _optional_group(
        r"PATENTE\s*:\s*([A-Z0-9-]+)",
        text,
        flags=re.IGNORECASE,
    )

    neto = _parse_money_int(
        _first_group(
            r"NETO\s+([\d.,]+)",
            text,
            flags=re.IGNORECASE,
            field="NETO_GUIA",
        )
    )
    iva = _parse_money_int(
        _first_group(
            r"19%\s+IVA\s+([\d.,]+)",
            text,
            flags=re.IGNORECASE,
            field="IVA_GUIA",
        )
    )
    total = _parse_money_int(
        _first_group(
            r"TOTAL\s+([\d.,]+)",
            text,
            flags=re.IGNORECASE,
            field="TOTAL_GUIA",
        )
    )

    items = _parse_items(text)

    kg_doc_raw = _optional_group(
        r"(?m)^\s*([\d.,]+)\s*$\nLUGAR\s+DE\s+DESPACHO",
        text,
        flags=re.IGNORECASE,
    )
    kg_doc = _parse_decimal(kg_doc_raw) if kg_doc_raw else None

    # En este formato de DSC el RUT emisor y el folio están contenidos en el
    # encabezado gráfico; pypdf puede no exponerlos como texto. Se usa el dato
    # estable del emisor de este parser específico.
    issuer_rut = _optional_group(
        r"R\.U\.T\.?\s*[:.]?\s*([0-9.]+-[0-9Kk])",
        text,
        flags=re.IGNORECASE,
    ) or "76.871.322-7"

    issuer_name = _optional_group(
        r"^\s*(DSC\s+Spa)\s*$",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    ) or "DSC Spa"

    return FierroGuide(
        numero_guia=numero,
        rut_emisor=issuer_rut,
        razon_social_emisor=issuer_name,
        fecha_guia=fecha,
        orden_compra=orden_compra,
        direccion_destino=direccion,
        comuna_destino=comuna,
        chofer=chofer,
        rut_chofer=rut_chofer,
        patente=patente,
        neto_guia=neto,
        iva_guia=iva,
        total_guia=total,
        total_kg_documento=kg_doc,
        items=items,
        raw_text=text,
    )
