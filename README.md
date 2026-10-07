# Informe Semanal de Obra Gruesa - V1.6.0 (boleta de muestreo QR)

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


## V1.2.3 - legibilidad curva acumulada

Se modifica únicamente la presentación del gráfico
`Curvas acumuladas de hormigón`.

Cambios:
- eje X mensual;
- fechas en formato `dd/mm/aa`;
- etiquetas inclinadas para mejorar lectura;
- título, leyenda y área de curvas quedan en franjas independientes;
- la leyenda se mueve fuera del área de trazado;
- mayor margen superior para evitar que las curvas se superpongan
  a la leyenda;
- se conserva la línea vertical de fecha de corte;
- no cambia ninguna fuente de datos ni cálculo de la V1.2.2.

Después del despliegue:
`GET /ping` debe devolver `version: 1.2.3`.


# V1.2.4 - Escritura de informes vía Apps Script

## Motivo

Una Service Account de Cloud Run puede leer archivos compartidos desde
"Mi unidad", pero no dispone de cuota propia para crear archivos nuevos
allí. V1.2.4 mantiene Cloud Run para generar el PDF y delega únicamente
la escritura final a un Google Apps Script Web App ejecutado como el
usuario propietario.

Flujo:

AppSheet -> Cloud Run -> genera PDF -> Apps Script Web App
-> Mi unidad / INFORMES_SEMANALES -> AppSheet INFORME actualizado.

## Archivos nuevos

- `app/report_writer_client.py`
- `apps_script/INFORME_DRIVE_WRITER_v1_0_0.gs`

## Variables nuevas de Cloud Run

- `REPORT_WRITER_URL`
- `REPORT_WRITER_TOKEN`

`REPORT_APPSHEET_PATH` permanece como `INFORMES_SEMANALES`.

`REPORT_FOLDER_ID` ya no se usa por Cloud Run para crear el PDF.
El ID de la carpeta se configura como Propiedad del script en Apps Script.

## Propiedades del Apps Script

En Configuración del proyecto -> Propiedades del script:

- `REPORT_FOLDER_ID` = ID de la carpeta `INFORMES_SEMANALES`
- `REPORT_WRITER_TOKEN` = mismo valor que `REPORT_WRITER_TOKEN` en Cloud Run

## Despliegue del Apps Script

Implementar -> Nueva implementación -> Aplicación web

- Ejecutar como: Yo
- Quién tiene acceso: Cualquiera

Copiar la URL terminada en `/exec` y configurarla en Cloud Run como
`REPORT_WRITER_URL`.

## Prueba

1. Abrir la URL del Web App en el navegador.
2. Debe responder:
   `{"ok":true,"service":"informe-semanal-drive-writer","version":"1.0.0"}`
3. Desplegar Cloud Run V1.2.4.
4. Verificar `/ping` -> `1.2.4`.
5. Ejecutar `POST /informe-semanal` desde `/docs`.
6. Confirmar:
   - PDF creado en `INFORMES_SEMANALES`
   - `ARCHIVO_INFORME` actualizado
   - `ESTADO_INFORME = EMITIDO`
   - `REGENERAR_INFORME = FALSE`


# V1.2.5 - Proyección de término desde semana 6

La proyección lineal deja de publicarse durante las primeras semanas
de obra gruesa.

Regla:

- Menos de 6 semanas cerradas con `M3 ACUMULADO REAL`:
  - no se calcula ni muestra fecha estimada de término;
  - no se muestran días de adelanto/atraso;
  - el informe indica cuántas semanas válidas existen de las 6 requeridas.

- Desde 6 semanas cerradas con dato real:
  - se utilizan las últimas 6 semanas válidas;
  - se calcula regresión lineal del `M3 ACUMULADO REAL`;
  - se proyecta la fecha en que se alcanzará el objetivo final;
  - se compara contra `Término programado OG`.

El `Término programado OG` y el gráfico de curvas permanecen visibles
desde el inicio; solamente se condiciona la proyección estadística.


# V1.3.0 - Reporte fotográfico diario

Se agrega un segundo PDF independiente del informe semanal.

## Fuente

