from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import CSS, HTML

from .analytics import build_floor_map
from .appsheet_client import AppSheetClient
from .drive_client import DriveClient
from .formatters import fmt_date, fmt_floor, parse_appsheet_date
from .report_writer_client import ReportWriterClient, ReportWriterResult


BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

TABLE_DAILY = "INFORME_FOTOGRAFICO_DIARIO"
TABLE_FOTOS = "REGISTRO_AVANCE_SEMANAL"
TABLE_PISOS = "PISOS"
TABLE_OBRA = "OBRA"

env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {
        "true", "t", "yes", "y", "si", "sí", "1"
    }


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _select_obra(
    daily: dict[str, Any],
    obra_rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not obra_rows:
        return None

    target = _safe_text(daily.get("ID_OBRA"))

    if target:
        for row in obra_rows:
            if _safe_text(row.get("ID_OBRA")) == target:
                return row

    return obra_rows[0]


def _select_photos_for_date(
    rows: list[dict[str, Any]],
    target_date,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []

    if target_date is None:
        return selected

    for row in rows:
        if not _safe_text(row.get("IMAGEN")):
            continue

        photo_date = parse_appsheet_date(
            row.get("FECHA")
        )

        if photo_date != target_date:
            continue

        selected.append(row)

    selected.sort(
        key=lambda row: (
            _safe_text(row.get("FECHA")),
            _safe_text(row.get("ID_REGISTRO_FOTOGRAFICO")),
        )
    )

    return selected


def _load_photo_media(
    drive: DriveClient,
    rows: list[dict[str, Any]],
    floor_map: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    photos: list[dict[str, Any]] = []
    warnings: list[str] = []

    for row in rows:
        image_path = _safe_text(row.get("IMAGEN"))

        try:
            image_uri = drive.data_uri_photo(
                image_path
            )
        except Exception as exc:
            warnings.append(
                f"Foto "
                f"{row.get('ID_REGISTRO_FOTOGRAFICO', '')} "
                f"no incorporada: {exc}"
            )
            continue

        floor_ref = _safe_text(
            row.get("PISO")
        )

        floor_value = floor_map.get(
            floor_ref
        )

        if floor_value in (None, ""):
            floor_value = floor_ref or "—"

        photos.append(
            {
                "id": row.get(
                    "ID_REGISTRO_FOTOGRAFICO"
                ),
                "fecha": row.get("FECHA"),
                "piso": floor_value,
                "comentario": (
                    row.get("COMENTARIO")
                    or "Sin descripción."
                ),
                "imagen": image_uri,
            }
        )

    return photos, warnings


def _chunks(
    rows: list[dict[str, Any]],
    size: int,
) -> list[list[dict[str, Any]]]:
    if not rows:
        return [[]]

    return [
        rows[i:i + size]
        for i in range(0, len(rows), size)
    ]


def load_daily_report_data(
    id_informe_diario: str,
) -> dict[str, Any]:
    appsheet = AppSheetClient()
    drive = DriveClient()

    daily = appsheet.find_by_key(
        TABLE_DAILY,
        "ID_INFORME_DIARIO",
        id_informe_diario,
    )

    # Apagar el gatillo apenas Cloud Run toma el trabajo.
    try:
        appsheet.edit_row(
            TABLE_DAILY,
            {
                "ID_INFORME_DIARIO": id_informe_diario,
                "GENERAR_INFORME": False,
            },
        )
    except Exception:
        pass

    target_date = parse_appsheet_date(
        daily.get("FECHA_INFORME")
    )

    obra_rows = appsheet.find_rows(
        TABLE_OBRA
    )
    obra = _select_obra(
        daily,
        obra_rows,
    )

    floor_rows = appsheet.find_rows(
        TABLE_PISOS
    )
    floor_map = build_floor_map(
        floor_rows
    )

    photo_rows = appsheet.find_rows(
        TABLE_FOTOS
    )

    selected = _select_photos_for_date(
        photo_rows,
        target_date,
    )

    photos, warnings = _load_photo_media(
        drive=drive,
        rows=selected,
        floor_map=floor_map,
    )

    return {
        "daily": daily,
        "obra": obra or {},
        "date": target_date,
        "photos": photos,
        "photo_pages": _chunks(photos, 6),
        "warnings": warnings,
        "source_count": len(selected),
    }


def build_daily_context(
    bundle: dict[str, Any],
) -> dict[str, Any]:
    logo_file = STATIC_DIR / "logo_altius.png"

    return {
        "r": bundle["daily"],
        "obra": bundle["obra"],
        "fecha": bundle["date"],
        "fotos": bundle["photos"],
        "photo_pages": bundle["photo_pages"],
        "warnings": bundle["warnings"],
        "logo_path": (
            logo_file.resolve().as_uri()
            if logo_file.exists()
            else None
        ),
        "f": {
            "date": fmt_date,
            "floor": fmt_floor,
        },
    }


def render_daily_pdf_bytes(
    id_informe_diario: str,
    bundle: dict[str, Any],
) -> bytes:
    template = env.get_template(
        "reporte_fotografico_diario.html"
    )

    html = template.render(
        **build_daily_context(bundle)
    )

    css_file = STATIC_DIR / "daily_report.css"

    stylesheets = (
        [CSS(filename=str(css_file))]
        if css_file.exists()
        else []
    )

    return HTML(
        string=html,
        base_url=str(BASE_DIR),
    ).write_pdf(
        stylesheets=stylesheets
    )


def generate_daily_preview(
    id_informe_diario: str,
) -> tuple[bytes, dict[str, Any]]:
    bundle = load_daily_report_data(
        id_informe_diario
    )

    pdf_bytes = render_daily_pdf_bytes(
        id_informe_diario,
        bundle,
    )

    return pdf_bytes, {
        "id_informe_diario": id_informe_diario,
        "fecha": fmt_date(bundle["date"]),
        "fotos_incluidas": len(bundle["photos"]),
        "fotos_encontradas": bundle["source_count"],
        "warnings": bundle["warnings"],
    }


def generate_daily_and_publish(
    id_informe_diario: str,
) -> dict[str, Any]:
    appsheet = AppSheetClient()
    writer = ReportWriterClient()

    bundle = load_daily_report_data(
        id_informe_diario
    )

    pdf_bytes = render_daily_pdf_bytes(
        id_informe_diario,
        bundle,
    )

    safe_id = "".join(
        c
        for c in str(id_informe_diario)
        if c.isalnum() or c in ("-", "_")
    ) or "reporte"

    target_date = bundle["date"]

    if target_date:
        date_token = target_date.strftime(
            "%Y-%m-%d"
        )
    else:
        date_token = "sin-fecha"

    filename = (
        f"Reporte_Fotografico_"
        f"{date_token}_"
        f"{safe_id}.pdf"
    )

    uploaded: ReportWriterResult = (
        writer.upload_or_replace_pdf(
            pdf_bytes,
            filename,
            folder_key="daily_photos",
        )
    )

    now_chile = datetime.now(
        ZoneInfo("America/Santiago")
    )

    # AppSheet API opera con Locale en-US.
    emission_us = now_chile.strftime(
        "%m/%d/%Y %H:%M:%S"
    )

    appsheet.edit_row(
        TABLE_DAILY,
        {
            "ID_INFORME_DIARIO": id_informe_diario,
            "ARCHIVO_INFORME": uploaded.relative_path,
            "FECHA_EMISION": emission_us,
            "ESTADO": "EMITIDO",
            "GENERAR_INFORME": False,
        },
    )

    return {
        "ok": True,
        "id_informe_diario": id_informe_diario,
        "fecha_informe": fmt_date(bundle["date"]),
        "archivo_informe": uploaded.relative_path,
        "drive_file_id": uploaded.file_id,
        "drive_web_url": uploaded.web_view_link,
        "fotos_encontradas": bundle["source_count"],
        "fotos_incluidas": len(bundle["photos"]),
        "warnings": bundle["warnings"],
    }
