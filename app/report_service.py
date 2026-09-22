\
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML, CSS

from .appsheet_client import AppSheetClient, AppSheetError
from .charts import programa_tres_semanas
from .drive_client import DriveClient, DriveError, DriveUploadResult
from .formatters import (
    first_value,
    fmt_clp,
    fmt_date,
    fmt_m3,
    fmt_number,
    fmt_percent,
    fmt_uf,
)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

TABLE_INFORME = "INFORME"
TABLE_OBRA = "OBRA"
TABLE_VISTA = "VISTA_ALZAPRIMADO"
TABLE_FOTOS = "REGISTRO_AVANCE_SEMANAL"

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


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _choose_vista(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    usable = [r for r in rows if str(r.get("SVG_URI", "")).strip()]
    if not usable:
        return None

    usable.sort(
        key=lambda r: _safe_int(r.get("_RowNumber"), 0),
        reverse=True,
    )
    return usable[0]


def _selected_photos(
    rows: list[dict[str, Any]],
    week_id: Any,
) -> list[dict[str, Any]]:
    result = []

    for row in rows:
        if str(row.get("ID_SEMANA_OBRA_GRUESA", "")).strip() != str(week_id).strip():
            continue
        if not _truthy(row.get("INCLUIR_INFORME")):
            continue
        if not str(row.get("IMAGEN", "")).strip():
            continue
        result.append(row)

    result.sort(
        key=lambda r: (
            str(r.get("FECHA", "")),
            str(r.get("ID_REGISTRO_FOTOGRAFICO", "")),
        )
    )

    limit = _safe_int(os.getenv("MAX_REPORT_PHOTOS", "6"), 6)
    return result[:max(1, limit)]


def _load_media(
    drive: DriveClient,
    vista: dict[str, Any] | None,
    photos: list[dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    svg_data_uri: str | None = None

    if vista:
        svg_path = str(vista.get("SVG_URI", "")).strip()
        if svg_path:
            try:
                svg_data_uri = drive.data_uri_svg(svg_path)
            except Exception as exc:
                warnings.append(f"SVG no incorporado: {exc}")

    photo_context = []

    for row in photos:
        image_path = str(row.get("IMAGEN", "")).strip()
        try:
            image_uri = drive.data_uri_photo(image_path)
        except Exception as exc:
            warnings.append(
                f"Foto {row.get('ID_REGISTRO_FOTOGRAFICO', '')} "
                f"no incorporada: {exc}"
            )
            continue

        photo_context.append({
            "imagen": image_uri,
            "fecha": row.get("FECHA"),
            "piso": row.get("PISO"),
            "comentario": row.get("COMENTARIO"),
            "id": row.get("ID_REGISTRO_FOTOGRAFICO"),
        })

    return svg_data_uri, photo_context, warnings


def _enrich_with_obra(
    informe: dict[str, Any],
    obra_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    data = dict(informe)

    if obra_rows:
        obra = obra_rows[0]
        for key in (
            "ID_OBRA",
            "NOMBRE_OBRA",
            "DIRECCION_OBRA",
            "FECHA_INICIO_OBRA",
            "FECHA_TERMINO_OBRA",
            "ADMINISTRADOR_OBRA",
        ):
            if data.get(key) in (None, "", "—") and obra.get(key) not in (None, ""):
                data[key] = obra.get(key)

    return data


def load_report_data(
    id_informe: str,
) -> tuple[
    dict[str, Any],
    str | None,
    list[dict[str, Any]],
    list[str],
]:
    appsheet = AppSheetClient()
    drive = DriveClient()

    informe = appsheet.find_by_key(
        TABLE_INFORME,
        "ID_INFORME",
        id_informe,
    )

    # Apagar el gatillo apenas el backend toma el trabajo.
    try:
        appsheet.edit_row(
            TABLE_INFORME,
            {
                "ID_INFORME": id_informe,
                "REGENERAR_INFORME": False,
            },
        )
    except Exception:
        # No bloquea la generación si la columna está temporalmente no editable.
        pass

    obra_rows = appsheet.find_rows(TABLE_OBRA)
    data = _enrich_with_obra(informe, obra_rows)

    vista_rows = appsheet.find_rows(TABLE_VISTA)
    vista = _choose_vista(vista_rows)

    week_id = data.get("ID_SEMANA_OBRA_GRUE")
    photo_rows = appsheet.find_rows(TABLE_FOTOS)
    selected = _selected_photos(photo_rows, week_id)

    svg_data_uri, photos, warnings = _load_media(
        drive,
        vista,
        selected,
    )

    return data, svg_data_uri, photos, warnings


def build_context(
    data: dict[str, Any],
    svg_data_uri: str | None = None,
    photos: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    logo_file = STATIC_DIR / "logo_altius.png"

    return {
        "d": data,
        "logo_path": (
            logo_file.resolve().as_uri()
            if logo_file.exists()
            else None
        ),
        "chart_programa": programa_tres_semanas(data),
        "svg_alzaprimado": svg_data_uri,
        "fotos": photos or [],
        "warnings": warnings or [],
        "f": {
            "date": fmt_date,
            "m3": fmt_m3,
            "num": fmt_number,
            "pct": fmt_percent,
            "clp": fmt_clp,
            "uf": fmt_uf,
            "first": first_value,
        },
    }


def render_pdf_bytes(
    id_informe: str,
    data: dict[str, Any],
    svg_data_uri: str | None,
    photos: list[dict[str, Any]],
    warnings: list[str],
) -> bytes:
    template = env.get_template("informe_semanal.html")
    html = template.render(
        **build_context(
            data,
            svg_data_uri=svg_data_uri,
            photos=photos,
            warnings=warnings,
        )
    )

    css_file = STATIC_DIR / "report.css"
    stylesheets = [CSS(filename=str(css_file))] if css_file.exists() else []

    return HTML(
        string=html,
        base_url=str(BASE_DIR),
    ).write_pdf(stylesheets=stylesheets)


def generate_preview(
    id_informe: str,
) -> tuple[bytes, dict[str, Any]]:
    data, svg, photos, warnings = load_report_data(id_informe)
    pdf_bytes = render_pdf_bytes(
        id_informe,
        data,
        svg,
        photos,
        warnings,
    )

    info = {
        "id_informe": id_informe,
        "fotos_incluidas": len(photos),
        "svg_incluido": bool(svg),
        "warnings": warnings,
    }
    return pdf_bytes, info


def generate_and_publish(
    id_informe: str,
) -> dict[str, Any]:
    appsheet = AppSheetClient()
    drive = DriveClient()

    data, svg, photos, warnings = load_report_data(id_informe)

    pdf_bytes = render_pdf_bytes(
        id_informe,
        data,
        svg,
        photos,
        warnings,
    )

    safe_id = "".join(
        c for c in str(id_informe)
        if c.isalnum() or c in ("-", "_")
    ) or "informe"

    filename = f"Informe_Semanal_OG_{safe_id}.pdf"

    uploaded: DriveUploadResult = drive.upload_or_replace_pdf(
        pdf_bytes,
        filename,
    )

    today_us = datetime.now().strftime("%m/%d/%Y")

    appsheet.edit_row(
        TABLE_INFORME,
        {
            "ID_INFORME": id_informe,
            "ARCHIVO_INFORME": uploaded.relative_path,
            "FECHA_EMISION": today_us,
            "ESTADO_INFORME": "EMITIDO",
            "REGENERAR_INFORME": False,
        },
    )

    return {
        "ok": True,
        "id_informe": id_informe,
        "archivo_informe": uploaded.relative_path,
        "drive_file_id": uploaded.file_id,
        "drive_web_url": uploaded.web_view_link,
        "fotos_incluidas": len(photos),
        "svg_incluido": bool(svg),
        "warnings": warnings,
    }