Tabla:
`REGISTRO_AVANCE_SEMANAL`

Campos:
- `FECHA`
- `PISO`
- `COMENTARIO`
- `IMAGEN`

El piso se resuelve contra:
`PISOS[ID_PISO] -> PISOS[N PISO]`, con `PISOS[PISO]` como fallback.

## Tabla AppSheet

`INFORME_FOTOGRAFICO_DIARIO`

Columnas esperadas:
- `ID_INFORME_DIARIO`
- `FECHA_INFORME`
- `RESPONSABLE`
- `ESTADO`
- `ARCHIVO_INFORME`
- `GENERAR_INFORME`
- `FECHA_EMISION`

## Endpoints

### Preview

POST `/reporte-fotografico-diario/preview`

Body:

```json
{
  "id_informe_diario": "ID_REAL"
}
```

### Publicar

POST `/reporte-fotografico-diario`

Body:

```json
{
  "id_informe_diario": "ID_REAL"
}
```

Al publicar:
- guarda el PDF en la carpeta diaria de Drive;
- actualiza `ARCHIVO_INFORME`;
- `ESTADO = EMITIDO`;
- `GENERAR_INFORME = FALSE`;
- completa `FECHA_EMISION`.

## Apps Script Writer

Reemplazar el código desplegado por:
`apps_script/INFORME_DRIVE_WRITER_v1_1_0.gs`

Agregar en Propiedades del script:

- `DAILY_REPORT_FOLDER_ID`
  = ID de la carpeta `REPORTES_FOTOGRAFICOS_DIARIOS`

Mantener:
- `REPORT_FOLDER_ID`
- `REPORT_WRITER_TOKEN`

Después de editar el Apps Script:
`Implementar -> Administrar implementaciones -> Editar -> Nueva versión -> Implementar`

La URL `/exec` no debería cambiar.

## Cloud Run

Agregar:

`DAILY_REPORT_APPSHEET_PATH=REPORTES_FOTOGRAFICOS_DIARIOS`

No se requiere el ID de la carpeta diaria en Cloud Run;
ese ID queda solamente en Apps Script.

## Bot AppSheet

Acción:
`GENERAR_INFORME = TRUE`

Condición sugerida:

```appsheet
AND(
  ISNOTBLANK([ID_INFORME_DIARIO]),
  ISNOTBLANK([FECHA_INFORME]),
  NOT([GENERAR_INFORME])
)
```

Bot:
- tabla: `INFORME_FOTOGRAFICO_DIARIO`
- evento: Updates
- condición:

```appsheet
[GENERAR_INFORME] = TRUE
```

Webhook:
- POST
- URL:
  `https://informe-obra-gruesa-541351636997.southamerica-west1.run.app/reporte-fotografico-diario`
- Header:
  `X-Report-Token`
- Body:
  `appsheet/BODY_WEBHOOK_REPORTE_FOTOGRAFICO_DIARIO.json`

## Nombre del PDF

`Reporte_Fotografico_YYYY-MM-DD_<ID>.pdf`

El diseño usa 6 fotografías por página (2 columnas x 3 filas)
y agrega automáticamente páginas adicionales cuando hay más registros.

---

# V1.4.0 - Capítulo 05: Ensayos de resistencia del hormigón

Esta versión conserva las cinco secciones existentes y agrega, DESPUÉS del
registro fotográfico, un capítulo acumulado de resistencia con una página
resumen y una sección por cada grado encontrado en `TABLA_RESISTENCIA`.
No se modifican los endpoints, Bots, carpeta de Drive, ni Apps Script Writer.
`GET /ping` devuelve `version: 1.4.0`.

## Lectura de datos

El servicio lee, mediante la API de AppSheet:

- `TABLA_RESISTENCIA` (físicas y virtuales):
  `ID_MUESTRA`, `ID_GUIA`, `ID_CERTIFICADO`, `Grado del Hormigon`,
  `Resistencia_Individual`, `Resis_Media_Movil`, `Resis_Indiv_Minima`,
  `Resis_movil_minima`, `Fecha_Toma_Muestra`, `resistencia_Esperada` y
  `CERTIFICADO_FINAL_28D`.
