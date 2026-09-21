\
# Informe Semanal de Obra Gruesa - V1.0 Operativa

Esta versión conecta AppSheet -> Cloud Run -> AppSheet/Drive.

## Flujo

1. El usuario completa una fila de `INFORME`.
2. Acción AppSheet: `Generar informe`.
3. La acción deja `REGENERAR_INFORME = TRUE`.
4. Bot de AppSheet detecta el cambio y llama:
   `POST /informe-semanal`
5. El webhook envía solamente:
   `{"id_informe":"<<[ID_INFORME]>>"}`
6. Cloud Run consulta la tabla `INFORME` por API.
   AppSheet devuelve también las columnas virtuales.
7. El backend consulta:
   - `OBRA`
   - `VISTA_ALZAPRIMADO`
   - `REGISTRO_AVANCE_SEMANAL`
8. Descarga desde Google Drive:
   - el SVG actual de alzaprimado
   - fotografías con `INCLUIR_INFORME = TRUE`
9. Genera el PDF.
10. Guarda/reemplaza el PDF en:
    `INFORMES_SEMANALES/Informe_Semanal_OG_<ID_INFORME>.pdf`
11. Actualiza `INFORME`:
    - `ARCHIVO_INFORME`
    - `FECHA_EMISION`
    - `ESTADO_INFORME = EMITIDO`
    - `REGENERAR_INFORME = FALSE`

## Endpoints

### GET /ping
Debe devolver `version: 1.0.0`.

### POST /informe-semanal
Operativo: genera, sube a Drive y actualiza AppSheet.

Body:
```json
{
  "id_informe": "ID_REAL"
}
```

### POST /informe-semanal/preview
Genera el PDF con datos reales y lo devuelve al navegador,
pero no lo sube ni cambia `ARCHIVO_INFORME`.

## Variables de entorno Cloud Run

Obligatorias:

- `APPSHEET_APP_ID`
- `APPSHEET_ACCESS_KEY`
- `APP_ROOT_FOLDER_ID`

Recomendado:

- `REPORT_WEBHOOK_TOKEN`

Opcionales:

- `APPSHEET_DOMAIN=www.appsheet.com`
- `APPSHEET_LOCALE=en-US`
- `APPSHEET_TIMEZONE=Pacific SA Standard Time`
- `REPORT_FOLDER_NAME=INFORMES_SEMANALES`
- `MAX_REPORT_PHOTOS=6`

## Google Drive

El servicio usa Application Default Credentials del Service Account de Cloud Run.

1. Habilitar `Google Drive API` en el proyecto.
2. Identificar el Service Account utilizado por el servicio Cloud Run.
3. Compartir con ese correo, como **Editor**, la carpeta raíz donde está
   el Google Sheet de la aplicación y las carpetas de imágenes.
4. Copiar el ID de esa carpeta a `APP_ROOT_FOLDER_ID`.

El SVG de alzaprimado actualmente se genera en la misma carpeta
que el Google Sheet, por lo que el backend puede encontrarlo por `SVG_URI`.

Los archivos de `REGISTRO_AVANCE_SEMANAL[IMAGEN]` se resuelven
como rutas relativas desde la misma carpeta raíz.

## AppSheet

### Acción `Generar informe`

Tabla: `INFORME`

Tipo:
`Data: set the values of some columns in this row`

Valor:

`REGENERAR_INFORME = TRUE`

Condición sugerida:

```appsheet
AND(
  ISNOTBLANK([ID_INFORME]),
  ISNOTBLANK([BITACORA_SEMANAL]),
  NOT([REGENERAR_INFORME])
)
```

### Bot

Evento:
- Tabla: `INFORME`
- Updates
- Condition:

```appsheet
[REGENERAR_INFORME] = TRUE
```

Task:
`Call a webhook`

URL:
`https://TU-SERVICIO.run.app/informe-semanal`

HTTP Verb:
`POST`

Content Type:
`JSON`

Body:
usar `appsheet/BODY_WEBHOOK_GENERAR_INFORME.json`

Header:

`X-Report-Token: <mismo valor de REPORT_WEBHOOK_TOKEN>`

## Prueba antes de activar el Bot

Abrir `/docs`.

Probar primero:
`POST /informe-semanal/preview`

Body:
```json
{
  "id_informe": "ID_REAL_DE_INFORME"
}
```

Si se configuró `REPORT_WEBHOOK_TOKEN`, completar también
el header `X-Report-Token`.

Confirmar:
- datos reales
- SVG
- fotografías elegidas

Después probar:
`POST /informe-semanal`

y verificar que `ARCHIVO_INFORME` quede lleno en AppSheet.

## Nota sobre AppSheet API

La arquitectura usa `Find` para leer la fila de `INFORME`.
Esto permite que el backend reciba también las columnas virtuales
calculadas por AppSheet, evitando replicar todos los cálculos en Python.
