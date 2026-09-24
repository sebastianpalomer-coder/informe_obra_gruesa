from __future__ import annotations

import os

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from .daily_photo_report_service import (
    generate_daily_and_publish,
    generate_daily_preview,
)
from .report_service import (
    generate_and_publish,
    generate_preview,
)


app = FastAPI(
    title="Informes Obra Gruesa",
    version="1.3.0",
)


class InformeRequest(BaseModel):
    id_informe: str = Field(min_length=1)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id_informe": "REEMPLAZAR_POR_ID_REAL"
            }
        }
    )


class DailyPhotoReportRequest(BaseModel):
    id_informe_diario: str = Field(min_length=1)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id_informe_diario": "REEMPLAZAR_POR_ID_REAL"
            }
        }
    )


def _validate_token(
    x_report_token: str | None,
) -> None:
    expected = os.getenv(
        "REPORT_WEBHOOK_TOKEN",
        "",
    ).strip()

    if not expected:
        return

    if (
        not x_report_token
        or x_report_token != expected
    ):
        raise HTTPException(
            status_code=401,
            detail="X-Report-Token inválido.",
        )


@app.get("/ping")
def ping():
    return {
        "ok": True,
        "service": "informes-obra-gruesa",
        "version": "1.3.0",
    }


# ============================================================
# INFORME SEMANAL
# ============================================================

@app.post("/informe-semanal")
def informe_semanal(
    payload: InformeRequest,
    x_report_token: str | None = Header(
        default=None,
        alias="X-Report-Token",
    ),
):
    _validate_token(
        x_report_token
    )

    try:
        return generate_and_publish(
            payload.id_informe
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


@app.post(
    "/informe-semanal/preview",
    response_class=Response,
    responses={
        200: {
            "description": "PDF de vista previa",
            "content": {
                "application/pdf": {
                    "schema": {
                        "type": "string",
                        "format": "binary",
                    }
                }
            },
        }
    },
)
def informe_semanal_preview(
    payload: InformeRequest,
    x_report_token: str | None = Header(
        default=None,
        alias="X-Report-Token",
    ),
):
    _validate_token(
        x_report_token
    )

    try:
        pdf_bytes, info = generate_preview(
            payload.id_informe
        )

        headers = {
            "Content-Disposition": (
                f'attachment; filename="'
                f'Informe_Semanal_OG_'
                f'{payload.id_informe}.pdf"'
            ),
            "X-Fotos-Incluidas": str(
                info["fotos_incluidas"]
            ),
            "X-SVG-Incluido": str(
                info["svg_incluido"]
            ).lower(),
        }

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers=headers,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


# ============================================================
# REPORTE FOTOGRÁFICO DIARIO
# ============================================================

@app.post("/reporte-fotografico-diario")
def reporte_fotografico_diario(
    payload: DailyPhotoReportRequest,
    x_report_token: str | None = Header(
        default=None,
        alias="X-Report-Token",
    ),
):
    _validate_token(
        x_report_token
    )

    try:
        return generate_daily_and_publish(
            payload.id_informe_diario
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


@app.post(
    "/reporte-fotografico-diario/preview",
    response_class=Response,
    responses={
        200: {
            "description": (
                "PDF de vista previa del reporte "
                "fotográfico diario"
            ),
            "content": {
                "application/pdf": {
                    "schema": {
                        "type": "string",
                        "format": "binary",
                    }
                }
            },
        }
    },
)
def reporte_fotografico_diario_preview(
    payload: DailyPhotoReportRequest,
    x_report_token: str | None = Header(
        default=None,
        alias="X-Report-Token",
    ),
):
    _validate_token(
        x_report_token
    )

    try:
        pdf_bytes, info = generate_daily_preview(
            payload.id_informe_diario
        )

        headers = {
            "Content-Disposition": (
                f'attachment; filename="'
                f'Reporte_Fotografico_'
                f'{payload.id_informe_diario}.pdf"'
            ),
            "X-Fotos-Incluidas": str(
                info["fotos_incluidas"]
            ),
            "X-Fotos-Encontradas": str(
                info["fotos_encontradas"]
            ),
        }

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers=headers,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc
