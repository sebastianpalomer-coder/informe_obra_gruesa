from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from .report_service import generate_pdf

app = FastAPI(
    title="Informe Semanal Obra Gruesa",
    version="0.2.0",
)


class InformeRequest(BaseModel):
    id_informe: str = Field(min_length=1)
    datos: dict[str, Any]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id_informe": "DEMO001",
                "datos": {
                    "NOMBRE_OBRA": "HOTEL BELLET",
                    "FECHA_INICIO_SEMANA": "2026-09-14",
                    "FECHA_TERMINO_SEMANA": "2026-09-20",
                    "FECHA_INICIO_OBRA": "2026-02-01",
                    "FECHA_TERMINO_OBRA": "2027-04-30",
                    "PLAZO_OBRA": 453,
                    "%_PLAZO_TRANSCURRIDO": 0.51,
                    "RESPONSABLE_INFORME": "Administrador de Obra",
                    "FECHA_CORTE": "2026-09-18",
                    "BITACORA_SEMANAL": "Semana de prueba del informe ejecutivo.",
                    "HITOS_SEMANA": "Hormigonado de losa del nivel en curso.",
                    "RESTRICCIONES_SEMANA": "Sin restricciones críticas.",
                    "ACCIONES_PROXIMA_SEMANA": "Continuar secuencia programada.",
                    "M3_PROGRAMADOS_SEMANA": 43.2,
                    "M3_REALES_SEMANA": 37.4,
                    "M3_GEOMETRICOS_SEMANA": 36.8,
                    "CUMPLIMIENTO_SEMANA": 0.8657,
                    "BRECHA_M3_SEMANA": -5.8,
                    "%_PERDIDA_SEM": 0.016,
                    "M3_PROGRAMADOS_SEM_ANT": 38,
                    "M3_REALES_SEM_ANT": 39,
                    "M3_GEOMETRICOS_SEM_ANT": 38.1,
                    "CUMPLIMIENTO_SEM_ANT": 1.026,
                    "%_PERDIDA_SEM_ANT": 0.023,
                    "M3_PROGRAMADOS_2SEM": 41,
                    "M3_REALES_2SEM": 38,
                    "M3_GEOMETRICOS_2SEM": 37.4,
                    "CUMPLIMIENTO_2SEM": 0.927,
                    "%_PERDIDA_2SEM": 0.016,
                    "M3_PROGRAMA_ACUM": 220.5,
                    "M3_REAL_ACUM": 210.4,
                    "BRECHA_M3_ACUM": -10.1,
                    "M3_PROX_2_SEM": 66.4,
                    "ESTADO_CURVA": "ATRASADO",
                    "GUIAS_SEMANA": 18,
                    "M3_GUIAS_SEMANA": 137.5,
                    "PORC_GUIAS_VALIDADAS": 0.94,
                    "PORC_GUIAS_CON_TED": 1.0,
                    "FACTURAS_SEMANA": 4,
                    "NETO_FACTURADO_SEMANA": 8420000,
                    "GUIAS_PENDIENTES_FACTURA_SEMANA": 3,
                    "M3_PENDIENTES_FACTURA_SEMANA": 21,
                    "M3_OC_HORMIGON": 1250,
                    "M3_CONSUMIDOS_OC": 820,
                    "M3_SALDO_OC": 430,
                    "PORC_CONSUMO_OC_HORMIGON": 0.656,
                    "UF_POR_FACTURAR_OC": 38.4,
                    "TOTAL_PANOS": 50,
                    "PANOS_HORMIGONADOS": 24,
                    "PANOS_HORMIGONADOS_SEMANA": 4,
                    "DESCIMBRES_SEMANA": 3,
                    "CNT_FAENA_ACTUAL": 4,
                    "CNT_100_ALZAPRIMAS": 8,
                    "CNT_50_ALZAPRIMAS": 6,
                    "CNT_DISP_DESCIMBRE": 3,
                    "CNT_DESCIMBRADA": 3,
                    "CNT_SIN_HORMIGONAR": 26,
                    "PORC_FAENA_ACTUAL": 0.08,
                    "PORC_100_ALZAPRIMAS": 0.16,
                    "PORC_50_ALZAPRIMAS": 0.12,
                    "PORC_DISP_DESCIMBRE": 0.06,
                    "PORC_DESCIMBRADA": 0.06,
                    "PORC_SIN_HORMIGONAR": 0.52,
                    "PISO_ULTIMA_LOSA": 7,
                    "ULTIMA_LOSA_HORMIGONADA": "2026-09-17",
                    "FOTOS_SEMANA": 14,
                    "PISOS_CON_REGISTRO": 2,
                    "ULTIMA_FOTO_FECHA": "2026-09-18"
                }
            }
        }
    )


@app.get("/ping")
def ping():
    return {
        "ok": True,
        "service": "informe-semanal-obra-gruesa",
        "version": "0.2.0",
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
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc
