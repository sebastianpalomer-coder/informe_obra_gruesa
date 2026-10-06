from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any

from .appsheet_client import AppSheetClient
from .drive_client import DriveClient
from .fierro_order_parser import FierroOrder, parse_fierro_order


TABLE_PEDIDOS = os.getenv(
    "FIERRO_PEDIDOS_TABLE",
    "PEDIDOS_FIERRO",
).strip() or "PEDIDOS_FIERRO"

TABLE_DETALLE = os.getenv(
    "FIERRO_PEDIDOS_DETALLE_TABLE",
    "PEDIDOS_FIERRO_DETALLE",
).strip() or "PEDIDOS_FIERRO_DETALLE"

KEY_PEDIDO = "ID_PEDIDO_FIERRO"
KEY_DETALLE = "ID_DETALLE_PEDIDO"
FILE_COLUMN = "ARCHIVO_PEDIDO"

logger = logging.getLogger(__name__)


def _now_appsheet() -> str:
    now_chile = datetime.now(ZoneInfo("America/Santiago"))
    return now_chile.strftime("%m/%d/%Y %H:%M:%S")


def _date_appsheet(value) -> str:
    return value.strftime("%m/%d/%Y")


def _clean_error(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text[:1800]


def _detail_rows(order_id: str, order: FierroOrder) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in order.lineas:
        rows.append(
            {
                KEY_DETALLE: uuid.uuid4().hex,
                KEY_PEDIDO: order_id,
                "DIAMETRO_MM": line.diametro_mm,
                "LARGO_M": line.largo_m,
                "KG_MT": line.kg_mt,
                "BARRAS_SOLICITADAS": line.barras_solicitadas,
                "KG_SOLICITADOS": line.kg_solicitados,
            }
        )
    return rows


def _delete_previous_details(
    appsheet: AppSheetClient,
    order_id: str,
) -> int:
    rows = appsheet.find_rows(TABLE_DETALLE)
    keys = [
        {KEY_DETALLE: row.get(KEY_DETALLE)}
        for row in rows
        if str(row.get(KEY_PEDIDO, "")).strip() == str(order_id).strip()
        and row.get(KEY_DETALLE)
    ]
    if keys:
        appsheet.delete_rows(TABLE_DETALLE, keys)
    return len(keys)


def process_fierro_order(id_pedido_fierro: str) -> dict[str, Any]:
    appsheet = AppSheetClient()
    drive = DriveClient()

    pedido = appsheet.find_by_key(
        TABLE_PEDIDOS,
        KEY_PEDIDO,
        id_pedido_fierro,
    )

    file_path = str(pedido.get(FILE_COLUMN) or "").strip()
    logger.info(
        "pedido_fierro stage=pedido_encontrado id=%s archivo=%s",
        id_pedido_fierro,
        file_path,
    )
    if not file_path:
        raise RuntimeError(
            f"{TABLE_PEDIDOS}[{FILE_COLUMN}] está vacío para "
            f"{id_pedido_fierro}."
        )

    appsheet.edit_row(
        TABLE_PEDIDOS,
        {
            KEY_PEDIDO: id_pedido_fierro,
            "ESTADO_PROCESAMIENTO": "PROCESANDO",
            "OBSERVACION_PROCESAMIENTO": "",
        },
    )
    logger.info(
        "pedido_fierro stage=procesando id=%s",
        id_pedido_fierro,
    )

    try:
        content, _mime, filename = drive.download_fierro_order(file_path)
        logger.info(
            "pedido_fierro stage=archivo_descargado id=%s filename=%s bytes=%s",
            id_pedido_fierro,
            filename,
            len(content),
        )
        parsed = parse_fierro_order(content, filename)
        logger.info(
            "pedido_fierro stage=archivo_parseado id=%s pedido=%s lineas=%s",
            id_pedido_fierro,
            parsed.numero_pedido,
            len(parsed.lineas),
        )

        deleted = _delete_previous_details(
            appsheet,
            id_pedido_fierro,
        )

        rows = _detail_rows(id_pedido_fierro, parsed)
        appsheet.add_rows(TABLE_DETALLE, rows)

        appsheet.edit_row(
            TABLE_PEDIDOS,
            {
                KEY_PEDIDO: id_pedido_fierro,
                "N_PEDIDO": parsed.numero_pedido,
                "FECHA_PEDIDO": _date_appsheet(parsed.fecha_pedido),
                "FECHA_REQUERIDA_OBRA": _date_appsheet(
                    parsed.fecha_requerida_obra
                ),
                "HORA_REQUERIDA": parsed.hora_requerida,
                "AREA": parsed.area,
                "ESTADO_PROCESAMIENTO": "PROCESADO",
                "FECHA_PROCESAMIENTO": _now_appsheet(),
                "OBSERVACION_PROCESAMIENTO": "",
            },
        )

        return {
            "ok": True,
            "id_pedido_fierro": id_pedido_fierro,
            "archivo": filename,
            "numero_pedido": parsed.numero_pedido,
            "area": parsed.area,
            "fecha_pedido": parsed.fecha_pedido.isoformat(),
            "fecha_requerida_obra": parsed.fecha_requerida_obra.isoformat(),
            "hora_requerida": parsed.hora_requerida,
            "lineas": len(rows),
            "kg_solicitados": parsed.total_kg,
            "detalle_anterior_eliminado": deleted,
        }

    except Exception as exc:
        logger.exception(
            "pedido_fierro stage=error id=%s",
            id_pedido_fierro,
        )
        # El estado ERROR se intenta registrar aun cuando falle la lectura,
        # el parser o la escritura del detalle.
        try:
            appsheet.edit_row(
                TABLE_PEDIDOS,
                {
                    KEY_PEDIDO: id_pedido_fierro,
                    "ESTADO_PROCESAMIENTO": "ERROR",
                    "FECHA_PROCESAMIENTO": _now_appsheet(),
                    "OBSERVACION_PROCESAMIENTO": _clean_error(exc),
                },
            )
        except Exception:
            pass
        raise