- `TABLA_CERTIFICADO_HORMIGON`: `ID_CERTIFICADO`, `ID_GUIA`,
  `FECHA_CERTIFICADO`, `R_7_DIAS`, `R_28_DIAS_1`, `R_28_DIAS_2` y
  `FECHA_REGISTRO` (nuevo campo RECOMENDADO, véase abajo).
- `GUIAS`: para mostrar el folio de la guía y la fecha que ya utiliza
  `TABLA_RESISTENCIA[Fecha_Toma_Muestra]`.
- `TABLA_VISITA_TOMA_MUESTRA` (incorporada en V1.4.1): `ID_VISITA`, `ID_GUIA`,
  `PISO`, `ELEMENTO`, `DESCRIPCION_SECTOR` para la ubicación real de la muestra.
- `PISOS`: convierte `TABLA_VISITA_TOMA_MUESTRA[PISO]` (Ref) a `N PISO`.

Se agrupan todas las muestras de fecha <= `INFORME[FECHA_CORTE]` por grado.
Solo un certificado con los TRES resultados (R7, R28-1 y R28-2) es definitivo.
No se grafican muestras pendientes como si tuvieran resultado 0.

### Requisito para cortes históricos exactos

**Agregar una columna física** `FECHA_REGISTRO` a la hoja
`TABLA_CERTIFICADO_HORMIGON` y regenerar estructura de AppSheet:

- Type: `DateTime`
- Initial value: `NOW()`
- App formula: **vacío**
- Editable: OFF
- Show: opcional OFF

Esta es la fecha en que se ingresó el certificado en AppSheet; es diferente a
`FECHA_CERTIFICADO` (fecha que figura en el documento del laboratorio).
Al automatizar OCR, la nueva fila debe conservar el momento real de ingreso.
`VIGENTE` sigue funcionando como hasta ahora; NO se usa para reconstruir el
pasado porque el certificado anterior ya no estará vigente cuando aparezca el
segundo.

Si faltan `FECHA_REGISTRO` en certificados antiguos, se utiliza
`FECHA_CERTIFICADO` como fallback **aproximado** y se imprime una advertencia
visible en el informe; NO se afirma que esos resultados ya estaban cargados al
cierre. Para auditoría estricta, completar la fecha real de ingreso histórico
cuando haya evidencia. Si el certificado no tiene ninguna fecha, se excluye del
corte y se notifica.

La proyección `resistencia_Esperada` actualmente es una VC. Cuando se compara
un informe antiguo con certificados sustituidos y el R7 histórico no coincide
con el actual, se omite la proyección, porque no hay registro persistido de la
estimación calculada en la fecha original.

### Criterios

- Resistencia individual: se usa la VC `Resistencia_Individual` cuando el
  certificado actual coincide con el vigente al corte. En cortes históricos,
  donde difieren, se reconstruye exactamente `(R_28_DIAS_1 + R_28_DIAS_2)/2`
  desde el certificado definitivo disponible al cierre.
- Resistencia media móvil: se valida la VC `Resis_Media_Movil` cuando las tres
  muestras pertenecen a la cohorte definitiva del corte. Cuando no se puede
  reutilizar sin arrastrar datos futuros, se aplica el promedio de las tres
  resistencias individuales consecutivas del MISMO grado, ordenadas por fecha
  y guía. Si la VC difiere en más de 0.02 de la media reconstruida, el informe
  utiliza el cálculo del corte y emite una advertencia.
- Mínimos: `Resis_Indiv_Minima` y `Resis_movil_minima` llegan desde AppSheet.
  Nunca se inventan mínimos. Si faltan, hay gráfico sin clasificación de
  cumplimiento y una advertencia visible.
- Proyección 7D: muestra solamente casos aún sin certificado definitivo cuya
  `resistencia_Esperada` es menor al mínimo individual. Se presenta como
  ALERTA INFORMATIVA; nunca se incorpora a la serie definitiva o media móvil.
- Pendiente vencida: sin resultados 28D al cumplir 28 días desde la toma.

### Salida y paginación

