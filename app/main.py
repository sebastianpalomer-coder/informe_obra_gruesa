from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .report_service import generate_pdf

app = FastAPI(
    title="Informe Semanal Obra Gruesa",
    version="0.1.0",
)


class InformeRequest(BaseModel):
    id_informe: str = Field(min_length=1)
    datos: dict[str, Any]


@app.get("/ping")
def ping():
    return {
        "ok": True,
        "service": "informe-semanal-obra-gruesa",
        "version": "0.1.0",
    }


@app.post("/informe-semanal")
def informe_semanal(payload: InformeRequest):
    try:
        pdf_path = generate_pdf(
            id_informe=payload.id_informe,
            data=payload.datos,
        )
        return FileResponse(
            path=str(pdf_path),
            media_type="application/pdf",
            filename=pdf_path.name,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
