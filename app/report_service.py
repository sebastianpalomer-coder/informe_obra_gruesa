from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import os
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
from .drive_client import DriveClient
from .report_writer_client import ReportWriterClient, ReportWriterResult
from .resistance_report import build_resistance_report
from .resistance_charts import attach_resistance_charts
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
    parse_appsheet_date,
)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

TABLE_INFORME = "INFORME"
TABLE_OBRA = "OBRA"
TABLE_SEMANAS = "SEMANAS_OBRA_GRUESA"
TABLE_PROGRAMA_SEMANAL = "PROGRAMA_SEMANAL"
TABLE_GUIAS = "GUIAS"
TABLE_VISTA = "VISTA_ALZAPRIMADO"
TABLE_FOTOS = "REGISTRO_AVANCE_SEMANAL"
TABLE_PISOS = "PISOS"
TABLE_FACTURAS = "FACTURAS"
TABLE_RESISTENCIAS = "TABLA_RESISTENCIA"
TABLE_CERTIFICADOS = "TABLA_CERTIFICADO_HORMIGON"
TABLE_VISITAS_MUESTRA = "TABLA_VISITA_TOMA_MUESTRA"
TABLE_ELEMENTOS = "ELEMENTOS"

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

    # El Apps Script v5.8.x genera la primera fila de VISTA_ALZAPRIMADO.
    # Elegir la misma vista en Cloud Run evita mezclar archivos de distintas vistas.
    usable.sort(key=lambda r: _safe_int(r.get("_RowNumber"), 999999))
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
    cutoff: date,
) -> tuple[str | None, list[dict[str, Any]], list[str], dict[str, Any]]:
    warnings: list[str] = []
    svg_data_uri: str | None = None
    svg_snapshot: dict[str, Any] = {
        "fecha": None,
        "detalle": (
            "No hay una instantánea histórica de alzaprimado conservada "
            "hasta el cierre de este informe. No se incorpora el estado "
            "actual porque podría incluir modificaciones posteriores."
        ),
    }

    if vista:
        id_vista = str(vista.get("ID_VISTA") or "").strip()
        if not id_vista:
            warnings.append(
                "La vista actual de alzaprimado no tiene ID_VISTA; "
                "no es posible localizar su historial."
            )
        else:
            try:
                # No leer el SVG_URI actual: este es mutable y puede
                # representar eventos posteriores a FECHA_CORTE.
                found = drive.historical_alzaprimado_svg(
                    id_vista=id_vista,
                    cutoff=cutoff,
                    time_zone=os.getenv("REPORT_TIMEZONE", "America/Santiago"),
                )
                if found is not None:
                    svg_data_uri, snapshot = found
                    svg_snapshot = {
                        "fecha": snapshot.created_local.strftime("%d/%m/%Y %H:%M"),
                        "detalle": (
                            "Última instantánea archivada disponible antes del "
                            "cierre. Puede no incluir cambios posteriores "
                            "a su fecha de captura."
                        ),
                    }
                else:
                    warnings.append(
                        "Sin SVG histórico disponible para la vista "
                        f"{id_vista} al corte {cutoff:%d/%m/%Y}. "
                        "El SVG actual se omitió expresamente."
                    )
            except Exception as exc:
                warnings.append(f"SVG histórico de alzaprimado no incorporado: {exc}")
    else:
        warnings.append("No hay VISTA_ALZAPRIMADO con SVG_URI disponible.")

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

    return svg_data_uri, photo_context, warnings, svg_snapshot


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

    program_rows = appsheet.find_rows(TABLE_PROGRAMA_SEMANAL)
    guide_rows = appsheet.find_rows(TABLE_GUIAS)

    weekly = build_weekly_summary(
        weeks=week_rows,
        current_week=current_week,
        program_rows=program_rows,
        guide_rows=guide_rows,
    )

    invoice_rows = appsheet.find_rows(TABLE_FACTURAS)
    invoices = build_invoice_summary(
        invoices=invoice_rows,
        cutoff_value=data.get("FECHA_CORTE"),
        data=data,
    )

    floor_rows = appsheet.find_rows(TABLE_PISOS)
    floor_map = build_floor_map(floor_rows)
    # En el capítulo de resistencia se requiere la etiqueta de PISOS,
    # mientras que las fotografías conservan el campo N PISO.
    resistance_floor_map = {}
    for floor_row in floor_rows:
        floor_id = str(floor_row.get("ID_PISO") or "").strip()
        if floor_id:
            resistance_floor_map[floor_id] = (
                floor_row.get("PISO") or floor_row.get("N PISO") or floor_id
            )

    # V1.4.0: el capítulo usa dos tablas de AppSheet. Las fechas de
    # disponibilidad del certificado permiten reconstruir el corte semanal.
    # Fallos de consulta no deben impedir emitir las cinco páginas existentes.
    resistance_warnings = []
    resistances = []
    certificates = []
    visits = []
    elements = []
    try:
        resistances = appsheet.find_rows(TABLE_RESISTENCIAS)
        certificates = appsheet.find_rows(TABLE_CERTIFICADOS)
    except Exception as exc:
        resistance_warnings.append(
            f"No fue posible consultar tablas de resistencia: {exc}"
        )

    try:
        visits = appsheet.find_rows(TABLE_VISITAS_MUESTRA)
    except Exception as exc:
        resistance_warnings.append(
            f"No fue posible consultar TABLA_VISITA_TOMA_MUESTRA: {exc}; "
            "se intentará ubicación secundaria desde otras tablas."
        )

    try:
        elements = appsheet.find_rows(TABLE_ELEMENTOS)
    except Exception as exc:
        resistance_warnings.append(
            f"No fue posible consultar ELEMENTOS: {exc}; "
            "se mostrará ID_ELEMENTOS si no hay etiqueta disponible."
        )
    element_map = {
        str(r.get("ID_ELEMENTOS") or "").strip(): str(r.get("ELEMENTO") or "").strip()
        for r in elements
        if str(r.get("ID_ELEMENTOS") or "").strip() and str(r.get("ELEMENTO") or "").strip()
    }

    cutoff = (
        parse_appsheet_date(data.get("FECHA_CORTE"))
        or general.get("week_end")
    )
    if cutoff is None:
        from datetime import date
        cutoff = date.today()
        resistance_warnings.append(
            "No se encontró FECHA_CORTE ni término de semana; se usa la fecha actual."
        )

    resistance = build_resistance_report(
        rows=resistances,
        certificates=certificates,
        guide_rows=guide_rows,
        floor_map=resistance_floor_map,
        cutoff=cutoff,
        element_map=element_map,
        week_start=general.get("week_start"),
        visit_rows=visits,
    )
    resistance["warnings"].extend(resistance_warnings)
    attach_resistance_charts(resistance)

    vista_rows = appsheet.find_rows(TABLE_VISTA)
    vista = _choose_vista(vista_rows)

    photo_rows = appsheet.find_rows(TABLE_FOTOS)
    selected = _selected_photos(photo_rows, week_id)

    svg_data_uri, photos, warnings, svg_snapshot = _load_media(
        drive=drive,
        vista=vista,
        photos=selected,
        floor_map=floor_map,
        cutoff=cutoff,
    )

    return {
        "data": data,
        "general": general,
        "weekly": weekly,
        "invoices": invoices,
        "resistance": resistance,
        "svg": svg_data_uri,
        "svg_snapshot": svg_snapshot,
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
        "resistance": bundle["resistance"],
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
        "alz_snapshot": bundle.get("svg_snapshot") or {},
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
        "warnings": bundle["warnings"] + bundle["resistance"]["warnings"],
        "resistencia_grados": len(bundle["resistance"]["grades"]),
    }
    return pdf_bytes, info


def generate_and_publish(id_informe: str) -> dict[str, Any]:
    appsheet = AppSheetClient()
    writer = ReportWriterClient()

    bundle = load_report_data(id_informe)
    pdf_bytes = render_pdf_bytes(id_informe, bundle)

    safe_id = "".join(
        c for c in str(id_informe)
        if c.isalnum() or c in ("-", "_")
    ) or "informe"

    filename = f"Informe_Semanal_OG_{safe_id}.pdf"

    # V1.2.4:
    # El PDF se escribe mediante un Apps Script Web App ejecutado como
    # el usuario propietario. Así evitamos la limitación de cuota de
    # almacenamiento de las Service Accounts en Mi unidad.
    uploaded: ReportWriterResult = writer.upload_or_replace_pdf(
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
        "warnings": bundle["warnings"] + bundle["resistance"]["warnings"],
        "resistencia_grados": len(bundle["resistance"]["grades"]),
    }
