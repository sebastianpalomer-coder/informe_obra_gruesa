from __future__ import annotations

import csv
import io
import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import google.auth
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from openpyxl import load_workbook
try:
    import xlrd
except ImportError:  # permite iniciar el servicio; .xls requerirá instalar xlrd
    xlrd = None

logger = logging.getLogger(__name__)

VERSION = "1.11.1-subcontratos-iconstruye"

# -----------------------------------------------------------------------------
# Configuración fija del proyecto Hotel Bellet, sobreescribible por variables.
# -----------------------------------------------------------------------------
FOLDER_ID = os.getenv(
    "SUBCONTRATOS_FOLDER_ID",
    "1iu7StPjp6PpEQHEK5XmODpY2RfjvKoZr",
).strip()

SPREADSHEET_ID = os.getenv(
    "SUBCONTRATOS_SPREADSHEET_ID",
    "1uj0eoHHiG6wKQwkzRIQUSqVOOqNOv7CPhYhcXGq61vY",
).strip()

EXPECTED_CENTRO_GESTION = os.getenv(
    "SUBCONTRATOS_CENTRO_GESTION",
    "2470 BELLET - HOTEL BELLET",
).strip()

MAX_FILE_BYTES = int(os.getenv("SUBCONTRATOS_MAX_FILE_BYTES", str(20 * 1024 * 1024)))
MAX_BATCH_SPAN_MINUTES = int(os.getenv("SUBCONTRATOS_LOTE_MAX_SPAN_MIN", "180"))

TABLE_SC = os.getenv("SUBCONTRATOS_TABLE_SC", "REPORTE_SC").strip()
TABLE_DETALLE_SC = os.getenv(
    "SUBCONTRATOS_TABLE_DETALLE_SC", "REPORTE_DETALLE_SC"
).strip()
TABLE_EP = os.getenv("SUBCONTRATOS_TABLE_EP", "REPORTE_EP").strip()
TABLE_DETALLE_EP = os.getenv(
    "SUBCONTRATOS_TABLE_DETALLE_EP", "REPORTE_DETALLE_EP"
).strip()
TABLE_GARANTIAS_SC = os.getenv(
    "SUBCONTRATOS_TABLE_GARANTIAS_SC", "REPORTE_GARANTIAS_SC"
).strip()

TABLES = (TABLE_SC, TABLE_DETALLE_SC, TABLE_EP, TABLE_DETALLE_EP, TABLE_GARANTIAS_SC)

GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
GOOGLE_OAUTH_REFRESH_TOKEN = os.getenv("GOOGLE_OAUTH_REFRESH_TOKEN", "").strip()
GOOGLE_OAUTH_TOKEN_URI = os.getenv(
    "GOOGLE_OAUTH_TOKEN_URI", "https://oauth2.googleapis.com/token"
).strip()

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]


EXPECTED_HEADERS: dict[str, list[str]] = {
    TABLE_SC: [
        "ID_SC",
        "TIPO_SUBCONTRATO",
        "NOMBRE_SC",
        "CENTRO_GESTION",
        "RUT_SUBCONTRATISTA",
        "NOMBRE_SUBCONTRATISTA",
        "MONEDA_SC",
        "TASA_CAMBIO",
        "MONTO_ORIGINAL",
        "MONTO_DESCUENTO",
        "MONTO_ANEXOS",
        "MONTO_DIF_PU",
        "MONTO_TOTAL_NETO",
        "ANTICIPO_PACTADO",
        "ANTICIPO_PAGADO",
        "SALDO_ANTICIPO_POR_PAGAR",
        "ANTICIPO_DESCONTADO",
        "SALDO_ANTICIPO_POR_DESCONTAR",
        "RETENCIONES_PACTADAS",
        "RETENCIONES_ACUMULADAS",
        "SALDO_RETENCIONES",
        "RETENCIONES_PAGADAS",
        "PRODUCCION_EP_AVANCE",
        "TOTAL_PAGO_NETO",
        "REAJUSTES",
        "DESC_SIN_IVA_EP",
        "DESC_CON_IVA_EP",
        "EP_APROBADOS",
        "PRODUCCION_TOTAL",
        "SALDO",
        "SALDO_TERMINO_ANTICIPADO",
        "EP_FACTURADOS",
        "FECHA_CREACION",
        "FECHA_INICIO",
        "FECHA_TERMINO",
        "ESTADO",
    ],
    TABLE_DETALLE_SC: [
        "ID_SC_DETALLE",
        "ID_SC",
        "N_LINEA_SC",
        "TIPO_SUBCONTRATO",
        "CENTRO_GESTION",
        "RAZON_SOCIAL",
        "RUT_SUBCONTRATISTA",
        "NOMBRE_SUBCONTRATISTA",
        "CODIGO_SERVICIO",
        "DESCRIPCION_SERVICIO",
        "GLOSA",
        "UNIDAD_MEDIDA",
        "MONEDA",
        "TASA_CAMBIO",
        "CANTIDAD_ORIGINAL",
        "MONTO_DIF_MODIF_PU",
        "CANTIDAD_CORREGIDA",
        "PRECIO_UNITARIO",
        "PRECIO_UNITARIO_CON_DESCUENTO",
        "TOTAL_UNITARIO",
        "CODIGO_CUENTA_COSTO",
        "DESCRIPCION_CUENTA_COSTO",
        "CANTIDAD_AVANZADA",
        "TOTAL_AVANCE",
        "SALDO",
        "MONTO_ASOCIADO_FACTURA",
        "FECHA_CREACION",
    ],
    TABLE_EP: [
        "ID_EP",
        "ID_SC",
        "NOMBRE_EP",
        "CENTRO_GESTION",
        "RUT_SUBCONTRATISTA",
        "NOMBRE_SUBCONTRATISTA",
        "EMITE_FACTURA",
        "MONEDA_EP",
        "MONTO_BRUTO_EP",
        "DEVOLUCION_ANTICIPO",
        "RETENCIONES",
        "REAJUSTES",
        "DESCUENTOS_SIN_IVA",
        "DESCUENTOS_CON_IVA",
        "TOTAL_PAGO_NETO",
        "IVA",
        "MONTO_EP_FACTURADO",
        "N_FACTURA",
        "FECHA_EP",
        "TIPO_DOCUMENTO",
        "ESTADO_DOCUMENTO",
    ],
    TABLE_DETALLE_EP: [
        "ID_EP_DETALLE",
        "ID_EP",
        "ID_SC",
        "ID_SC_DETALLE",
        "N_LINEA_SC",
        "CENTRO_GESTION",
        "CODIGO_CUENTA_COSTO",
        "DESCRIPCION_CUENTA_COSTO",
        "MONEDA_SC",
        "TASA_CAMBIO_SC",
        "NOMBRE_SC",
        "RUT_SUBCONTRATISTA",
        "NOMBRE_SUBCONTRATISTA",
        "DESCRIPCION_LINEA",
        "CANTIDAD_ORIGINAL",
        "CANTIDAD_CORREGIDA",
        "PRECIO_UNITARIO",
        "PRECIO_TOTAL",
        "TIPO_EP",
        "CANTIDAD_EP",
        "MONTO_EP",
        "ESTADO_DOCUMENTO",
    ],
    TABLE_GARANTIAS_SC: [
        "ID_GARANTIA_SC",
        "ID_SC",
        "NOMBRE_SC",
        "ESTADO_SC",
        "CENTRO_GESTION",
        "RUT_SUBCONTRATISTA",
        "NOMBRE_SUBCONTRATISTA",
        "TIPO_GARANTIA",
        "MONEDA_GARANTIA",
        "MONTO_GARANTIA",
        "TIPO_DOCUMENTO_GARANTIA",
        "FECHA_VENCIMIENTO",
        "VENCIDA",
    ],
}


