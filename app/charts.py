from __future__ import annotations

import base64
import io
from datetime import date
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt


BRAND_BLUE = "#1769FF"
BRAND_NAVY = "#031F73"
BRAND_MID = "#0A3AB8"
BAND_FILL = "#DDE9FF"
ACCENT_ORANGE = "#F2994A"
MUTED = "#687386"
GRID = "#D8E0EA"


def _fig_to_data_uri(fig) -> str:
    buffer = io.BytesIO()
    fig.savefig(
        buffer,
        format="png",
        dpi=180,
        bbox_inches="tight",
        facecolor="white",
    )
    plt.close(fig)
    buffer.seek(0)
    return (
        "data:image/png;base64,"
        + base64.b64encode(buffer.read()).decode("ascii")
    )


def curvas_acumuladas(
    series: list[dict[str, Any]],
    current_date: date | None,
) -> str | None:
    """
    Curva acumulada ejecutiva.

    V1.2.3:
    - eje X mensual y explícito en formato dd/mm/aa;
    - etiquetas rotadas para evitar ambigüedad;
    - leyenda completamente fuera del área de trazado;
    - mayor margen superior para que las curvas nunca se crucen
      visualmente con la leyenda;
    - marca vertical de fecha de corte conservada.
    """
    if not series:
        return None

    dates = [item["date"] for item in series]
    lower = [item.get("lower") for item in series]
    upper = [item.get("upper") for item in series]
    real = [item.get("real") for item in series]

    if not any(v is not None for v in lower + upper + real):
        return None

    # Se aumenta levemente la altura para separar:
    # título -> leyenda -> área de curvas -> eje X.
    fig, ax = plt.subplots(figsize=(7.2, 2.95))

    ax.plot(
        dates,
        lower,
        label="Banda inferior",
        linewidth=1.8,
        color=BRAND_MID,
        zorder=3,
    )

    ax.plot(
        dates,
        upper,
        label="Banda superior",
        linewidth=1.8,
        color=BRAND_BLUE,
        zorder=3,
    )

    # Sombreado de la banda de control.
    fill_dates = []
    fill_lower = []
    fill_upper = []

    for d, lo, up in zip(dates, lower, upper):
        if lo is not None and up is not None:
            fill_dates.append(d)
            fill_lower.append(lo)
            fill_upper.append(up)

    if fill_dates:
        ax.fill_between(
            fill_dates,
            fill_lower,
            fill_upper,
            color=BAND_FILL,
            alpha=0.55,
            linewidth=0,
            label="Banda de control",
            zorder=1,
        )

    # Curva real solamente hasta la última semana con dato real.
    real_dates = [
        d for d, v in zip(dates, real)
        if v is not None
    ]

    real_values = [
        v for v in real
        if v is not None
    ]

    if real_dates:
        ax.plot(
            real_dates,
            real_values,
            label="Real acumulado",
            linewidth=2.6,
            marker="o",
            markersize=3.8,
            color=ACCENT_ORANGE,
            zorder=4,
        )

        ax.scatter(
            [real_dates[-1]],
            [real_values[-1]],
            s=38,
            color=ACCENT_ORANGE,
            zorder=5,
        )

    # Fecha de corte del informe.
    if current_date:
        ax.axvline(
            current_date,
            color=MUTED,
            linestyle="--",
            linewidth=1.0,
            alpha=0.80,
            zorder=2,
        )

    # El título es de figura para reservar una franja independiente.
    fig.suptitle(
        "Curvas acumuladas de hormigón",
        color=BRAND_NAVY,
        fontweight="bold",
        fontsize=11,
        y=0.985,
    )

    ax.set_ylabel(
        "m³ acumulados",
        fontsize=8.5,
    )

    ax.set_xlabel(
        "Fecha",
        fontsize=8,
        labelpad=5,
    )

    # Un tick por mes, siempre el día 01.
    # El año explícito evita confundir dd/mm con mm/dd.
    ax.xaxis.set_major_locator(
        mdates.MonthLocator(
            bymonthday=1,
            interval=1,
        )
    )

    ax.xaxis.set_major_formatter(
        mdates.DateFormatter("%d/%m/%y")
    )

    # Mejor lectura en PDF.
    plt.setp(
        ax.get_xticklabels(),
        rotation=38,
        ha="right",
        rotation_mode="anchor",
    )

    ax.grid(
        axis="y",
        color=GRID,
        alpha=0.55,
        linewidth=0.7,
        zorder=0,
    )

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    ax.tick_params(
        axis="both",
        labelsize=7.6,
    )

    # Leyenda fuera del área de datos:
    # queda entre el título y el gráfico.
    handles, labels = ax.get_legend_handles_labels()

    fig.legend(
        handles,
        labels,
        frameon=False,
        ncol=4,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.915),
        fontsize=7.4,
        columnspacing=1.6,
        handlelength=2.4,
    )

    # Reserva explícita para título/leyenda y para fechas rotadas.
    fig.subplots_adjust(
        left=0.105,
        right=0.985,
        bottom=0.235,
        top=0.735,
    )

    return _fig_to_data_uri(fig)


def trend_chart(
    labels: list[str],
    values: list[float | None],
    title: str,
    unit: str,
    percent: bool = False,
) -> str | None:
    if not any(v is not None for v in values):
        return None

    xs = list(range(len(labels)))
    plot_values = [
        (v * 100.0 if percent and v is not None else v)
        for v in values
    ]

    fig, ax = plt.subplots(figsize=(2.22, 1.35))
    ax.plot(
        xs,
        plot_values,
        color=BRAND_BLUE,
        marker="o",
        linewidth=2.0,
        markersize=4.0,
    )

    ax.set_xticks(xs, labels)
    ax.tick_params(axis="x", labelsize=7)
    ax.tick_params(axis="y", labelsize=7)
    ax.grid(axis="y", color=GRID, alpha=0.55, linewidth=0.6)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_title(
        title,
        color=BRAND_NAVY,
        fontsize=8.6,
        fontweight="bold",
        pad=4,
    )

    if percent:
        ax.set_ylabel("%", fontsize=7)
    elif unit:
        ax.set_ylabel(unit, fontsize=7)

    fig.tight_layout(pad=0.5)
    return _fig_to_data_uri(fig)


def weekly_trend_charts(weekly: dict[str, Any]) -> list[dict[str, Any]]:
    rows = weekly.get("weeks", [])
    labels = [row.get("short", "") for row in rows]

    definitions = [
        ("M³ proyectados", "projected", "m³", False),
        ("M³ reales", "real", "m³", False),
        ("M³ geométricos", "geometric", "m³", False),
        ("% cumplimiento", "compliance", "%", True),
        ("% pérdida", "loss", "%", True),
    ]

    result = []
    for title, key, unit, percent in definitions:
        values = [row.get(key) for row in rows]
        image = trend_chart(
            labels=labels,
            values=values,
            title=title,
            unit=unit,
            percent=percent,
        )
        result.append(
            {
                "title": title,
                "image": image,
            }
        )

    return result
