# Informe Semanal de Obra Gruesa · v0.1

Servicio FastAPI para generar el informe ejecutivo semanal de obra gruesa de ALTIUS.

## Arquitectura inicial

AppSheet llama `POST /informe-semanal` y envía:

```json
{
  "id_informe": "ABC123",
  "datos": {
    "NOMBRE_OBRA": "...",
    "BITACORA_SEMANAL": "...",
    "M3_PROGRAMADOS_SEMANA": 43.2
  }
}
```

La idea de esta V0.1 es **usar las columnas virtuales ya calculadas en AppSheet como snapshot del informe**.
Esto evita intentar leerlas desde Google Sheets, porque las virtual columns no existen físicamente en la hoja.

En siguientes versiones el servicio además leerá directamente:
- `DETALLE_PROGRAMA`
- `CURVA_HORMIGON`
- `REGISTRO_AVANCE_SEMANAL`
- `VISTA_ALZAPRIMADO`
- nuevas tablas de ensayos, fierro y avance económico

para construir gráficos y anexos más completos.

## Endpoints

### `GET /ping`

Respuesta de salud del servicio.

### `POST /informe-semanal`

Genera un PDF y lo devuelve directamente.

## Ejecutar localmente

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

En Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Luego:

```bash
curl -X POST http://127.0.0.1:8000/informe-semanal ^
  -H "Content-Type: application/json" ^
  --data-binary @sample_payload.json ^
  --output informe_demo.pdf
```

## Docker

```bash
docker build -t informe-og .
docker run --rm -p 8080:8080 informe-og
```

## Cloud Run

El `Dockerfile` ya está preparado para Cloud Run.

En la siguiente fase se incorporará:
1. subida automática del PDF a Drive;
2. escritura de `ARCHIVO_INFORME`;
3. SVG de alzaprimado;
4. fotografías seleccionadas desde `REGISTRO_AVANCE_SEMANAL`;
5. gráficos históricos;
6. secciones futuras de ensayos, fierro y avance económico.