NUMBER_COLUMNS: dict[str, set[str]] = {
    TABLE_SC: {
        "TASA_CAMBIO", "MONTO_ORIGINAL", "MONTO_DESCUENTO", "MONTO_ANEXOS",
        "MONTO_DIF_PU", "MONTO_TOTAL_NETO", "ANTICIPO_PACTADO", "ANTICIPO_PAGADO",
        "SALDO_ANTICIPO_POR_PAGAR", "ANTICIPO_DESCONTADO",
        "SALDO_ANTICIPO_POR_DESCONTAR", "RETENCIONES_PACTADAS",
        "RETENCIONES_ACUMULADAS", "SALDO_RETENCIONES", "RETENCIONES_PAGADAS",
        "PRODUCCION_EP_AVANCE", "TOTAL_PAGO_NETO", "REAJUSTES",
        "DESC_SIN_IVA_EP", "DESC_CON_IVA_EP", "EP_APROBADOS", "PRODUCCION_TOTAL",
        "SALDO", "SALDO_TERMINO_ANTICIPADO", "EP_FACTURADOS",
    },
    TABLE_DETALLE_SC: {
        "TASA_CAMBIO", "CANTIDAD_ORIGINAL", "MONTO_DIF_MODIF_PU",
        "CANTIDAD_CORREGIDA", "PRECIO_UNITARIO", "PRECIO_UNITARIO_CON_DESCUENTO",
        "TOTAL_UNITARIO", "CANTIDAD_AVANZADA", "TOTAL_AVANCE", "SALDO",
        "MONTO_ASOCIADO_FACTURA",
    },
    TABLE_EP: {
        "MONTO_BRUTO_EP", "DEVOLUCION_ANTICIPO", "RETENCIONES", "REAJUSTES",
        "DESCUENTOS_SIN_IVA", "DESCUENTOS_CON_IVA", "TOTAL_PAGO_NETO", "IVA",
        "MONTO_EP_FACTURADO",
    },
    TABLE_DETALLE_EP: {
        "TASA_CAMBIO_SC", "CANTIDAD_ORIGINAL", "CANTIDAD_CORREGIDA",
        "PRECIO_UNITARIO", "PRECIO_TOTAL", "CANTIDAD_EP", "MONTO_EP",
    },
    TABLE_GARANTIAS_SC: {"MONTO_GARANTIA"},
}

DATE_COLUMNS: dict[str, set[str]] = {
    TABLE_SC: {"FECHA_CREACION", "FECHA_INICIO", "FECHA_TERMINO"},
    TABLE_DETALLE_SC: {"FECHA_CREACION"},
    TABLE_EP: {"FECHA_EP"},
    TABLE_DETALLE_EP: set(),
    TABLE_GARANTIAS_SC: {"FECHA_VENCIMIENTO"},
}


SOURCE_MAP_SC = {
    "ID_SC": ["Nº Subcontrato", "N° Subcontrato", "Numero Subcontrato", "Número Subcontrato"],
    "TIPO_SUBCONTRATO": ["Tipo Subcontrato"],
    "NOMBRE_SC": ["Nombre", "Nombre Subcontrato"],
    "CENTRO_GESTION": ["Centro Gestión", "Centro de Gestion", "Centro de Gestión"],
    "RUT_SUBCONTRATISTA": ["RUT Subcontratista"],
    "NOMBRE_SUBCONTRATISTA": ["Nombre Subcontratista"],
    "MONEDA_SC": ["Moneda Subcontrato"],
    "TASA_CAMBIO": ["Tasa Cambio", "Tasa de Cambio"],
    "MONTO_ORIGINAL": ["Monto Original"],
    "MONTO_DESCUENTO": ["Monto Descuento"],
    "MONTO_ANEXOS": ["Monto Anexos"],
    "MONTO_DIF_PU": ["Monto Dif. PU"],
    "MONTO_TOTAL_NETO": ["Monto Total Neto"],
    "ANTICIPO_PACTADO": ["Anticipo Pactado"],
    "ANTICIPO_PAGADO": ["Anticipo Pagado"],
    "SALDO_ANTICIPO_POR_PAGAR": ["Saldo Anticipo por Pagar"],
    "ANTICIPO_DESCONTADO": ["Anticipo Descontado"],
    "SALDO_ANTICIPO_POR_DESCONTAR": ["Saldo Anticipo Por Descontar"],
    "RETENCIONES_PACTADAS": ["Retenciones Pactadas"],
    "RETENCIONES_ACUMULADAS": ["Retenciones Acumuladas"],
    "SALDO_RETENCIONES": ["Saldo Retenciones"],
    "RETENCIONES_PAGADAS": ["Retenciones Pagadas"],
    "PRODUCCION_EP_AVANCE": ["Produccion EP Avance", "Producción EP Avance"],
    "TOTAL_PAGO_NETO": ["Total Pago Neto"],
    "REAJUSTES": ["Reajustes"],
    "DESC_SIN_IVA_EP": ["Desc. S/IVA Estado Pago"],
    "DESC_CON_IVA_EP": ["Desc. C/IVA Estado Pago"],
    "EP_APROBADOS": ["Estado de Pago Aprobados"],
    "PRODUCCION_TOTAL": ["Produccion Total", "Producción Total"],
    "SALDO": ["Saldo"],
    "SALDO_TERMINO_ANTICIPADO": ["Saldo Termino Anticipado", "Saldo Término Anticipado"],
    "EP_FACTURADOS": ["Estado de Pago Facturados"],
    "FECHA_CREACION": ["Fecha Creación", "Fecha Creacion"],
    "FECHA_INICIO": ["Fecha Inicio"],
    "FECHA_TERMINO": ["Fecha Termino", "Fecha Término"],
    "ESTADO": ["Estado"],
}

