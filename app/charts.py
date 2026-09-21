\
from __future__ import annotations

import base64
import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .formatters import to_float


BRAND_BLUE = "#1769FF"
BRAND_NAVY = "#031F73"
ACCENT_ORANGE = "#F2994A"


def _fig_to_data_uri(fig) -> str:
    buffer = io.BytesIO()
    fig.savefig(
        buffer,
        format="png",
        dpi=170,
        bbox_inches="tight",
        facecolor="white",
    )
    plt.close(fig)
    buffer.seek(0)
    return (
        "data:image/png;base64,"
        + base64.b64encode(buffer.read()).decode("ascii")
    )


def programa_tres_semanas(data: dict) -> str | None:
    labels = ["Hace 2 sem", "Anterior", "Actual"]
    programado = [
        to_float(data.get("M3_PROGRAMADOS_2SEM")),
        to_float(data.get("M3_PROGRAMADOS_SEM_ANT")),
        to_float(data.get("M3_PROGRAMADOS_SEMANA")),
    ]
    real = [
        to_float(data.get("M3_REALES_2SEM")),
        to_float(data.get("M3_REALES_SEM_ANT")),
        to_float(data.get("M3_REALES_SEMANA")),
    ]

    if not any(programado) and not any(real):
        return None

    x = list(range(len(labels)))
    width = 0.34

    fig, ax = plt.subplots(figsize=(7.2, 2.7))

    ax.bar(
        [i - width / 2 for i in x],
        programado,
        width,
        label="Programado",
        color=BRAND_BLUE,
    )
    ax.bar(
        [i + width / 2 for i in x],
        real,
        width,
        label="Real",
        color=ACCENT_ORANGE,
    )

    ax.set_xticks(x, labels)
    ax.set_ylabel("m³")
    ax.set_title(
        "Producción semanal: programa vs real",
        color=BRAND_NAVY,
        fontweight="bold",
    )
    ax.legend(frameon=False, ncol=2, loc="upper left")
    ax.grid(axis="y", alpha=0.16)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.tight_layout()
    return _fig_to_data_uri(fig)
