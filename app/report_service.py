from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML, CSS

from .charts import programa_tres_semanas
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
OUTPUT_DIR = BASE_DIR / "output"

env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


def build_context(data: dict[str, Any]) -> dict[str, Any]:
    chart_programa = programa_tres_semanas(data)

    logo_file = STATIC_DIR / "logo_altius.png"

    return {
        "d": data,
        "logo_path": logo_file.resolve().as_uri() if logo_file.exists() else None,
        "chart_programa": chart_programa,
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


def generate_pdf(id_informe: str, data: dict[str, Any]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    template = env.get_template("informe_semanal.html")
    html = template.render(**build_context(data))

    safe_id = "".join(
        c for c in str(id_informe)
        if c.isalnum() or c in ("-", "_")
    ) or "informe"

    output_path = OUTPUT_DIR / f"Informe_Semanal_OG_{safe_id}.pdf"

    css_file = STATIC_DIR / "report.css"
    stylesheets = []

    if css_file.exists():
        stylesheets.append(
            CSS(filename=str(css_file))
        )

    HTML(
        string=html,
        base_url=str(BASE_DIR),
    ).write_pdf(
        str(output_path),
        stylesheets=stylesheets,
    )

    return output_path
