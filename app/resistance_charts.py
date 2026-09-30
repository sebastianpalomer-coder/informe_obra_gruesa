from __future__ import annotations

import base64
import io
import math
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BRAND_BLUE = "#1769FF"
BRAND_NAVY = "#031F73"
MUTED = "#687386"
GRID = "#D8E0EA"
RED = "#EB5757"
GREEN = "#27AE60"
ORANGE = "#F2994A"


def _uri(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _finish(ax, title: str, labels: list[str]):
    ax.set_title(title, color=BRAND_NAVY, fontsize=10.5, fontweight="bold", pad=10)
    ax.set_ylabel("Resistencia (unidad del ensayo)", fontsize=8.0)
    ax.grid(axis="y", color=GRID, linewidth=.7, alpha=.7)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(GRID)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(axis="both", labelsize=7)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.27), ncol=3, frameon=False, fontsize=7)
    fig = ax.figure
    fig.subplots_adjust(left=.09, right=.985, top=.86, bottom=.32)


def _limits(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0, 1
    lo, hi = min(values), max(values)
    span = max(hi - lo, max(abs(hi), 1) * .10)
    return max(0, lo - span * .55), hi + span * .55


def individual_chart(grade: dict[str, Any]) -> str | None:
    rows = grade.get("definitives", [])
    if not rows:
        return None
    values = [x["individual"] for x in rows]
    mins = [x.get("min_individual") for x in rows]
    labels = [x["guia"] for x in rows]
    x = list(range(len(rows)))

    fig, ax = plt.subplots(figsize=(7.2, 2.75))
    ok_x, ok_y, bad_x, bad_y = [], [], [], []
    for i, (value, minimum) in enumerate(zip(values, mins)):
        bad = minimum is not None and value < minimum
        (bad_x if bad else ok_x).append(i)
        (bad_y if bad else ok_y).append(value)

    if ok_x:
        ax.scatter(ok_x, ok_y, s=28, color=BRAND_BLUE, label="Resistencia individual", zorder=4)
    if bad_x:
        ax.scatter(bad_x, bad_y, s=38, color=RED, label="Bajo mínimo", zorder=5)
    if any(v is not None for v in mins):
        ax.plot(x, [float("nan") if v is None else v for v in mins], color=RED, linewidth=1.6,
                linestyle="--", label="Mínima individual", zorder=3)
    ydata = values + [v for v in mins if v is not None]
    ax.set_ylim(*_limits(ydata))
    _finish(ax, f"{grade['grade']} - Resistencia individual promedio a 28 días", labels)
    return _uri(fig)


def moving_chart(grade: dict[str, Any]) -> str | None:
    rows = grade.get("moving", [])
    if not rows:
        return None
    values = [x["value"] for x in rows]
    mins = [x.get("minimum") for x in rows]
    labels = [x["guia"] for x in rows]
    x = list(range(len(rows)))

    fig, ax = plt.subplots(figsize=(7.2, 2.75))
    ax.plot(x, values, color=BRAND_BLUE, linewidth=1.8, marker="o", markersize=4.1,
            label="Media móvil (3 muestras)", zorder=4)
    bad_x = [i for i, r in enumerate(rows) if r.get("below")]
    if bad_x:
        ax.scatter(bad_x, [values[i] for i in bad_x], s=38, color=RED, label="Bajo mínimo", zorder=5)
    if any(v is not None for v in mins):
        ax.plot(x, [float("nan") if v is None else v for v in mins], color=RED, linewidth=1.6,
                linestyle="--", label="Mínima media móvil", zorder=3)
    ydata = values + [v for v in mins if v is not None]
    ax.set_ylim(*_limits(ydata))
    _finish(ax, f"{grade['grade']} - Media móvil de 3 muestras", labels)
    return _uri(fig)


def attach_resistance_charts(report: dict[str, Any]) -> dict[str, Any]:
    for grade in report.get("grades", []):
        for key, builder in (("chart_individual", individual_chart), ("chart_moving", moving_chart)):
            try:
                grade[key] = builder(grade)
            except Exception as exc:
                grade[key] = None
                report["warnings"].append(
                    f"No se pudo graficar {grade['grade']} ({key}): {exc}"
                )
    return report
