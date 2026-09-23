from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import CSS, HTML

from .analytics import (
    build_floor_map,
    build_general_summary,
    build_invoice_summary,
    build_weekly_summary,
    find_week,
)
from .appsheet_client import AppSheetClient
from .charts import curvas_acumuladas, weekly_trend_charts
from .drive_client import DriveClient, DriveUploadResult
from .formatters import (
    first_value,
    fmt_clp,
    fmt_date,
    fmt_days_deviation,
    fmt_floor,
    fmt_m3,
    fmt_month_year,
    fmt_number,
    fmt_percent,
    fmt_signed_m3,
    fmt_uf,
)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

TABLE_INFORME = "INFORME"
TABLE_OBRA = "OBRA"
TABLE_SEMANAS = "SEMANAS_OBRA_GRUESA"
TABLE_VISTA = "VISTA_ALZAPRIMADO"
TABLE_FOTOS = "REGISTRO_AVANCE_SEMANAL"
TABLE_PISOS = "PISOS"
TABLE_FACTURAS = "FACTURAS"

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
    target = str(week_id or "").strip()

    for row in rows:
        current_week = str(
            row.get("ID_SEMANA_OBRA_GRUESA", "")
        ).strip()

        if current_week != target:
            continue
        if not _truthy(row.get("INCLUIR_INFORME")):
            continue
        if not str(row.get("IMAGEN", "")).strip():
            continue

        result.append(row)

    # El orden final se normaliza por fecha en el PDF; aquí usamos fecha textual
    # y key para mantener determinismo incluso si hay registros en el mismo día.
    result.sort(
        key=lambda r: (
            str(r.get("FECHA", "")),
            str(r.get("ID_REGISTRO_FOTOGRAFICO", "")),
        )
    )

    import os
    limit = _safe_int(os.getenv("MAX_REPORT_PHOTOS", "6"), 6)
    return result[:max(1, limit)]


def _load_media(
    drive: DriveClient,
    vista: dict[str, Any] | None,
    photos: list[dict[str, Any]],
    floor_map: dict[str, Any],
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

        floor_ref = str(row.get("PISO", "")).strip()
        floor_real = floor_map.get(floor_ref)
        if floor_real in (None, ""):
            floor_real = floor_ref or None

        photo_context.append(
            {
                "imagen": image_uri,
                "fecha": row.get("FECHA"),
                "piso": floor_real,
                "comentario": row.get("COMENTARIO"),
                "id": row.get("ID_REGISTRO_FOTOGRAFICO"),
            }
        )

    return svg_data_uri, photo_context, warnings


def _select_obra(
    informe: dict[str, Any],
    obra_rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not obra_rows:
        return None

    target = str(informe.get("ID_OBRA", "")).strip()
    if target:
        for row in obra_rows:
            if str(row.get("ID_OBRA", "")).strip() == target:
                return row

    return obra_rows[0]


def _enrich_with_obra(
    informe: dict[str, Any],
    obra_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    data = dict(informe)
    obra = _select_obra(informe, obra_rows)

    if obra:
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


def load_report_data(id_informe: str) -> dict[str, Any]:
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
        # No bloquear la generación si la columna está temporalmente no editable.
        pass

    obra_rows = appsheet.find_rows(TABLE_OBRA)
    data = _enrich_with_obra(informe, obra_rows)

    week_rows = appsheet.find_rows(TABLE_SEMANAS)
    week_id = data.get("ID_SEMANA_OBRA_GRUE")
    current_week = find_week(week_rows, week_id)

    general = build_general_summary(
        data=data,
        weeks=week_rows,
        current_week=current_week,
    )

    weekly = build_weekly_summary(data)

    invoice_rows = appsheet.find_rows(TABLE_FACTURAS)
    invoices = build_invoice_summary(
        invoices=invoice_rows,
        cutoff_value=data.get("FECHA_CORTE"),
        data=data,
    )

    floor_rows = appsheet.find_rows(TABLE_PISOS)
    floor_map = build_floor_map(floor_rows)

    vista_rows = appsheet.find_rows(TABLE_VISTA)
    vista = _choose_vista(vista_rows)

    photo_rows = appsheet.find_rows(TABLE_FOTOS)
    selected = _selected_photos(photo_rows, week_id)

    svg_data_uri, photos, warnings = _load_media(
        drive=drive,
        vista=vista,
        photos=selected,
        floor_map=floor_map,
    )

    return {
        "data": data,
        "general": general,
        "weekly": weekly,
        "invoices": invoices,
        "svg": svg_data_uri,
        "photos": photos,
        "warnings": warnings,
    }


def build_context(bundle: dict[str, Any]) -> dict[str, Any]:
    data = bundle["data"]
    general = bundle["general"]
    weekly = bundle["weekly"]

    logo_file = STATIC_DIR / "logo_altius.png"

    return {
        "d": data,
        "general": general,
        "weekly": weekly,
        "invoices": bundle["invoices"],
        "logo_path": (
            logo_file.resolve().as_uri()
            if logo_file.exists()
            else None
        ),
        "chart_curves": curvas_acumuladas(
            general.get("series", []),
            general.get("week_end"),
        ),
        "trend_charts": weekly_trend_charts(weekly),
        "svg_alzaprimado": bundle["svg"],
        "fotos": bundle["photos"],
        "warnings": bundle["warnings"],
        "f": {
            "date": fmt_date,
            "m3": fmt_m3,
            "signed_m3": fmt_signed_m3,
            "num": fmt_number,
            "pct": fmt_percent,
            "clp": fmt_clp,
            "uf": fmt_uf,
            "month_year": fmt_month_year,
            "days_deviation": fmt_days_deviation,
            "floor": fmt_floor,
            "first": first_value,
        },
    }


def render_pdf_bytes(
    id_informe: str,
    bundle: dict[str, Any],
) -> bytes:
    template = env.get_template("informe_semanal.html")
    html = template.render(**build_context(bundle))

    css_file = STATIC_DIR / "report.css"
    stylesheets = [CSS(filename=str(css_file))] if css_file.exists() else []

    return HTML(
        string=html,
        base_url=str(BASE_DIR),
    ).write_pdf(stylesheets=stylesheets)


def generate_preview(id_informe: str) -> tuple[bytes, dict[str, Any]]:
    bundle = load_report_data(id_informe)
    pdf_bytes = render_pdf_bytes(id_informe, bundle)

    info = {
        "id_informe": id_informe,
        "fotos_incluidas": len(bundle["photos"]),
        "svg_incluido": bool(bundle["svg"]),
        "warnings": bundle["warnings"],
    }
    return pdf_bytes, info


def generate_and_publish(id_informe: str) -> dict[str, Any]:
    appsheet = AppSheetClient()
    drive = DriveClient()

    bundle = load_report_data(id_informe)
    pdf_bytes = render_pdf_bytes(id_informe, bundle)

    safe_id = "".join(
        c for c in str(id_informe)
        if c.isalnum() or c in ("-", "_")
    ) or "informe"

    filename = f"Informe_Semanal_OG_{safe_id}.pdf"

    uploaded: DriveUploadResult = drive.upload_or_replace_pdf(
        pdf_bytes,
        filename,
    )

    # AppSheet API está operando con locale en-US.
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
        "fotos_incluidas": len(bundle["photos"]),
        "svg_incluido": bool(bundle["svg"]),
        "estado_general": bundle["general"].get("state"),
        "warnings": bundle["warnings"],
    }
