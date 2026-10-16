from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable

from pypdf import PdfReader


class FierroInvoiceParseError(RuntimeError):
    pass


@dataclass(frozen=True)
class FierroInvoiceItem:
    line_number: int
    codigo_producto: str
    descripcion: str
    diametro_mm: Decimal
    largo_m: Decimal
    hornada: str
    kg_facturados: Decimal
    precio_kg: Decimal
    total_item: int


@dataclass(frozen=True)
class FierroInvoiceGuideReference:
    numero: str
    fecha: date | None


@dataclass(frozen=True)
class FierroInvoice:
    numero_factura: str
    rut_emisor: str
    razon_social_emisor: str
    fecha_emision: date
    fecha_vencimiento: date | None
    orden_compra: str
    direccion_destino: str
    comuna_destino: str
    neto_factura: int
    iva_factura: int
    total_factura: int
    items: tuple[FierroInvoiceItem, ...]
    guias: tuple[FierroInvoiceGuideReference, ...]
    raw_text: str

    @property
    def total_kg_facturados(self) -> Decimal:
        return sum((item.kg_facturados for item in self.items), Decimal("0"))


_DATE_RE = r"(?P<day>\d{2})[-/]((?P<month>\d{2}))[-/](?P<year>\d{4})"


def _clean_text(value: str) -> str:
    text = value.replace("\u00a0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def _first_group(pattern: str, text: str, *, flags: int = 0, field: str) -> str:
    match = re.search(pattern, text, flags)
    if not match:
        raise FierroInvoiceParseError(f"No fue posible extraer {field}.")
    return match.group(1).strip()


def _optional_group(pattern: str, text: str, *, flags: int = 0) -> str:
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else ""


def _parse_date(value: str) -> date:
    value = value.strip().replace("/", "-")
    try:
        return datetime.strptime(value, "%d-%m-%Y").date()
    except ValueError as exc:
        raise FierroInvoiceParseError(f"Fecha inválida en factura: {value!r}.") from exc


def _parse_decimal_cl(value: str) -> Decimal:
    text = str(value or "").strip().replace("$", "").replace(" ", "")
    if not text:
        return Decimal("0")

    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        # Para cantidades como 1.076 en estos DTE, el punto es separador de miles
        # sólo cuando hay grupos de tres dígitos. En las líneas reales de DSC las
        # cantidades vienen sin separador, por lo que este caso se usa sobre todo
        # para importes CLP.
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", text):
            text = text.replace(".", "")

    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise FierroInvoiceParseError(f"Número inválido en factura: {value!r}.") from exc


def _parse_money_int(value: str) -> int:
    amount = _parse_decimal_cl(value)
    return int(amount.quantize(Decimal("1")))


def extract_pdf_text(pdf_bytes: bytes) -> str:
    if not pdf_bytes.startswith(b"%PDF-"):
        raise FierroInvoiceParseError("El archivo recibido no parece ser un PDF válido.")

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:
        raise FierroInvoiceParseError(f"No fue posible leer el PDF: {exc}") from exc

    text = _clean_text("\n".join(pages))
    if not text:
        raise FierroInvoiceParseError(
            "El PDF no contiene texto extraíble. Este módulo todavía no usa OCR."
        )
    return text


def _parse_guide_references(text: str) -> tuple[FierroInvoiceGuideReference, ...]:
    refs: list[FierroInvoiceGuideReference] = []

    pattern = re.compile(
        r"GU[IÍ]A\s+DE\s+DESPACHO(?:\s*\n\s*ELECTR[ÓO]NICA)?\s*\n?\s*"
        r"(?P<number>\d{3,})\s+(?P<date>\d{2}[-/]\d{2}[-/]\d{4})",
        re.IGNORECASE,
    )

    for match in pattern.finditer(text):
        number = match.group("number")
        date_value = _parse_date(match.group("date"))
        refs.append(FierroInvoiceGuideReference(numero=number, fecha=date_value))

    # Fallback para PDFs donde el salto de línea de "ELECTRÓNICA" cambia.
    if not refs:
        block = _optional_group(
            r"Tipo Doc\. Referenciado.*?(?=Cant\.\s+C[oó]digo)",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if block:
            compact = " ".join(block.split())
            match = re.search(
                r"GU[IÍ]A DE DESPACHO(?: ELECTR[ÓO]NICA)?\s+(\d{3,})\s+"
                r"(\d{2}[-/]\d{2}[-/]\d{4})",
                compact,
                re.IGNORECASE,
            )
            if match:
                refs.append(
                    FierroInvoiceGuideReference(
                        numero=match.group(1),
                        fecha=_parse_date(match.group(2)),
                    )
                )

    return tuple(refs)


def _iter_item_matches(text: str) -> Iterable[re.Match[str]]:
    # Formato DSC original: el material FE A630 aparece en la primera línea
    # y vuelve a repetirse junto con la hornada en la segunda.
    standard_pattern = re.compile(
        r"(?m)^\s*(?P<qty>\d+(?:[.,]\d+)?)\s+"
        r"(?P<code>[A-Z0-9_-]+)\s+"
        r"(?P<desc>FE\s+A630-420H\s+\d+(?:[.,]\d+)?mm\s+x\s+\d+(?:[.,]\d+)?\s*mts?\.)\s*\n"
        r"\s*FE\s+A630-420H\s+\d+(?:[.,]\d+)?mm\s+x\s+\d+(?:[.,]\d+)?\s*mts?\.\s*"
        r"Hornada:\[(?P<hornada>[^\]]+)\]\s*\n"
        r"\s*\$\s*(?P<price>[\d.]+(?:,\d{1,2})?)\s+"
        r"(?:\$\s*(?P<discount>[\d.]+(?:,\d{1,2})?)\s+)?"
        r"\$\s*(?P<total>[\d.]+(?:,\d{1,2})?)\s*$",
        re.IGNORECASE,
    )

    # Formato DSC de servicios (observado en factura 26823):
    #   2010 800100105 SERVICIOS FIERRO BOD.CENTRAL
    #   FE A630-420H 25mm x 9 mts. Hornada:[B00037771]
    #   $ 720,00 $ 1.447.200
    #
    # Se conserva el código documental (p.ej. 800100105), pero el material real
    # se toma desde la segunda línea. El negative lookahead evita duplicar líneas
    # del formato original.
    service_pattern = re.compile(
        r"(?m)^\s*(?P<qty>\d+(?:[.,]\d+)?)\s+"
        r"(?P<code>[A-Z0-9_-]+)\s+"
        r"(?!FE\s+A630-420H\b)[^\n]+\s*\n"
        r"\s*(?P<desc>FE\s+A630-420H\s+\d+(?:[.,]\d+)?mm\s+x\s+\d+(?:[.,]\d+)?\s*mts?\.)\s*"
        r"Hornada:\[(?P<hornada>[^\]]+)\]\s*\n"
        r"\s*\$\s*(?P<price>[\d.]+(?:,\d{1,2})?)\s+"
        r"(?:\$\s*(?P<discount>[\d.]+(?:,\d{1,2})?)\s+)?"
        r"\$\s*(?P<total>[\d.]+(?:,\d{1,2})?)\s*$",
        re.IGNORECASE,
    )

    matches = list(standard_pattern.finditer(text))
    matches.extend(service_pattern.finditer(text))
    matches.sort(key=lambda match: match.start())
    return iter(matches)


def _parse_items(text: str) -> tuple[FierroInvoiceItem, ...]:
    items: list[FierroInvoiceItem] = []

    for index, match in enumerate(_iter_item_matches(text), start=1):
        description = re.sub(r"\s+", " ", match.group("desc")).strip()

        material = re.search(
            r"(?P<diameter>\d+(?:[.,]\d+)?)mm\s+x\s+"
            r"(?P<length>\d+(?:[.,]\d+)?)\s*mts?",
            description,
            re.IGNORECASE,
        )
        if not material:
            raise FierroInvoiceParseError(
                f"No fue posible interpretar diámetro/largo del ítem {index}: {description!r}."
            )

        items.append(
            FierroInvoiceItem(
                line_number=index,
                codigo_producto=match.group("code").strip(),
                descripcion=description,
                diametro_mm=_parse_decimal_cl(material.group("diameter")),
                largo_m=_parse_decimal_cl(material.group("length")),
                hornada=match.group("hornada").strip(),
                kg_facturados=_parse_decimal_cl(match.group("qty")),
                precio_kg=_parse_decimal_cl(match.group("price")),
                total_item=_parse_money_int(match.group("total")),
            )
        )

    if not items:
        raise FierroInvoiceParseError(
            "No se encontraron líneas de fierro reconocibles en la factura."
        )

    return tuple(items)


def parse_fierro_invoice(pdf_bytes: bytes) -> FierroInvoice:
    text = extract_pdf_text(pdf_bytes)

    invoice_number = _first_group(
        r"FACTURA\s+ELECTR[ÓO]NICA\s*\n\s*N[°º]?\s*(\d+)",
        text,
        flags=re.IGNORECASE,
        field="N_FACTURA",
    )

    issuer_rut = _first_group(
        r"R\.U\.T\.:\s*([0-9.]+-[0-9Kk])",
        text,
        flags=re.IGNORECASE,
        field="RUT_EMISOR",
    )

    issuer_name = _optional_group(
        r"^\s*(DSC\s+Spa)",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    ) or "DSC Spa"

    emission_date = _parse_date(
        _first_group(
            r"Fecha\s+Emisi[oó]n\s*:\s*(\d{2}[-/]\d{2}[-/]\d{4})",
            text,
            flags=re.IGNORECASE,
            field="FECHA_EMISION",
        )
    )

    due_raw = _optional_group(
        r"Fecha\s+Vencimiento\s*:\s*(\d{2}[-/]\d{2}[-/]\d{4})",
        text,
        flags=re.IGNORECASE,
    )
    due_date = _parse_date(due_raw) if due_raw else None

    purchase_order = _optional_group(
        r"ORDEN\s+DE\s+COMPRA\s+([A-Z0-9-]+)\s+\d{2}[-/]\d{2}[-/]\d{4}",
        text,
        flags=re.IGNORECASE,
    )

    destination_commune = _optional_group(
        r"Comuna\s+Destino\s*:\s*([^\n]+?)(?:\s+Ciudad\s+Destino\s*:|$)",
        text,
        flags=re.IGNORECASE,
    )

    destination_address = _optional_group(
        r"Direcci[oó]n\s+Destino\s*:\s*([^\n]+)",
        text,
        flags=re.IGNORECASE,
    )

    net_amount = _parse_money_int(
        _first_group(
            r"TOTAL\s+NETO\s*:\s*\$\s*([\d.]+(?:,\d{1,2})?)",
            text,
            flags=re.IGNORECASE,
            field="NETO_FACTURA",
        )
    )
    vat_amount = _parse_money_int(
        _first_group(
            r"TOTAL\s+I\.V\.A\.\s*\(19%\)\s*:\s*\$\s*([\d.]+(?:,\d{1,2})?)",
            text,
            flags=re.IGNORECASE,
            field="IVA_FACTURA",
        )
    )
    total_amount = _parse_money_int(
        _first_group(
            r"MONTO\s+TOTAL\s*:\s*\$\s*([\d.]+(?:,\d{1,2})?)",
            text,
            flags=re.IGNORECASE,
            field="TOTAL_FACTURA",
        )
    )

    items = _parse_items(text)
    guides = _parse_guide_references(text)

    return FierroInvoice(
        numero_factura=invoice_number,
        rut_emisor=issuer_rut,
        razon_social_emisor=issuer_name,
        fecha_emision=emission_date,
        fecha_vencimiento=due_date,
        orden_compra=purchase_order,
        direccion_destino=destination_address,
        comuna_destino=destination_commune,
        neto_factura=net_amount,
        iva_factura=vat_amount,
        total_factura=total_amount,
        items=items,
        guias=guides,
        raw_text=text,
    )