- Capítulo 05, resumen global y tabla por grado.
- Una página por grado cuando su contenido cabe en A4; si hay muchas
  incidencias, WeasyPrint continúa automáticamente en páginas adicionales.
- Cada grado incluye KPIs, tabla de alertas de proyección 7D,
  gráfico de resistencia individual y tabla con muestras bajo el mínimo,
  gráfico de media móvil de tres muestras y tabla con ventanas bajo el mínimo,
  y tabla de resultados definitivos vencidos.
- No se han modificado los diseños de los cinco capítulos anteriores.

## Antes de la publicación real

1. Confirmar en una respuesta real de la API de AppSheet que las VC nombradas
   arriba se devuelven con sus valores calculados. Si no aparecen, revisar
   tabla/slice/seguridad de AppSheet antes de afirmar cumplimiento.
2. Agregar `FECHA_REGISTRO` para que los cortes históricos sean fiables.
3. Confirmar el nombre exacto del campo de piso y la ubicación real de la
   muestra; hoy el código busca distintas alternativas y muestra `—` si
   ninguno existe. NO se presume que el piso de la guía sea necesariamente el
   de la muestra sin corroborarlo.
4. Verificar la UNIDAD reportada por el laboratorio (el gráfico dice
   `Resistencia (unidad del ensayo)` hasta esa confirmación).
5. En `/informe-semanal/preview`, revisar una guía con solo R7, otra con
   certificado final y una situación individual / media móvil bajo mínimo.
6. Una vez aprobada la vista previa, publicar con el Bot vigente.

## Pruebas locales sin credenciales

`python -m unittest discover -s tests -v`

`python -m tests.build_preview`

La segunda genera un PDF **DEMOSTRATIVO CON VALORES INVENTADOS** dentro de la
carpeta del proyecto; nunca usarlo como informe de obra real.


# V1.4.1 - Ubicación real de las muestras desde la visita

Fuente confirmada de ubicación: `TABLA_VISITA_TOMA_MUESTRA`,
relacionada por `TABLA_RESISTENCIA[ID_VISITA]` a `[ID_VISITA]` de visita.
En las tablas de resistencia individuales, proyección 7D y certificados vencidos:

- `PISO` proviene de `TABLA_VISITA_TOMA_MUESTRA[PISO]`, Ref resuelto con `PISOS[N PISO]`.
- Ubicación combina `ELEMENTO` y `DESCRIPCION_SECTOR` de la visita.
- Si falta el vínculo `ID_VISITA`, usa `ID_GUIA` solo cuando es una visita única;
  si hay duplicados o referencias inconsistentes, genera advertencias.
- `Fecha_Toma_Muestra` continúa siendo la fecha de control y NO se sustituye
  automáticamente por `FECHA_VISITA`.
- Los datos de ubicación de una visita agregada después de un cierre son
  metadatos de ubicación actuales, no una reconstrucción histórica versionada.

**Pendiente de configuración**: `ELEMENTO` es Ref. Sin conocer su tabla origen
y columna Label, puede aparecer la clave interna en el PDF. Para mostrar el
nombre legible, confirmar ambos y agregar el mapa de desreferencia.

`GET /ping` versión 1.4.1. Sin cambios de webhook, Writer ni variables.


## V1.4.2 - Resolución de etiquetas en el capítulo de resistencia

Se consulta también `ELEMENTOS`; para cada fila de `TABLA_RESISTENCIA`,
`ID_VISITA` se relaciona con `TABLA_VISITA_TOMA_MUESTRA`, donde
`ELEMENTO` (Ref) se traduce desde `ELEMENTOS[ID_ELEMENTOS]` a `ELEMENTOS[ELEMENTO]`.
Para este capítulo `PISO` se traduce desde `PISOS[ID_PISO]` a `PISOS[PISO]`.
`DESCRIPCION_SECTOR` conserva su texto original. Los pies de las fotos siguen
mostrando `PISOS[N PISO]` como antes.

No se alteran las cinco páginas existentes, el endpoint ni el flujo Drive Writer.
Consultar `NOTAS_ENTREGA_V1_4_2.txt` para despliegue.


## V1.4.3 - Gráfico de alzaprimado respetando FECHA_CORTE

