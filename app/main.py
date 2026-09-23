from __future__ import annotations

import os

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from .report_service import generate_and_publish, generate_preview


app = FastAPI(
    title="Informe Semanal Obra Gruesa",
    version="1.2.3",
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


def _validate_token(x_report_token: str | None) -> None:
    expected = os.getenv("REPORT_WEBHOOK_TOKEN", "").strip()

    if not expected:
        return

    if not x_report_token or x_report_token != expected:
        raise HTTPException(
            status_code=401,
            detail="X-Report-Token inválido.",
        )


@app.get("/ping")
def ping():
    return {
        "ok": True,
        "service": "informe-semanal-obra-gruesa",
        "version": "1.2.3",
    }


@app.post("/informe-semanal")
def informe_semanal(
    payload: InformeRequest,
    x_report_token: str | None = Header(
        default=None,
        alias="X-Report-Token",
    ),
):
    _validate_token(x_report_token)

    try:
        return generate_and_publish(payload.id_informe)
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
    _validate_token(x_report_token)

    try:
        pdf_bytes, info = generate_preview(payload.id_informe)

        headers = {
            "Content-Disposition": (
                f'attachment; filename="Informe_Semanal_OG_'
                f'{payload.id_informe}.pdf"'
            ),
            "X-Fotos-Incluidas": str(info["fotos_incluidas"]),
            "X-SVG-Incluido": str(info["svg_incluido"]).lower(),
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