SOURCE_MAP_DETALLE_SC = {
    "ID_SC": ["Nº Subcontrato", "N° Subcontrato", "Numero Subcontrato", "Número Subcontrato"],
    "N_LINEA_SC": ["N° Linea", "Nº Linea", "N° Línea", "Nº Línea"],
    "TIPO_SUBCONTRATO": ["Tipo Subcontrato"],
    "CENTRO_GESTION": ["Centro Gestión", "Centro de Gestion", "Centro de Gestión"],
    "RAZON_SOCIAL": ["Razón Social", "Razon Social"],
    "RUT_SUBCONTRATISTA": ["RUT Subcontratista"],
    "NOMBRE_SUBCONTRATISTA": ["Nombre Subcontratista"],
    "CODIGO_SERVICIO": ["Código del Servicio o Actividad", "Codigo del Servicio o Actividad"],
    "DESCRIPCION_SERVICIO": ["Descripción del Servicio o Actividad", "Descripcion del Servicio o Actividad"],
    "GLOSA": ["Glosa"],
    "UNIDAD_MEDIDA": ["Unidad Medida"],
    "MONEDA": ["Moneda"],
    "TASA_CAMBIO": ["Tasa de Cambio", "Tasa Cambio"],
    "CANTIDAD_ORIGINAL": ["Cantidad Original"],
    "MONTO_DIF_MODIF_PU": ["Monto Dif. Modif. PU"],
    "CANTIDAD_CORREGIDA": ["Cantidad Corregida"],
    "PRECIO_UNITARIO": ["Precio Unitario"],
    "PRECIO_UNITARIO_CON_DESCUENTO": ["Precio Unitario c/Descuento"],
    "TOTAL_UNITARIO": ["Total Unitario"],
    "CODIGO_CUENTA_COSTO": ["Código Cuenta Costo", "Codigo Cuenta Costo"],
    "DESCRIPCION_CUENTA_COSTO": ["Descripción Cuenta Costo", "Descripcion Cuenta Costo"],
    "CANTIDAD_AVANZADA": ["Cantidad Avanzada"],
    "TOTAL_AVANCE": ["Total Avance"],
    "SALDO": ["Saldo"],
    "MONTO_ASOCIADO_FACTURA": ["Monto Asociados a Factura", "Monto Asociado a Factura"],
    "FECHA_CREACION": ["Fecha Creación", "Fecha Creacion"],
}

SOURCE_MAP_EP = {
    "ID_EP": ["Nº Estado de Pago", "N° Estado de Pago", "Numero Estado de Pago", "Número Estado de Pago"],
    "ID_SC": ["Número Subcontrato", "Numero Subcontrato", "Nº Subcontrato", "N° Subcontrato"],
    "NOMBRE_EP": ["Nombre Estado de Pago"],
    "CENTRO_GESTION": ["Centro Gestión", "Centro de Gestion", "Centro de Gestión"],
    "RUT_SUBCONTRATISTA": ["RUT Subcontratista"],
    "NOMBRE_SUBCONTRATISTA": ["Nombre Subcontratista"],
    "EMITE_FACTURA": ["Emite Factura"],
    "MONEDA_EP": ["Moneda EP"],
    "MONTO_BRUTO_EP": ["Monto Bruto Estado de Pago"],
    "DEVOLUCION_ANTICIPO": ["Devolución Anticipo", "Devolucion Anticipo"],
    "RETENCIONES": ["Retenciones"],
    "REAJUSTES": ["Reajustes"],
    "DESCUENTOS_SIN_IVA": ["Descuentos sin IVA"],
    "DESCUENTOS_CON_IVA": ["Descuentos con IVA"],
    "TOTAL_PAGO_NETO": ["Total Pago Neto"],
    "IVA": ["IVA"],
    "MONTO_EP_FACTURADO": ["Montos Estados de Pago Facturados", "Monto Estado de Pago Facturado"],
    "N_FACTURA": ["N° Factura", "Nº Factura", "Numero Factura", "Número Factura"],
    "FECHA_EP": ["Fecha Estado de Pago"],
    "TIPO_DOCUMENTO": ["Tipo de Documento"],
    "ESTADO_DOCUMENTO": ["Estado Documento"],
}

SOURCE_MAP_DETALLE_EP = {
    "ID_EP": ["Número EP", "Numero EP", "Nº EP", "N° EP"],
    "ID_SC": ["Número SC", "Numero SC", "Nº SC", "N° SC"],
    "N_LINEA_SC": ["N° Linea SC", "Nº Linea SC", "N° Línea SC", "Nº Línea SC", "Linea SC", "Línea SC"],
    "CENTRO_GESTION": ["Centro Gestión", "Centro Gestion", "Centro de Gestión", "Centro de Gestion"],
    "CODIGO_CUENTA_COSTO": ["Código Cuenta Costo", "Codigo Cuenta Costo"],
    "DESCRIPCION_CUENTA_COSTO": ["Descripción Cuenta Costo", "Descripcion Cuenta Costo"],
    "MONEDA_SC": ["Moneda SC"],
    "TASA_CAMBIO_SC": ["Tasa Cambio SC", "Tasa de Cambio SC"],
    "NOMBRE_SC": ["Nombre SC", "Nombre Subcontrato"],
    "RUT_SUBCONTRATISTA": ["RUT Subcontratista"],
    "NOMBRE_SUBCONTRATISTA": ["Nombre Subcontratista"],
    "DESCRIPCION_LINEA": ["Descripción Linea", "Descripcion Linea", "Descripción Línea", "Descripcion Línea", "Descripción SC", "Descripcion SC"],
    "CANTIDAD_ORIGINAL": ["Cantidad Original"],
    "CANTIDAD_CORREGIDA": ["Cantidad Corregida"],
    "PRECIO_UNITARIO": ["Precio Unitario"],
    "PRECIO_TOTAL": ["Precio Total"],
    "TIPO_EP": ["Tipo EP"],
    "CANTIDAD_EP": ["Cantidad EP"],
    "MONTO_EP": ["Monto EP"],
    "ESTADO_DOCUMENTO": ["Estado Documento"],
}

SOURCE_MAP_GARANTIAS_SC = {
    "ID_SC": ["Numero Subcontrato", "Número Subcontrato", "Nº Subcontrato", "N° Subcontrato"],
    "NOMBRE_SC": ["Nombre Subcontrato"],
    "ESTADO_SC": ["Estado del Subcontrato", "Estado Subcontrato"],
    "CENTRO_GESTION": ["Centro Gestion", "Centro Gestión", "Centro de Gestion", "Centro de Gestión"],
    "RUT_SUBCONTRATISTA": ["Rut Subcontratista", "RUT Subcontratista"],
    "NOMBRE_SUBCONTRATISTA": ["Nombre Subcontratista"],
    "TIPO_GARANTIA": ["Tipo Garantia", "Tipo Garantía"],
    "MONEDA_GARANTIA": ["Monto Garantia", "Monto Garantía"],
    "MONTO_GARANTIA": ["Monto Garantia", "Monto Garantía"],
    "TIPO_DOCUMENTO_GARANTIA": ["Tipo Documento Garantia", "Tipo Documento Garantía"],
    "FECHA_VENCIMIENTO": ["Fecha Vencimiento"],
    "VENCIDA": ["Vencida"],
}

SOURCE_MAPS = {
    TABLE_SC: SOURCE_MAP_SC,
    TABLE_DETALLE_SC: SOURCE_MAP_DETALLE_SC,
    TABLE_EP: SOURCE_MAP_EP,
    TABLE_DETALLE_EP: SOURCE_MAP_DETALLE_EP,
    TABLE_GARANTIAS_SC: SOURCE_MAP_GARANTIAS_SC,
}


class SubcontractImportError(RuntimeError):
    pass


@dataclass
class DriveFile:
    id: str
    name: str
    mime_type: str
    modified_time: str
    created_time: str
    size: int


@dataclass
class ParsedReport:
    table: str
    file: DriveFile
    rows: list[dict[str, Any]]
    metadata: dict[str, str]
    source_headers: list[str]


# -----------------------------------------------------------------------------
# Utilidades generales
# -----------------------------------------------------------------------------
def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).replace("\xa0", " ").strip()