**Problema corregido:** Cloud Run tomaba la última fila `VISTA_ALZAPRIMADO[SVG_URI]`
sin verificar su fecha. Por eso el informe con cierre 20/09/2026 mostraba un SVG
actualizado el 25/09/2026: un estado posterior al periodo informado.

**Diseño de la corrección:**

1. Apps Script `VISTA_ALZAPRIMADO_v5_8_3_HISTORIAL_SVG.gs` deja de eliminar
   los SVG anteriores. Cada actualización genera un archivo nuevo dentro
   de la MISMA carpeta `SVG_Alzaprimado`; los nombres incluyen milisegundos
   para evitar colisiones (`ALZAPRIMADO_<ID_VISTA>_yyyyMMdd_HHmmss_SSS.svg`).
2. Cloud Run consulta Drive por `ID_VISTA` y selecciona el último archivo
   que efectivamente se creó antes del final de `FECHA_CORTE` según
   `REPORT_TIMEZONE` (por defecto `America/Santiago`).
3. El PDF muestra la fecha **real de captura del archivo** bajo el SVG.
   Puede ser anterior al cierre de semana; no se presenta como si
   documentara sucesos posteriores a dicha captura.
4. Si no existe ninguna instantánea anterior o igual a `FECHA_CORTE`,
   **NO muestra el SVG actual**. Muestra un recuadro explicativo y emite
   una advertencia en la respuesta del endpoint.

### Instalación obligatoria de las dos piezas

**PRIMERO: Apps Script de alzaprimado, NO el Drive Writer del PDF**

- Abrir el proyecto Apps Script que genera `VISTA_ALZAPRIMADO[SVG_URI]`.
- REEMPLAZAR TODO el contenido del archivo de alzaprimado que usa
  `actualizarVistaAlzaprimas()` por el archivo completo
  `apps_script/VISTA_ALZAPRIMADO_v5_8_3_HISTORIAL_SVG.gs`.
- No añadirlo como segundo archivo junto al script anterior: contiene la
  misma constante y las mismas funciones globales.
- Verificar zona horaria `America/Santiago` en la configuración del proyecto.
- Ejecutar `actualizarVistaAlzaprimas()` una vez y comprobar que `SVG_URI`
  continúa mostrando el SVG activo como antes.
- Opcional recomendado: ejecutar **una sola vez**
  `instalarSnapshotDiarioAlzaprimas()` para programar una captura diaria
  alrededor de las 23:30 (Chile), aunque no haya cambios de estado.
- No renombrar ni mover SVG históricos de la carpeta.

**DESPUÉS: GitHub / Cloud Run**

- Reemplazar el código de `main` con el paquete completo V1.4.3.
- Conservar las variables actuales, especialmente `SVG_FOLDER_ID`,
  que ahora debe permitir LISTAR y LEER archivos para la Service Account.
- `REPORT_TIMEZONE=America/Santiago` es opcional (ya es el valor predeterminado).
- `GET /ping` debe responder `version: 1.4.3`.
- Generar `/informe-semanal/preview` y comprobar bajo el SVG su fecha real.
- No cambian webhooks, Bots de AppSheet ni el Drive Writer.

**Limitación importante:** los SVG que la versión anterior eliminó NO se
pueden reconstruir a partir del archivo activo. Un informe de fecha pasada
sin archivo capturado antes de esa fecha mostrará el aviso de falta de
instantánea. Este cambio protege todos los futuros cierres, pero no
inventa historial retroactivo.

**Alcance:** se historiza el DIAGRAMA SVG, no los KPI de la parte superior
que `INFORME` entrega actualmente. Para tener una página 3 completamente
congelada al cierre semanal también habrá que archivar esos contadores.

Pruebas: `python -m unittest discover -s tests -v` (selección histórica,
fecha local de Chile, sin fallback a estados posteriores, descarga por ID,
resistencia y ubicaciones).

## V1.5.1 - Pedidos de fierro

Se incorpora procesamiento automático de las planillas `.xls` / `.xlsx`
cargadas en `PEDIDOS_FIERRO[ARCHIVO_PEDIDO]`.

Nuevo endpoint:

`POST /pedido-fierro`

