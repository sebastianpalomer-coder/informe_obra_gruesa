"""Selección estricta de instantáneas históricas de alzaprimado.

No es posible reconstruir retrospectivamente el estado de un SVG que el
Apps Script anterior borró. Solo se admiten archivos archivados y creados
hasta el cierre local del informe. Nunca se presenta un SVG futuro como histórico.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class AlzaprimadoSnapshot:
    file_id: str
    name: str
    created_local: datetime


def safe_vista_id(id_vista: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(id_vista or "").strip())


def select_snapshot(
    files: Iterable[dict[str, Any]],
    *,
    id_vista: str,
    cutoff: date,
    time_zone: str = "America/Santiago",
) -> AlzaprimadoSnapshot | None:
    """Último SVG conservado y creado hasta las 23:59:59 del día de corte.

    createdTime es autoritativo: evita interpretar como históricos archivos
    creados posteriormente aunque el nombre contenga una fecha antigua.
    El nombre se valida además para evitar incorporar SVG de otra vista.
    """
    vista = safe_vista_id(id_vista)
    if not vista:
        return None
    name_re = re.compile(
        r"^ALZAPRIMADO_" + re.escape(vista)
        + r"_\d{8}_\d{6}(?:_\d{3})?\.svg$",
        re.IGNORECASE,
    )
    tz = ZoneInfo(time_zone)
    end_exclusive = datetime.combine(cutoff + timedelta(days=1), time.min, tzinfo=tz)
    best: AlzaprimadoSnapshot | None = None
    for file in files:
        filename = str(file.get("name") or "")
        file_id = str(file.get("id") or "")
        if not file_id or not name_re.fullmatch(filename):
            continue
        raw_created = str(file.get("createdTime") or "").strip()
        if not raw_created:
            continue
        try:
            created = datetime.fromisoformat(raw_created.replace("Z", "+00:00"))
        except ValueError:
            continue
        if created.tzinfo is None:
            continue  # No se permite adivinar la zona de un instante histórico.
        created_local = created.astimezone(tz)
        if created_local >= end_exclusive:
            continue
        candidate = AlzaprimadoSnapshot(file_id, filename, created_local)
        if best is None or (candidate.created_local, candidate.name) > (best.created_local, best.name):
            best = candidate
    return best


def max_created_time_utc(cutoff: date, time_zone: str) -> str:
    tz = ZoneInfo(time_zone)
    next_day = datetime.combine(cutoff + timedelta(days=1), time.min, tzinfo=tz)
    return next_day.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