def _norm(value: Any) -> str:
    text = _text(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("º", "o").replace("°", "o")
    # Para encabezados de iConstruye ignoramos espacios, puntos y símbolos.
    # Esto hace equivalentes, por ejemplo, "Nº Subcontrato" y "NºSubcontrato".
    text = re.sub(r"[^A-Za-z0-9]+", "", text.upper())
    return text


def _norm_id(value: Any) -> str:
    text = _text(value)
    if re.fullmatch(r"\d+\.0", text):
        return text[:-2]
    return text


def _norm_line(value: Any) -> str:
    text = _norm_id(value)
    if not text:
        return ""
    try:
        number = float(text.replace(",", "."))
        if number.is_integer():
            return str(int(number))
    except Exception:
        pass
    return text


def _parse_number(value: Any) -> float | int | str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value

    text = _text(value)
    if not text:
        return ""

    text = text.replace("$", "").replace("UF", "").replace("US$", "")
    text = text.replace(" ", "")
    text = re.sub(r"[^0-9,\.\-+]", "", text)
    if not text or text in {"-", "+", ".", ","}:
        return ""

    # Formato chileno: 1.234.567,89
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    elif text.count(".") == 1:
        # Si hay exactamente 3 dígitos después del punto, normalmente es miles.
        left, right = text.split(".", 1)
        if len(right) == 3 and left not in {"0", "-0", "+0"}:
            text = left + right

    try:
        number = float(text)
        if number.is_integer():
            return int(number)
        return number
    except ValueError:
        return _text(value)


def _parse_currency(value: Any) -> str:
    text = _text(value).upper()
    if text.startswith("US$"):
        return "US$"
    if text.startswith("UF"):
        return "UF"
    if text.startswith("$"):
        return "$"
    return ""


def _key_number(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return format(value, ".12g")
    return _text(value)


def _parse_date(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()

    text = _text(value)
    if not text:
        return ""

    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%y", "%d/%m/%y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return text


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _col_letter(index_1based: int) -> str:
    result = ""
    n = index_1based
    while n:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def _get_by_alias(row: dict[str, Any], aliases: Iterable[str]) -> Any:
    for alias in aliases:
        key = _norm(alias)
        if key in row:
            return row[key]
    return ""


def _is_sc(value: Any) -> bool:
    return bool(re.fullmatch(r"\d+-\d+", _norm_id(value)))


def _is_ep(value: Any) -> bool:
    return bool(re.fullmatch(r"\d+-\d+-\d+", _norm_id(value)))


# -----------------------------------------------------------------------------
# Parser HTML de iConstruye (algunos .xls son HTML real)
# -----------------------------------------------------------------------------
class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell).replace("\xa0", " ").strip())
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None


def _decode_html(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "iso-8859-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("iso-8859-1", errors="replace")


def _parse_html_tables(data: bytes) -> list[list[list[Any]]]:
    parser = _TableParser()
    parser.feed(_decode_html(data))
    return parser.tables


# -----------------------------------------------------------------------------
# Lectores Excel
# -----------------------------------------------------------------------------
def _parse_xlsx_tables(data: bytes) -> list[list[list[Any]]]:
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    tables: list[list[list[Any]]] = []
    for ws in wb.worksheets:
        rows = [list(row) for row in ws.iter_rows(values_only=True)]
        tables.append(rows)
    return tables


def _parse_tsv_tables(data: bytes) -> list[list[list[Any]]]:
    text = None
    for encoding in ("utf-16", "utf-16-le", "utf-8-sig", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise SubcontractImportError("No se pudo decodificar el reporte tabulado.")
    rows = [list(row) for row in csv.reader(io.StringIO(text), delimiter="\t")]
    return [rows]


def _parse_xls_tables(data: bytes) -> list[list[list[Any]]]:
    if xlrd is None:
        raise SubcontractImportError("Falta dependencia xlrd para leer .xls binario.")
    book = xlrd.open_workbook(file_contents=data, formatting_info=False)
    tables: list[list[list[Any]]] = []
    for sheet in book.sheets():
        rows: list[list[Any]] = []
        for r in range(sheet.nrows):
            current: list[Any] = []
            for c in range(sheet.ncols):
                cell = sheet.cell(r, c)
                value: Any = cell.value
                if cell.ctype == xlrd.XL_CELL_DATE:
                    try:
                        parts = xlrd.xldate_as_datetime(value, book.datemode)
                        value = parts
                    except Exception:
                        pass
                current.append(value)
            rows.append(current)
        tables.append(rows)
    return tables


def _looks_like_tabular_text(data: bytes) -> bool:
    """Detecta exportaciones iConstruye que son texto tabulado aunque terminen en .xls."""
    sample = data[:8192]
    if not sample:
        return False

    # UTF-16 LE / BE con o sin BOM. En UTF-16 los tabs aparecen como 09 00 o 00 09.
    utf16_tab = b"\t\x00" in sample or b"\x00\t" in sample
    has_many_nuls = sample.count(b"\x00") >= max(4, len(sample) // 10)
    if utf16_tab and (data.startswith((b"\xff\xfe", b"\xfe\xff")) or has_many_nuls):
        return True

    # También toleramos TSV UTF-8/ANSI si contiene varias columnas y saltos de línea.
    if b"\t" in sample and (b"\n" in sample or b"\r" in sample):
        return True
    return False


def _detect_container(data: bytes, file_name: str) -> str:
    head = data[:256].lstrip()
    if data.startswith(b"PK\x03\x04"):
        return "xlsx"
    if data.startswith(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"):
        return "xls"
    if head.startswith(b"<") or b"<table" in head.lower() or b"<style" in head.lower():
        return "html"

    # IMPORTANTE: iConstruye entrega el reporte de garantías como TSV UTF-16
    # con extensión .xls. Debe detectarse por contenido ANTES de confiar en la extensión.
    if _looks_like_tabular_text(data):
        return "tsv"

    lower = file_name.lower()
    if lower.endswith(".xlsx"):
        return "xlsx"
    if lower.endswith(".xls"):
        return "xls"
    raise SubcontractImportError(f"Formato no reconocido: {file_name}")


def _read_tables(data: bytes, file_name: str) -> tuple[str, list[list[list[Any]]]]:
    container = _detect_container(data, file_name)
    if container == "xlsx":
        return container, _parse_xlsx_tables(data)
    if container == "xls":
        return container, _parse_xls_tables(data)
    if container == "tsv":
        return container, _parse_tsv_tables(data)
    return container, _parse_html_tables(data)


# -----------------------------------------------------------------------------
# Identificación del reporte y cabecera
# -----------------------------------------------------------------------------
def _classify_header(row: list[Any]) -> tuple[str | None, int]:
    headers = {_norm(v) for v in row if _text(v)}

    signatures: list[tuple[str, set[str]]] = [
        (TABLE_SC, {_norm("Nº Subcontrato"), _norm("Monto Total Neto"), _norm("Moneda Subcontrato")} ),
        (TABLE_DETALLE_SC, {_norm("Nº Subcontrato"), _norm("Código del Servicio o Actividad"), _norm("Cantidad Original"), _norm("N° Linea")} ),
        (TABLE_EP, {_norm("Nº Estado de Pago"), _norm("Número Subcontrato"), _norm("Monto Bruto Estado de Pago")} ),
        (TABLE_DETALLE_EP, {_norm("Número EP"), _norm("Número SC"), _norm("Cantidad EP"), _norm("Monto EP")} ),
        (TABLE_GARANTIAS_SC, {_norm("Numero Subcontrato"), _norm("Tipo Garantia"), _norm("Monto Garantia"), _norm("Fecha Vencimiento")} ),
    ]

    best_table: str | None = None
    best_score = 0
    for table, signature in signatures:
        score = len(headers.intersection(signature))
        if score > best_score:
            best_table = table
            best_score = score
    return best_table, best_score


def _extract_metadata(rows_before_header: list[list[Any]]) -> dict[str, str]:
    flat = [_text(cell) for row in rows_before_header for cell in row]
    result: dict[str, str] = {}

    for i, value in enumerate(flat):
        key = _norm(value)
        if key in {_norm("Centro de Gestion:"), _norm("Centro de Gestión:")}:
            for candidate in flat[i + 1 : i + 5]:
                if candidate and ":" not in candidate:
                    result["CENTRO_GESTION_REPORTE"] = candidate
                    break
        elif key == _norm("Fecha Inicio:"):
            for candidate in flat[i + 1 : i + 5]:
                if re.fullmatch(r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", candidate):
                    result["FECHA_DESDE_REPORTE"] = _parse_date(candidate)
                    break
        elif key == _norm("Fecha Final:"):
            for candidate in flat[i + 1 : i + 5]:
                if re.fullmatch(r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", candidate):
                    result["FECHA_HASTA_REPORTE"] = _parse_date(candidate)
                    break
        elif key == _norm("Fecha Vencimiento Garantia"):
            dates = [
                _parse_date(candidate)
                for candidate in flat[i + 1 : i + 6]
                if re.fullmatch(r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", candidate)
            ]
            if dates:
                result["FECHA_DESDE_REPORTE"] = dates[0]
            if len(dates) > 1:
                result["FECHA_HASTA_REPORTE"] = dates[1]
    return result


def _find_report(tables: list[list[list[Any]]]) -> tuple[str, list[str], list[list[Any]], dict[str, str]]:
    candidates: list[tuple[int, str, int, list[list[Any]]]] = []
    for table_rows in tables:
        for idx, row in enumerate(table_rows):
            report_type, score = _classify_header(row)
            if report_type and score >= 3:
                candidates.append((score, report_type, idx, table_rows))

    if not candidates:
        raise SubcontractImportError("No se pudo identificar el tipo de reporte por sus encabezados.")

    candidates.sort(key=lambda item: item[0], reverse=True)
    _, report_type, header_idx, table_rows = candidates[0]
    headers = [_text(v) for v in table_rows[header_idx]]
    metadata: dict[str, str] = {}
    # iConstruye a veces deja los filtros/fechas en una tabla HTML separada
    # de la tabla de datos. Revisamos las primeras filas de todas las tablas.
    for rows_any in tables:
        metadata.update(_extract_metadata(rows_any[:12]))
    metadata.update(_extract_metadata(table_rows[:header_idx]))
    data_rows = table_rows[header_idx + 1 :]
    return report_type, headers, data_rows, metadata


def _source_rows(headers: list[str], rows: list[list[Any]]) -> list[dict[str, Any]]:
    normalized_headers = [_norm(h) for h in headers]
    result: list[dict[str, Any]] = []
    for values in rows:
        row: dict[str, Any] = {}
        nonempty = False
        for idx, key in enumerate(normalized_headers):
            if not key:
                continue
            value = values[idx] if idx < len(values) else ""
            if _text(value):
                nonempty = True
            row[key] = value
        if nonempty:
            result.append(row)
    return result


# -----------------------------------------------------------------------------
# Normalización hacia las tablas físicas de AppSheet/Sheets
# -----------------------------------------------------------------------------
def _transform_report(
    table: str,
    source_headers: list[str],
    source_rows: list[list[Any]],
) -> list[dict[str, Any]]:
    mapping = SOURCE_MAPS[table]
    rows = _source_rows(source_headers, source_rows)
    transformed: list[dict[str, Any]] = []

    for src in rows:
        dst: dict[str, Any] = {}
        for dest, aliases in mapping.items():
            dst[dest] = _get_by_alias(src, aliases)

        if table == TABLE_SC:
            dst["ID_SC"] = _norm_id(dst.get("ID_SC"))
            if not _is_sc(dst["ID_SC"]):
                continue

        elif table == TABLE_DETALLE_SC:
            dst["ID_SC"] = _norm_id(dst.get("ID_SC"))
            dst["N_LINEA_SC"] = _norm_line(dst.get("N_LINEA_SC"))
            if not _is_sc(dst["ID_SC"]) or not dst["N_LINEA_SC"]:
                continue
            dst["ID_SC_DETALLE"] = f'{dst["ID_SC"]}|{dst["N_LINEA_SC"]}'

        elif table == TABLE_EP:
            dst["ID_EP"] = _norm_id(dst.get("ID_EP"))
            dst["ID_SC"] = _norm_id(dst.get("ID_SC"))
            if not _is_ep(dst["ID_EP"]) or not _is_sc(dst["ID_SC"]):
                continue

        elif table == TABLE_DETALLE_EP:
            dst["ID_EP"] = _norm_id(dst.get("ID_EP"))
            dst["ID_SC"] = _norm_id(dst.get("ID_SC"))
            dst["N_LINEA_SC"] = _norm_line(dst.get("N_LINEA_SC"))
            if not _is_ep(dst["ID_EP"]) or not _is_sc(dst["ID_SC"]) or not dst["N_LINEA_SC"]:
                continue
            dst["ID_SC_DETALLE"] = f'{dst["ID_SC"]}|{dst["N_LINEA_SC"]}'
            dst["ID_EP_DETALLE"] = f'{dst["ID_EP"]}|{dst["N_LINEA_SC"]}'

        elif table == TABLE_GARANTIAS_SC:
            dst["ID_SC"] = _norm_id(dst.get("ID_SC"))
            if not _is_sc(dst["ID_SC"]):
                continue
            raw_amount = dst.get("MONTO_GARANTIA")
            dst["MONEDA_GARANTIA"] = _parse_currency(raw_amount)
            dst["MONTO_GARANTIA"] = _parse_number(raw_amount)
            dst["FECHA_VENCIMIENTO"] = _parse_date(dst.get("FECHA_VENCIMIENTO"))
            dst["ID_GARANTIA_SC"] = "|".join([
                dst["ID_SC"],
                _text(dst.get("TIPO_GARANTIA")),
                dst["FECHA_VENCIMIENTO"],
                _key_number(dst["MONTO_GARANTIA"]),
            ])

        for column in NUMBER_COLUMNS[table]:
            if column in dst:
                dst[column] = _parse_number(dst[column])
        for column in DATE_COLUMNS[table]:
            if column in dst:
                dst[column] = _parse_date(dst[column])

        # Claves y códigos deben mantenerse como texto.
        for column in ("ID_SC", "ID_SC_DETALLE", "ID_EP", "ID_EP_DETALLE", "ID_GARANTIA_SC", "N_LINEA_SC",
                       "RUT_SUBCONTRATISTA", "CODIGO_SERVICIO", "CODIGO_CUENTA_COSTO", "N_FACTURA"):
            if column in dst:
                dst[column] = _norm_id(dst[column])

        # Limpiar espacios de campos de texto sin modificar números ni fechas.
        for column in EXPECTED_HEADERS[table]:
            if column in dst and column not in NUMBER_COLUMNS[table] and column not in DATE_COLUMNS[table]:
                dst[column] = _text(dst[column])

        # Garantizar que sólo salgan columnas físicas esperadas y en forma serializable.
        final_row = {column: dst.get(column, "") for column in EXPECTED_HEADERS[table]}
        transformed.append(final_row)

    if not transformed:
        raise SubcontractImportError(f"{table}: no se encontraron filas de datos válidas.")
    return transformed


# -----------------------------------------------------------------------------
# Google OAuth / Drive / Sheets
# -----------------------------------------------------------------------------
def _credentials():
    if GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET and GOOGLE_OAUTH_REFRESH_TOKEN:
        creds = Credentials(
            token=None,
            refresh_token=GOOGLE_OAUTH_REFRESH_TOKEN,
            token_uri=GOOGLE_OAUTH_TOKEN_URI,
            client_id=GOOGLE_OAUTH_CLIENT_ID,
            client_secret=GOOGLE_OAUTH_CLIENT_SECRET,
            scopes=GOOGLE_SCOPES,
        )
        creds.refresh(GoogleAuthRequest())
        return creds

    creds, _ = google.auth.default(scopes=GOOGLE_SCOPES)
    return creds


def _drive_service():
    return build("drive", "v3", credentials=_credentials(), cache_discovery=False)


def _sheets_service():
    return build("sheets", "v4", credentials=_credentials(), cache_discovery=False)


def _list_folder_files() -> list[DriveFile]:
    service = _drive_service()
    page_token: str | None = None
    files: list[DriveFile] = []
    query = f"'{FOLDER_ID}' in parents and trashed = false"

    while True:
        response = (
            service.files()
            .list(
                q=query,
                spaces="drive",
                fields="nextPageToken,files(id,name,mimeType,modifiedTime,createdTime,size)",
                pageSize=1000,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        for item in response.get("files", []):
            if item.get("mimeType") == "application/vnd.google-apps.folder":
                continue
            size = int(item.get("size") or 0)
            files.append(
                DriveFile(
                    id=str(item.get("id") or ""),
                    name=str(item.get("name") or ""),
                    mime_type=str(item.get("mimeType") or ""),
                    modified_time=str(item.get("modifiedTime") or ""),
                    created_time=str(item.get("createdTime") or ""),
                    size=size,
                )
            )
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return files


def _download_drive_file(file: DriveFile) -> bytes:
    if file.size and file.size > MAX_FILE_BYTES:
        raise SubcontractImportError(
            f"{file.name}: archivo excede máximo permitido ({file.size} bytes > {MAX_FILE_BYTES})."
        )
    service = _drive_service()
    data = service.files().get_media(fileId=file.id, supportsAllDrives=True).execute()
    if not isinstance(data, (bytes, bytearray)):
        raise SubcontractImportError(f"{file.name}: Drive no devolvió bytes descargables.")
    return bytes(data)


# -----------------------------------------------------------------------------
# Selección del lote más reciente
# -----------------------------------------------------------------------------
def _parse_drive_file(file: DriveFile) -> ParsedReport:
    data = _download_drive_file(file)
    container, tables = _read_tables(data, file.name)
    table, headers, rows, metadata = _find_report(tables)
    transformed = _transform_report(table, headers, rows)
    logger.info(
        "subcontratos archivo_clasificado nombre=%s id=%s container=%s reporte=%s filas=%s bytes=%s",
        file.name,
        file.id,
        container,
        table,
        len(transformed),
        len(data),
    )
    return ParsedReport(
        table=table,
        file=file,
        rows=transformed,
        metadata=metadata,
        source_headers=headers,
    )


def _select_latest_reports() -> tuple[dict[str, ParsedReport], list[str]]:
    files = _list_folder_files()
    if not files:
        raise SubcontractImportError(
            "La carpeta Archivos_Subcontrato_bellet_iconstruye está vacía."
        )

    parsed_by_table: dict[str, list[ParsedReport]] = {table: [] for table in TABLES}
    parse_errors: list[str] = []

    logger.info(
        "subcontratos archivos_en_carpeta total=%s archivos=%s",
        len(files),
        [f"{f.name} ({f.id}, {f.size} bytes)" for f in files],
    )

    for file in files:
        lower = file.name.lower()
        if not (lower.endswith(".xls") or lower.endswith(".xlsx")):
            continue
        try:
            report = _parse_drive_file(file)
            parsed_by_table[report.table].append(report)
        except Exception as exc:
            error_text = f"{file.name}: {exc}"
            parse_errors.append(error_text)
            logger.warning(
                "subcontratos archivo_ignorado nombre=%s id=%s error=%s",
                file.name,
                file.id,
                exc,
            )

    selected: dict[str, ParsedReport] = {}
    warnings: list[str] = []
    for table in TABLES:
        candidates = parsed_by_table[table]
        if not candidates:
            detail = "; ".join(parse_errors[:8])
            visibles = ", ".join(file.name for file in files[:20])
            raise SubcontractImportError(
                f"No se encontró un archivo válido para {table}."
                + (f" Archivos visibles: {visibles}." if visibles else "")
                + (f" Errores de lectura: {detail}" if detail else "")
            )
        candidates.sort(
            key=lambda r: _datetime(r.file.modified_time) if r.file.modified_time else datetime.min.replace(tzinfo=ZoneInfo("UTC")),
            reverse=True,
        )
        selected[table] = candidates[0]
        if len(candidates) > 1:
            warnings.append(
                f"{table}: se eligió {candidates[0].file.name}; se ignoraron {len(candidates)-1} versión(es) anterior(es)."
            )

    if MAX_BATCH_SPAN_MINUTES > 0:
        times = [
            _datetime(report.file.modified_time)
            for report in selected.values()
            if report.file.modified_time
        ]
        if len(times) == len(TABLES):
            span_minutes = (max(times) - min(times)).total_seconds() / 60.0
            if span_minutes > MAX_BATCH_SPAN_MINUTES:
                raise SubcontractImportError(
                    f"Los {len(TABLES)} reportes seleccionados no parecen pertenecer al mismo lote: "
                    f"sus modifiedTime abarcan {span_minutes:.1f} minutos "
                    f"(máximo {MAX_BATCH_SPAN_MINUTES})."
                )

    if parse_errors:
        warnings.append(
            f"Se ignoraron {len(parse_errors)} archivo(s) que no pudieron clasificarse/leer."
        )
    return selected, warnings


# -----------------------------------------------------------------------------
# Validaciones de integridad
# -----------------------------------------------------------------------------
def _duplicates(rows: list[dict[str, Any]], key: str) -> list[str]:
    seen: set[str] = set()
    dup: list[str] = []
    for row in rows:
        value = _text(row.get(key))
        if value in seen:
            dup.append(value)
        seen.add(value)
    return sorted(set(dup))


def _validate_reports(reports: dict[str, ParsedReport]) -> list[str]:
    errors: list[str] = []
    sc_rows = reports[TABLE_SC].rows
    det_sc_rows = reports[TABLE_DETALLE_SC].rows
    ep_rows = reports[TABLE_EP].rows
    det_ep_rows = reports[TABLE_DETALLE_EP].rows
    garantia_rows = reports[TABLE_GARANTIAS_SC].rows

    for table, rows, key in (
        (TABLE_SC, sc_rows, "ID_SC"),
        (TABLE_DETALLE_SC, det_sc_rows, "ID_SC_DETALLE"),
        (TABLE_EP, ep_rows, "ID_EP"),
        (TABLE_DETALLE_EP, det_ep_rows, "ID_EP_DETALLE"),
        (TABLE_GARANTIAS_SC, garantia_rows, "ID_GARANTIA_SC"),
    ):
        dup = _duplicates(rows, key)
        if dup:
            errors.append(f"{table}: claves duplicadas en {key}: {', '.join(dup[:20])}")

    sc_by_id = {_text(row["ID_SC"]): row for row in sc_rows}
    det_sc_by_id = {_text(row["ID_SC_DETALLE"]): row for row in det_sc_rows}
    ep_by_id = {_text(row["ID_EP"]): row for row in ep_rows}

    missing_det_sc = sorted({
        _text(row["ID_SC"]) for row in det_sc_rows if _text(row["ID_SC"]) not in sc_by_id
    })
    if missing_det_sc:
        errors.append("DETALLE_SC referencia SC inexistentes: " + ", ".join(missing_det_sc[:30]))

    missing_ep_sc = sorted({
        _text(row["ID_SC"]) for row in ep_rows if _text(row["ID_SC"]) not in sc_by_id
    })
    if missing_ep_sc:
        errors.append("EP referencia SC inexistentes: " + ", ".join(missing_ep_sc[:30]))

    missing_active_guarantee_sc = sorted({
        _text(row["ID_SC"])
        for row in garantia_rows
        if _text(row.get("ESTADO_SC")).upper() != "CANCELADO"
        and _text(row["ID_SC"]) not in sc_by_id
    })
    if missing_active_guarantee_sc:
        errors.append(
            "GARANTIAS referencia SC activos inexistentes: "
            + ", ".join(missing_active_guarantee_sc[:30])
        )

    missing_det_ep = sorted({
        _text(row["ID_EP"]) for row in det_ep_rows if _text(row["ID_EP"]) not in ep_by_id
    })
    if missing_det_ep:
        errors.append("DETALLE_EP referencia EP inexistentes: " + ", ".join(missing_det_ep[:30]))

    missing_line = sorted({
        _text(row["ID_SC_DETALLE"])
        for row in det_ep_rows
        if _text(row["ID_SC_DETALLE"]) not in det_sc_by_id
    })
    if missing_line:
        errors.append("DETALLE_EP referencia líneas SC inexistentes: " + ", ".join(missing_line[:30]))

    mismatched_ep_sc: list[str] = []
    for row in det_ep_rows:
        ep = ep_by_id.get(_text(row["ID_EP"]))
        if ep and _text(ep.get("ID_SC")) != _text(row.get("ID_SC")):
            mismatched_ep_sc.append(
                f'{row.get("ID_EP_DETALLE")}: detalle={row.get("ID_SC")}, EP={ep.get("ID_SC")}'
            )
    if mismatched_ep_sc:
        errors.append("DETALLE_EP con SC distinto al EP: " + "; ".join(mismatched_ep_sc[:20]))

    # Centro de gestión: revisar sólo valores informados.
    for table, report in reports.items():
        bad_centers = sorted({
            _text(row.get("CENTRO_GESTION"))
            for row in report.rows
            if _text(row.get("CENTRO_GESTION"))
            and _text(row.get("CENTRO_GESTION")) != EXPECTED_CENTRO_GESTION
        })
        if bad_centers:
            errors.append(
                f"{table}: Centro Gestión distinto de {EXPECTED_CENTRO_GESTION!r}: "
                + ", ".join(bad_centers[:10])
            )

    # RUT consistente por SC entre las cuatro tablas.
    rut_by_sc: dict[str, set[str]] = {}
    for report in reports.values():
        for row in report.rows:
            sc = _text(row.get("ID_SC"))
            rut = _text(row.get("RUT_SUBCONTRATISTA"))
            if sc and rut:
                rut_by_sc.setdefault(sc, set()).add(rut)
    inconsistent_rut = [f"{sc}: {sorted(ruts)}" for sc, ruts in rut_by_sc.items() if len(ruts) > 1]
    if inconsistent_rut:
        errors.append("RUT inconsistente para el mismo SC: " + "; ".join(inconsistent_rut[:20]))

    if errors:
        raise SubcontractImportError(" | ".join(errors))
    return errors


# -----------------------------------------------------------------------------
# Verificación de esquema y publicación con rollback
# -----------------------------------------------------------------------------
def _read_headers(sheets, table: str) -> list[str]:
    last_col = _col_letter(len(EXPECTED_HEADERS[table]))
    response = (
        sheets.spreadsheets()
        .values()
        .get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{table}'!A1:{last_col}1",
            valueRenderOption="FORMATTED_VALUE",
        )
        .execute()
    )
    values = response.get("values", [[]])
    return [_text(v) for v in (values[0] if values else [])]


def _verify_destination_schema(sheets) -> None:
    for table in TABLES:
        actual = _read_headers(sheets, table)
        expected = EXPECTED_HEADERS[table]
        if actual != expected:
            raise SubcontractImportError(
                f"La estructura de {table} no coincide con la programada. "
                f"Esperado={expected}; Actual={actual}"
            )


def _read_existing_rows(sheets, table: str) -> list[list[Any]]:
    last_col = _col_letter(len(EXPECTED_HEADERS[table]))
    response = (
        sheets.spreadsheets()
        .values()
        .get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{table}'!A2:{last_col}",
            valueRenderOption="UNFORMATTED_VALUE",
        )
        .execute()
    )
    return response.get("values", [])


def _rows_matrix(table: str, rows: list[dict[str, Any]]) -> list[list[Any]]:
    headers = EXPECTED_HEADERS[table]
    return [[row.get(column, "") for column in headers] for row in rows]


def _clear_tables(sheets) -> None:
    ranges = []
    for table in TABLES:
        last_col = _col_letter(len(EXPECTED_HEADERS[table]))
        ranges.append(f"'{table}'!A2:{last_col}")
    (
        sheets.spreadsheets()
        .values()
        .batchClear(
            spreadsheetId=SPREADSHEET_ID,
            body={"ranges": ranges},
        )
        .execute()
    )


def _write_matrices(sheets, matrices: dict[str, list[list[Any]]]) -> None:
    data = []
    for table in TABLES:
        matrix = matrices.get(table) or []
        if not matrix:
            continue
        last_col = _col_letter(len(EXPECTED_HEADERS[table]))
        last_row = len(matrix) + 1
        data.append(
            {
                "range": f"'{table}'!A2:{last_col}{last_row}",
                "majorDimension": "ROWS",
                "values": matrix,
            }
        )
    if not data:
        return
    (
        sheets.spreadsheets()
        .values()
        .batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={
                "valueInputOption": "RAW",
                "data": data,
            },
        )
        .execute()
    )


def _publish(reports: dict[str, ParsedReport]) -> None:
    sheets = _sheets_service()
    _verify_destination_schema(sheets)

    backup = {table: _read_existing_rows(sheets, table) for table in TABLES}
    new_matrices = {table: _rows_matrix(table, reports[table].rows) for table in TABLES}

    try:
        _clear_tables(sheets)
        _write_matrices(sheets, new_matrices)
    except Exception as publish_error:
        logger.exception("subcontratos publish_failed; intentando rollback")
        try:
            _clear_tables(sheets)
            _write_matrices(sheets, backup)
        except Exception:
            logger.exception("subcontratos rollback_failed")
            raise SubcontractImportError(
                f"Falló la publicación ({publish_error}) y también falló el rollback. "
                "Revisar inmediatamente las cinco tablas."
            ) from publish_error
        raise SubcontractImportError(
            f"Falló la publicación y se restauró el snapshot anterior: {publish_error}"
        ) from publish_error


# -----------------------------------------------------------------------------
# API de servicio
# -----------------------------------------------------------------------------
def _summary(reports: dict[str, ParsedReport], warnings: list[str], published: bool) -> dict[str, Any]:
    files = {}
    for table, report in reports.items():
        files[table] = {
            "drive_file_id": report.file.id,
            "nombre_archivo": report.file.name,
            "modified_time": report.file.modified_time,
            "filas": len(report.rows),
            "metadata_reporte": report.metadata,
        }

    return {
        "ok": True,
        "version": VERSION,
        "published": published,
        "folder_id": FOLDER_ID,
        "spreadsheet_id": SPREADSHEET_ID,
        "counts": {
            "sc": len(reports[TABLE_SC].rows),
            "detalle_sc": len(reports[TABLE_DETALLE_SC].rows),
            "ep": len(reports[TABLE_EP].rows),
            "detalle_ep": len(reports[TABLE_DETALLE_EP].rows),
            "garantias_sc": len(reports[TABLE_GARANTIAS_SC].rows),
        },
        "files": files,
        "warnings": warnings,
        "processed_at": datetime.now(ZoneInfo("America/Santiago")).isoformat(),
    }


def validate_subcontract_import() -> dict[str, Any]:
    reports, warnings = _select_latest_reports()
    _validate_reports(reports)

    # También valida que las columnas físicas sigan exactamente como se definieron.
    sheets = _sheets_service()
    _verify_destination_schema(sheets)

    return _summary(reports, warnings, published=False)


def process_subcontract_import() -> dict[str, Any]:
    reports, warnings = _select_latest_reports()
    _validate_reports(reports)
    _publish(reports)
    return _summary(reports, warnings, published=True)