Body:

```json
{
  "id_pedido_fierro": "ID_REAL"
}
```

Seguridad: utiliza el mismo header `X-Report-Token` y la misma variable
`REPORT_WEBHOOK_TOKEN` del informe semanal.

El servicio extrae:

- número de pedido;
- área;
- fecha de pedido;
- fecha requerida en obra;
- hora requerida;
- diámetro;
- largo;
- kg/mt;
- barras solicitadas;
- kg solicitados.

Las líneas se escriben en `PEDIDOS_FIERRO_DETALLE`. Si el mismo pedido se
reprocesa, primero se elimina su detalle anterior para evitar duplicados.

### Importante: HORA_REQUERIDA

Debe ser `Text`, no `Time`. Las planillas reales incluyen valores como `AM`,
`10 y 12 am` y también horas reales como `09:00`.

### Variable Drive recomendada

```text
FIERRO_PEDIDOS_FOLDER_ID=<ID_DE_LA_CARPETA>
```

La Service Account de Cloud Run debe tener acceso de lectura a esa carpeta.
Si la variable se deja vacía, se intenta resolver `ARCHIVO_PEDIDO` como ruta
relativa desde `APP_ROOT_FOLDER_ID`.

Después del despliegue, `GET /ping` debe devolver `version: 1.5.1`.

# V1.6.0 - Boleta de muestreo desde QR

Nuevo endpoint:

`POST /procesar-boleta-muestreo`

Body:

```json
{
  "id_visita": "<<[ID_VISITA]>>"
}
```

Header:

`X-Report-Token` con el mismo valor de `REPORT_WEBHOOK_TOKEN`.

Flujo:

1. Lee `TABLA_VISITA_TOMA_MUESTRA[URL_QR_MUESTREO]`.
2. Descarga el PDF indicado por el QR.
3. Extrae texto nativo con `pypdf` (sin OCR en esta versión).
4. Obtiene `MUESTRA N°` y `GUIA N°`.
5. Archiva una copia del PDF mediante Apps Script Drive Writer.
6. Busca la guía por `GUIAS[FOLIO]` y escribe su `ID_REGISTRO` en `ID_GUIA`.
7. Completa `ARCHIVO_BOLETA_MUESTREO`, `N_MUESTRA_LAB` y estado.

Columnas requeridas en `TABLA_VISITA_TOMA_MUESTRA`:

- `URL_QR_MUESTREO`
- `ARCHIVO_BOLETA_MUESTREO`
- `N_MUESTRA_LAB`
- `ESTADO_PROCESAMIENTO_BOLETA`
- `OBSERVACION_PROCESAMIENTO_BOLETA`
- `ID_GUIA`

Estados usados:

- `PENDIENTE`
- `PROCESANDO`
- `PROCESADO`
- `ERROR`

## Apps Script Writer V1.2.0

Reemplazar el script anterior por:

`apps_script/INFORME_DRIVE_WRITER_v1_2_0_MUESTREO.gs`

Agregar Propiedad del script:

`SAMPLE_TICKET_FOLDER_ID=<ID carpeta Drive donde se archivarán las boletas>`

Conservar las propiedades existentes:

- `REPORT_WRITER_TOKEN`
- `REPORT_FOLDER_ID`
- `DAILY_REPORT_FOLDER_ID`

## Variables Cloud Run V1.6.0

```text
SAMPLE_TICKET_APPSHEET_PATH=MUESTRAS_HORMIGON/BOLETAS_MUESTREO
SAMPLE_TICKET_MAX_BYTES=20971520
SAMPLE_VISITS_TABLE=TABLA_VISITA_TOMA_MUESTRA
SAMPLE_GUIDES_TABLE=GUIAS
SAMPLE_VISIT_KEY=ID_VISITA
SAMPLE_GUIDE_KEY=ID_REGISTRO
SAMPLE_GUIDE_FOLIO_COLUMN=FOLIO
```

`SAMPLE_TICKET_APPSHEET_PATH` debe ser la ruta relativa que AppSheet pueda abrir desde la columna File. El ID físico de la carpeta se configura en Apps Script, no en Cloud Run.
