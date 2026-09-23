# Informe Semanal de Obra Gruesa - V1.2.1

## Cambios V1.2.1

La V1.2.1 reorganiza el informe con una lectura ejecutiva acumulada primero y el detalle semanal después.

### Página 1 - Resumen ejecutivo acumulado
Fuente principal: `SEMANAS_OBRA_GRUESA`.

Usa la fila correspondiente a `INFORME[ID_SEMANA_OBRA_GRUE]` y lee:

- `M3 ACUMULADO INFERIOR`
- `M3 ACUMULADO SUPERIOR`
- `M3 ACUMULADO REAL`

Calcula:

- brecha real vs banda inferior;
- brecha real vs banda superior;
- cumplimiento real / banda inferior;
- cumplimiento real / banda superior;
- estado general:
  - REAL < INFERIOR -> ATRASADO
  - INFERIOR <= REAL <= SUPERIOR -> EN RANGO
  - REAL > SUPERIOR -> ADELANTADO
- plazo transcurrido desde las fechas reales de obra;
- proyección lineal de término de obra gruesa usando las últimas 3 semanas disponibles;
- días de adelanto o atraso contra el término programado de obra gruesa.

El gráfico de curvas usa toda `SEMANAS_OBRA_GRUESA`: banda inferior, banda superior y real acumulado.

### Página 2 - Producción semanal

Muestra:

- m³ proyectados;
- m³ reales;
- m³ geométricos;
- % cumplimiento;
- % pérdida.

Incluye 5 gráficos pequeños de tendencia de las últimas 3 semanas y tabla diaria de guías/m³ de lunes a sábado.

Si `%_PERDIDA_*` viene vacío, el backend lo calcula como:

`(M3 real - M3 geométrico) / M3 real`

### Página 3 - Alzaprimado

Mantiene el módulo y SVG actual.

### Página 4 - Facturación de hormigón

Consulta directamente `FACTURAS` hasta `INFORME[FECHA_CORTE]` y calcula:

- cantidad de facturas del mes;
- neto facturado del mes;
- total facturado del mes;
- total facturado acumulado;
- m³ facturados acumulados;
- UF pendientes de facturación;
- resumen de orden de compra.

Campos FACTURAS utilizados:

- `FECHA_EMISION`
- `NETO_FACTURA`
- `IVA_FACTURA`
- `TOTAL_FACTURA`

### Página 5 - Registro fotográfico

`REGISTRO_AVANCE_SEMANAL[PISO]` es un Ref a `PISOS[ID_PISO]`.
La V1.2.1 resuelve el Ref y muestra `PISOS[N PISO]` en el pie de foto.

### Corrección de fechas

La API AppSheet de esta app usa `Locale=en-US`. La V1.2.1 interpreta primero `MM/DD/YYYY` y siempre imprime el PDF en `DD/MM/YYYY`.

Ejemplos:

- API `09/01/2026` -> PDF `01/09/2026`
- API `09/11/2026` -> PDF `11/09/2026`

## Tablas que consulta el backend

- `INFORME`
- `OBRA`
- `SEMANAS_OBRA_GRUESA`
- `VISTA_ALZAPRIMADO`
- `REGISTRO_AVANCE_SEMANAL`
- `PISOS`
- `FACTURAS`

## Variables Cloud Run

Se mantienen las existentes:

- `APPSHEET_APP_ID`
- `APPSHEET_ACCESS_KEY`
- `APPSHEET_DOMAIN=www.appsheet.com`
- `APPSHEET_LOCALE=en-US`
- `APPSHEET_TIMEZONE=Pacific SA Standard Time`
- `PHOTO_FOLDER_ID`
- `SVG_FOLDER_ID`
- `REPORT_FOLDER_ID`
- `REPORT_APPSHEET_PATH=INFORMES_SEMANALES`
- `REPORT_WEBHOOK_TOKEN`
- `MAX_REPORT_PHOTOS=6`

No se requiere ninguna variable nueva para V1.2.1.

## Deploy

Subir todo el contenido del ZIP a la raíz del repositorio, reemplazando los archivos anteriores.

Después del despliegue:

`GET /ping`

debe responder:

```json
{
  "ok": true,
  "service": "informe-semanal-obra-gruesa",
  "version": "1.2.0"
}
```

Probar primero:

`POST /informe-semanal/preview`

Antes de activar/generar el PDF definitivo.


## Corrección V1.2.1 - producción semanal

La página de producción semanal ya no utiliza los valores virtuales
`M3_PROGRAMADOS_SEMANA`, `M3_REALES_SEMANA`, `M3_GEOMETRICOS_SEMANA`,
`GUIAS_LUN...SAB` ni `M3_LUN...SAB` de la fila `INFORME`.

Ahora Cloud Run calcula en tiempo real:

- M³ proyectados: `DETALLE_PROGRAMA[M3_PROGRAMADOS]`
- M³ geométricos: `DETALLE_PROGRAMA[M3_GEOMETRICO]`
- M³ reales: `GUIAS[CANTIDAD]`
- % cumplimiento: `M3 reales / M3 proyectados`
- % pérdida: `(M3 reales - M3 geométricos) / M3 reales`
- Guías diarias: `GUIAS[FECHA_EMISION]`
- Total tabla: suma exacta de las filas diarias mostradas

Todos los registros se filtran por el `ID_SEMANA_OBRA_GRUE` de
`SEMANAS_OBRA_GRUESA` correspondiente al informe.

Las tendencias de las últimas 3 semanas también se recalculan desde
`DETALLE_PROGRAMA` y `GUIAS`, evitando valores antiguos almacenados en
columnas virtuales de `INFORME`.

Si existe una guía vinculada a la semana pero su fecha no corresponde
a lunes-sábado, se agrega una fila `Otros / sin fecha` para que el total
siempre sea auditable y coincida con las filas visibles.


## V1.2.2 - PROGRAMA_SEMANAL como fuente semanal

La fuente oficial para los cinco KPI de producción semanal y para los cinco
minigráficos de las últimas tres semanas pasa a ser `PROGRAMA_SEMANAL`.

Columnas utilizadas:

- `ID_SEMANA_OBRA_GRUE`
- `M3 PROGRAMADOS`
- `M3 REALES`
- `M3 GEOMETRICOS`
- `% CUMPLIMIENTO SEMANAL`
- `% PERDIDA SEMANAL`

Los gráficos toman la semana del informe y las dos semanas anteriores,
relacionadas por `ID_SEMANA_OBRA_GRUE`.

La tabla diaria se mantiene independiente y se calcula directamente desde
`GUIAS`, porque su objetivo es auditar cantidad de guías y m³ por día.

No se mezclan fuentes: los minigráficos ya no se reconstruyen desde
`DETALLE_PROGRAMA` ni desde las guías.
