
/*
 * ============================================================
 * VISTA ALZAPRIMADO v5.8.3 - HISTORIAL INMUTABLE DE SVG
 * ============================================================
 *
 * Cambios principales v5.6:
 * - Elimina el "regrueso" lateral de cada paño.
 * - Solo dibuja espesor en el FRENTE EXTERIOR de cada nivel.
 * - Ejes numéricos: una sola vez, arriba, con líneas punteadas
 *   verticales que atraviesan el tramo visible.
 * - Ejes alfabéticos: una sola vez en el nivel superior, con
 *   líneas punteadas sobre la planta.
 * - Sin círculos de ejes.
 * - Perspectiva más frontal / limpia.
 *
 * Hojas:
 * - VISTA_ALZAPRIMADO
 * - GRILLA_LOSAS
 * - GUIA_PANO
 * - CONTROL_ALZAPRIMADO
 * - Ejes_Numericos
 * - Ejes_alfabeto
 *
 * ============================================================
 */

const CONFIG_VISTA_ALZ = {

  /*
   * Carpeta dedicada para los SVG de alzaprimado.
   * El Service Account de Cloud Run puede recibir permiso
   * solamente sobre esta carpeta.
   */
  SVG_FOLDER_ID: "1kR2qPov-y262lcpGPyCfqTMjPVpg1lqP",

  /*
   * Ruta que se escribirá en VISTA_ALZAPRIMADO[SVG_URI].
   * La carpeta SVG_Alzaprimado está directamente bajo Mi unidad.
   */
  SVG_FOLDER_NAME: "SVG_Alzaprimado",

  HOJA_VISTA: ["VISTA_ALZAPRIMADO"],
  HOJA_GRILLA: ["GRILLA_LOSAS"],
  HOJA_GUIA_PANO: ["GUIA_PANO"],
  HOJA_CONTROL: ["CONTROL_ALZAPRIMADO"],
  HOJA_EJES_NUM: ["Ejes_Numericos", "EJES_NUMERICOS", "Ejes Numericos"],
  HOJA_EJES_ALF: [
    "Ejes_alfabeto",
    "Ejes_Alfabeticos",
    "EJES_ALFABETICOS",
    "Ejes Alfabeticos"
  ]
};


/*
 * ============================================================
 * FUNCIÓN PRINCIPAL
 * ============================================================
 */

function actualizarVistaAlzaprimas() {

  const ss = SpreadsheetApp.getActiveSpreadsheet();

  const shVista   = vaBuscarHoja_(ss, CONFIG_VISTA_ALZ.HOJA_VISTA);
  const shGrilla  = vaBuscarHoja_(ss, CONFIG_VISTA_ALZ.HOJA_GRILLA);
  const shGuiaPan = vaBuscarHoja_(ss, CONFIG_VISTA_ALZ.HOJA_GUIA_PANO);
  const shControl = vaBuscarHoja_(ss, CONFIG_VISTA_ALZ.HOJA_CONTROL);
  const shEjesNum = vaBuscarHoja_(ss, CONFIG_VISTA_ALZ.HOJA_EJES_NUM);
  const shEjesAlf = vaBuscarHoja_(ss, CONFIG_VISTA_ALZ.HOJA_EJES_ALF);

  const faltantes = [];

  if (!shVista)   faltantes.push(CONFIG_VISTA_ALZ.HOJA_VISTA.join(" / "));
  if (!shGrilla)  faltantes.push(CONFIG_VISTA_ALZ.HOJA_GRILLA.join(" / "));
  if (!shGuiaPan) faltantes.push(CONFIG_VISTA_ALZ.HOJA_GUIA_PANO.join(" / "));
  if (!shControl) faltantes.push(CONFIG_VISTA_ALZ.HOJA_CONTROL.join(" / "));
  if (!shEjesNum) faltantes.push(CONFIG_VISTA_ALZ.HOJA_EJES_NUM.join(" / "));
  if (!shEjesAlf) faltantes.push(CONFIG_VISTA_ALZ.HOJA_EJES_ALF.join(" / "));

  if (faltantes.length > 0) {
    throw new Error(
      "No se encontraron estas hojas: " +
      faltantes.join(", ") +
      ". Hojas existentes: " +
      ss.getSheets().map(h => h.getName()).join(", ")
    );
  }

  const vistas    = vaSheetToObjects_(shVista);
  const grilla    = vaSheetToObjects_(shGrilla);
  const guiaPanos = vaSheetToObjects_(shGuiaPan);
  const control   = vaSheetToObjects_(shControl);
  const ejesNum   = vaSheetToObjects_(shEjesNum);
  const ejesAlf   = vaSheetToObjects_(shEjesAlf);

  if (vistas.length === 0) {
    throw new Error("VISTA_ALZAPRIMADO no tiene registros.");
  }

  const vista = vistas[0];

  const idVista = String(vista.ID_VISTA || "").trim();

  if (!idVista) {
    throw new Error(
      "La primera fila de VISTA_ALZAPRIMADO no tiene ID_VISTA."
    );
  }

  const nivelDesde  = vaToNum_(vista.NIVEL_DESDE, 4);
  const cantNiveles = vaToNum_(vista.CANT_NIVELES, 5);
  const nivelHasta  = nivelDesde + cantNiveles - 1;

  if (cantNiveles < 1) {
    throw new Error("CANT_NIVELES debe ser mayor que 0.");
  }

  /*
   * ----------------------------------------------------------
   * CONFIGURACIÓN GRÁFICA
   * ----------------------------------------------------------
   */

  const W = 1700;
  const H = 980;

  const cfg = {

    width: W,
    height: H,

    nivelDesde: nivelDesde,
    nivelHasta: nivelHasta,

    // Planta
    originX: 150,
    originY: 830,

    // Vista más frontal / menos deformada
    scaleX: 0.235,
    perspectiveX: 0.075,
    perspectiveY: 0.052,

    // Separación vertical
    levelGap: 150,

    // Espesor SOLO en borde frontal exterior
    slabThickness: 10,

    // Diseño
    bg: "#F7F9FC",
    frame: "#D3DDE8",
    titleBg: "#274C77",
    titleColor: "#FFFFFF",

    gridStroke: "#7B8EA3",
    axisStroke: "#B3C0CF",
    axisText: "#173B67",

    textDark: "#1F2D3D",
    textSoft: "#6B7A8C",

    panelBg: "#FFFFFF",
    panelStroke: "#CDD8E4"
  };


  /*
   * ----------------------------------------------------------
   * MAPAS DE EJES
   * ----------------------------------------------------------
   */

  const mapaEjesNum =
    vaCrearMapaEjes_(
      ejesNum,
      "ID_EJE_NUMERICO",
      "EJE_NUM"
    );

  const mapaEjesAlf =
    vaCrearMapaEjes_(
      ejesAlf,
      "ID_EJE_ALFABETICO",
      "EJE_ALF"
    );


  /*
   * ----------------------------------------------------------
   * CONSTRUIR GRILLA REAL
   * ----------------------------------------------------------
   */

  const grillaMap = {};

  grilla.forEach(r => {

    const idPano =
      String(
        r.ID_PANO || ""
      ).trim();

    if (!idPano) {
      return;
    }

    const ejeNumDesde =
      vaResolverEje_(
        mapaEjesNum,
        r.EJE_NUM_DESDE
      );

    const ejeNumHasta =
      vaResolverEje_(
        mapaEjesNum,
        r.EJE_NUM_HASTA
      );

    const ejeAlfDesde =
      vaResolverEje_(
        mapaEjesAlf,
        r.EJE_ALF_DESDE
      );

    const ejeAlfHasta =
      vaResolverEje_(
        mapaEjesAlf,
        r.EJE_ALF_HASTA
      );

    if (
      !ejeNumDesde ||
      !ejeNumHasta ||
      !ejeAlfDesde ||
      !ejeAlfHasta
    ) {

      console.log(
        "PAÑO OMITIDO POR EJE NO ENCONTRADO | " +
        idPano
      );

      return;
    }

    const nivel =
      vaToNum_(
        r.NIVEL
      );

    const familia = [
      ejeAlfDesde.key,
      ejeAlfHasta.key,
      ejeNumDesde.key,
      ejeNumHasta.key
    ].join("|");

    const label =
      ejeAlfDesde.label +
      "-" +
      ejeAlfHasta.label +
      " / " +
      ejeNumDesde.label +
      "-" +
      ejeNumHasta.label;

    grillaMap[idPano] = {

      id: idPano,
      nivel: nivel,

      x1: ejeNumDesde.posicion,
      x2: ejeNumHasta.posicion,

      y1: ejeAlfDesde.posicion,
      y2: ejeAlfHasta.posicion,

      ejeNumDesdeLabel:
        ejeNumDesde.label,

      ejeNumHastaLabel:
        ejeNumHasta.label,

      ejeAlfDesdeLabel:
        ejeAlfDesde.label,

      ejeAlfHastaLabel:
        ejeAlfHasta.label,

      familia: familia,
      label: label
    };

  });


  /*
   * ----------------------------------------------------------
   * PAÑOS HORMIGONADOS
   * ----------------------------------------------------------
   */

  const hormigonadosSet =
    new Set();

  const fechasHormigonadoMap = {};

  guiaPanos.forEach(r => {

    const idPano =
      String(
        r.ID_PANO || ""
      ).trim();

    if (idPano) {
      hormigonadosSet.add(
        idPano
      );
    }

    const fechaHorm =
      vaParseDate_(
        vaGetField_(
          r,
          [
            "FECHA_HORMIGONADO",
            "FECHA",
            "FECHA_GUIA"
          ]
        )
      );

    if (
      idPano &&
      fechaHorm
    ) {

      if (
        !fechasHormigonadoMap[idPano] ||
        fechaHorm.getTime() > fechasHormigonadoMap[idPano].getTime()
      ) {
        fechasHormigonadoMap[idPano] = fechaHorm;
      }

    }

  });


  /*
   * ----------------------------------------------------------
   * CONTROL MANUAL (ESTADO INTERNO DESALZAPRIMADO / TEXTO VISUAL DESCIMBRE)
   * ----------------------------------------------------------
   */

  const controlMap = {};

  control.forEach(r => {

    const idPano =
      String(
        r.ID_PANO || ""
      ).trim();

    if (!idPano) {
      return;
    }

    controlMap[idPano] = {

      confirmado:
        vaYesNo_(
          vaGetField_(
            r,
            [
              "DESALZAPRIMADO_CONFIRMADO",
              "DESALZAPRIMADO",
              "DESAPUNTALADO_CONFIRMADO",
              "LIBERADO",
              "DES"
            ]
          )
        ),

      fechaConfirmacion:
        vaParseDate_(
          vaGetField_(
            r,
            [
              "FECHA_DESALZAPRIMADO",
              "FECHA_LIBERACION",
              "FECHA_CONFIRMACION",
              "FECHA"
            ]
          )
        )

    };

  });


  /*
   * ----------------------------------------------------------
   * FAMILIA + NIVEL HORMIGONADO
   * ----------------------------------------------------------
   */

  const familiaNivelHormigonado =
    new Set();

  Object
    .values(grillaMap)
    .forEach(g => {

      if (
        hormigonadosSet.has(
          g.id
        )
      ) {

        familiaNivelHormigonado.add(
          g.familia +
          "|" +
          g.nivel
        );

      }

    });


  /*
   * ----------------------------------------------------------
   * PAÑOS VISIBLES
   * ----------------------------------------------------------
   */

  const panosVisibles =
    Object
      .values(grillaMap)
      .filter(
        g =>
          g.nivel >= nivelDesde &&
          g.nivel <= nivelHasta
      )
      .sort(
        (a, b) => {

          if (
            a.nivel !== b.nivel
          ) {
            return a.nivel - b.nivel;
          }

          if (
            a.y1 !== b.y1
          ) {
            return a.y1 - b.y1;
          }

          return a.x1 - b.x1;
        }
      );

  console.log(
    "Paños visibles: " +
    panosVisibles.length
  );


  /*
   * ----------------------------------------------------------
   * LIMITES DE LA PLANTA
   * ----------------------------------------------------------
   */

  const limites =
    vaObtenerLimitesPlanta_(
      panosVisibles
    );


  /*
   * ----------------------------------------------------------
   * ESTADO + RESUMEN
   * ----------------------------------------------------------
   */

  const estadoConteo = {
    "FAENA ACTUAL": 0,
    "100% ALZAPRIMAS": 0,
    "50% ALZAPRIMAS": 0,
    "DISPONIBLE PARA DESALZAPRIMAR": 0,
    "DESALZAPRIMADA": 0,
    "SIN HORMIGONAR": 0
  };

  const panosRender =
    panosVisibles.map(p => {

      const estadoTecnico =
        vaCalcularEstadoTecnico_(
          p,
          hormigonadosSet,
          familiaNivelHormigonado
        );

      const confirmado =
        controlMap[p.id]
          ?
          controlMap[p.id]
            .confirmado
          :
          false;

      const estadoVisual =
        confirmado
          ?
          "DESALZAPRIMADA"
          :
          estadoTecnico;

      if (
        estadoConteo[estadoVisual] ===
        undefined
      ) {
        estadoConteo[estadoVisual] =
          0;
      }

      estadoConteo[
        estadoVisual
      ]++;

      return {
        pano: p,
        estadoTecnico: estadoTecnico,
        estadoVisual: estadoVisual,
        fechaHormigonado:
          fechasHormigonadoMap[p.id] || null,
        fechaCumplimiento:
          confirmado
            ?
            (
              controlMap[p.id] &&
              controlMap[p.id].fechaConfirmacion
                ?
                controlMap[p.id].fechaConfirmacion
                :
                fechasHormigonadoMap[p.id] || null
            )
            :
            fechasHormigonadoMap[p.id] || null
      };

    });


  /*
   * ----------------------------------------------------------
   * DIBUJAR TOP DE LOSAS
   * ----------------------------------------------------------
   */

  let shapes =
    "";

  let labels =
    "";

  panosRender.forEach(item => {

    const p =
      item.pano;

    const estadoVisual =
      item.estadoVisual;

    const colorTop =
      vaColorEstado_(
        estadoVisual
      );

    const pts =
      vaPanoToIso_(
        p,
        cfg
      );

    /*
     * SOLO SUPERFICIE SUPERIOR
     */

    shapes +=
      '<polygon points="' +
      pts.top +
      '"' +
      ' fill="' +
      colorTop +
      '"' +
      ' stroke="' +
      cfg.gridStroke +
      '"' +
      ' stroke-width="1.2"/>';

    /*
     * BORDE LATERAL IZQUIERDO:
     * LÍNEA TÉCNICA PUNTEADA Y SUAVE.
     */

    if (
      vaEsBordeLateralIzq_(
        p,
        limites
      )
    ) {

      shapes +=
        '<line x1="' +
        pts.leftEdge.x1 +
        '" y1="' +
        pts.leftEdge.y1 +
        '" x2="' +
        pts.leftEdge.x2 +
        '" y2="' +
        pts.leftEdge.y2 +
        '" stroke="#9FB0C3" stroke-width="1.1" stroke-dasharray="5,5" opacity="0.9"/>';

    }

    /*
     * ESPESOR SOLO SI EL PAÑO ESTÁ EN EL BORDE FRONTAL
     * EXTERIOR DE LA PLANTA.
     */

    if (
      vaEsBordeFrontal_(
        p,
        limites
      )
    ) {

      const colorFront =
        vaShadeColor_(
          colorTop,
          -22
        );

      shapes +=
        '<polygon points="' +
        pts.front +
        '"' +
        ' fill="' +
        colorFront +
        '"' +
        ' stroke="' +
        cfg.gridStroke +
        '"' +
        ' stroke-width="0.9"/>';

    }

    /*
     * BORDE / ESPESOR DERECHO
     * SOLO EN EL CONTORNO EXTERIOR DERECHO.
     */

    if (
      vaEsBordeLateralDer_(
        p,
        limites
      )
    ) {

      const colorRight =
        vaShadeColor_(
          colorTop,
          -22
        );

      shapes +=
        '<polygon points="' +
        pts.right +
        '"' +
        ' fill="' +
        colorRight +
        '"' +
        ' stroke="' +
        cfg.gridStroke +
        '"' +
        ' stroke-width="0.9"/>';

    }

    /*
     * LABEL DEL PAÑO
     */

    labels +=
      '<text x="' +
      pts.center.x +
      '"' +
      ' y="' +
      (pts.center.y + 4) +
      '"' +
      ' text-anchor="middle"' +
      ' font-family="Arial"' +
      ' font-size="12"' +
      ' font-weight="700"' +
      ' fill="' +
      cfg.textDark +
      '">' +
      vaEscapeXml_(
        p.label
      ) +
      '</text>';

  });


  /*
   * ----------------------------------------------------------
   * ETIQUETAS DE NIVEL
   * ----------------------------------------------------------
   */

  let levelLabels =
    "";

  for (
    let nivel = nivelDesde;
    nivel <= nivelHasta;
    nivel++
  ) {

    const puntoNivel =
      vaProjectIso_(
        limites.minX,
        limites.minY,
        nivel,
        cfg
      );

    levelLabels +=
      '<rect x="20"' +
      ' y="' +
      (puntoNivel.y - 22) +
      '"' +
      ' width="110"' +
      ' height="36"' +
      ' rx="8"' +
      ' fill="#FFFFFF"' +
      ' stroke="#C5D2E0"' +
      ' stroke-width="1.4"/>' +

      '<text x="75"' +
      ' y="' +
      (puntoNivel.y + 1) +
      '"' +
      ' text-anchor="middle"' +
      ' font-family="Arial"' +
      ' font-size="17"' +
      ' font-weight="700"' +
      ' letter-spacing="0.4"' +
      ' fill="#173B67">' +
      'NIVEL ' +
      nivel +
      '</text>';

  }


  /*
   * ----------------------------------------------------------
   * EJES VISUALES
   * ----------------------------------------------------------
   *
   * Los ejes siguen utilizándose internamente para calcular
   * la geometría de cada paño, pero NO se dibujan en el SVG.
   * La lectura se concentra en LABEL_PANO (ej.: A-E / 1-2).
   */

  const ejesSvg = "";


  /*
   * ----------------------------------------------------------
   * PANEL LATERAL
   * ----------------------------------------------------------
   */

  const secuenciaActual =
    vaBuildSecuenciaActual_(
      panosRender
    );

  const panelesSvg =
    vaBuildInfoPanelSvg_(
      cfg,
      nivelDesde,
      nivelHasta,
      panosVisibles.length,
      estadoConteo,
      secuenciaActual
    );


  /*
   * ----------------------------------------------------------
   * FECHA ACTUALIZACIÓN
   * ----------------------------------------------------------
   */

  const timeStamp =
    Utilities.formatDate(
      new Date(),
      Session.getScriptTimeZone(),
      "dd/MM/yyyy HH:mm"
    );


  /*
   * ----------------------------------------------------------
   * SVG FINAL
   * ----------------------------------------------------------
   */

  const svg =
    '<svg xmlns="http://www.w3.org/2000/svg"' +
    ' viewBox="0 0 ' +
    W +
    ' ' +
    H +
    '">' +

    '<rect width="' +
    W +
    '" height="' +
    H +
    '" fill="' +
    cfg.bg +
    '"/>' +

    '<rect x="12"' +
    ' y="12"' +
    ' width="' +
    (W - 24) +
    '"' +
    ' height="' +
    (H - 24) +
    '"' +
    ' rx="24"' +
    ' fill="none"' +
    ' stroke="' +
    cfg.frame +
    '"' +
    ' stroke-width="2"/>' +

    /*
     * HEADER
     */

    '<rect x="18"' +
    ' y="18"' +
    ' width="' +
    (W - 36) +
    '"' +
    ' height="78"' +
    ' rx="22"' +
    ' fill="' +
    cfg.titleBg +
    '"/>' +

    '<text x="44"' +
    ' y="55"' +
    ' font-family="Arial"' +
    ' font-size="26"' +
    ' font-weight="700"' +
    ' fill="' +
    cfg.titleColor +
    '">' +
    'CONTROL DE ALZAPRIMAS - LOSAS' +
    '</text>' +

    '<text x="44"' +
    ' y="76"' +
    ' font-family="Arial"' +
    ' font-size="14"' +
    ' font-weight="600"' +
    ' fill="#E8F0FA">' +
    'Secuencia vertical por familia de paño' +
    '</text>' +

    '<text x="' +
    (W - 150) +
    '"' +
    ' y="48"' +
    ' text-anchor="middle"' +
    ' font-family="Arial"' +
    ' font-size="13"' +
    ' font-weight="700"' +
    ' fill="#E8F0FA">' +
    'ACTUALIZADO' +
    '</text>' +

    '<text x="' +
    (W - 150) +
    '"' +
    ' y="76"' +
    ' text-anchor="middle"' +
    ' font-family="Arial"' +
    ' font-size="18"' +
    ' font-weight="700"' +
    ' fill="#FFFFFF">' +
    timeStamp +
    '</text>' +

    /*
     * ORDEN:
     * - ejes punteados de fondo
     * - top de losas
     * - labels
     * - niveles
     * - paneles
     */

    ejesSvg +
    shapes +
    labels +
    levelLabels +
    panelesSvg +

    '</svg>';


  /*
   * ----------------------------------------------------------
   * GUARDAR SVG
   * ----------------------------------------------------------
   */

  const nombreArchivo =
    vaGuardarSvgDrive_(
      ss,
      idVista,
      svg
    );

  vaWriteValueByKey_(
    shVista,
    "ID_VISTA",
    idVista,
    "SVG_URI",
    nombreArchivo
  );


  /*
   * ----------------------------------------------------------
   * LOG
   * ----------------------------------------------------------
   */

  console.log(
    "======================================"
  );

  console.log(
    "VISTA ALZAPRIMADO v5.8.3 GENERADA"
  );

  console.log(
    "ID_VISTA: " +
    idVista
  );

  console.log(
    "Niveles: " +
    nivelDesde +
    " a " +
    nivelHasta
  );

  console.log(
    "Paños: " +
    panosVisibles.length
  );

  console.log(
    "Archivo: " +
    nombreArchivo
  );

  console.log(
    "Caracteres SVG: " +
    svg.length
  );

  console.log(
    "======================================"
  );

}


/*
 * ============================================================
 * LIMITES DE LA PLANTA
 * ============================================================
 */

function vaObtenerLimitesPlanta_(
  panos
) {

  if (
    !panos ||
    panos.length === 0
  ) {

    return {
      minX: 0,
      maxX: 0,
      minY: 0,
      maxY: 0
    };

  }

  return {

    minX:
      Math.min.apply(
        null,
        panos.map(
          p => p.x1
        )
      ),

    maxX:
      Math.max.apply(
        null,
        panos.map(
          p => p.x2
        )
      ),

    minY:
      Math.min.apply(
        null,
        panos.map(
          p => p.y1
        )
      ),

    maxY:
      Math.max.apply(
        null,
        panos.map(
          p => p.y2
        )
      )

  };

}


/*
 * ============================================================
 * DETERMINAR BORDE FRONTAL
 * ============================================================
 *
 * Solo los paños que terminan en el máximo Y dibujan
 * espesor. Así desaparecen los "regruesos" interiores.
 * ============================================================
 */

function vaEsBordeFrontal_(
  pano,
  limites
) {

  const tolerancia =
    0.001;

  return (
    Math.abs(
      pano.y1 -
      limites.minY
    )
    <
    tolerancia
  );

}


/*
 * ============================================================
 * DETERMINAR BORDE LATERAL IZQUIERDO
 * ============================================================
 */

function vaEsBordeLateralIzq_(
  pano,
  limites
) {

  const tolerancia =
    0.001;

  return (
    Math.abs(
      pano.x1 -
      limites.minX
    )
    <
    tolerancia
  );

}


/*
 * ============================================================
 * DETERMINAR BORDE LATERAL DERECHO
 * ============================================================
 */

function vaEsBordeLateralDer_(
  pano,
  limites
) {

  const tolerancia =
    0.001;

  return (
    Math.abs(
      pano.x2 -
      limites.maxX
    )
    <
    tolerancia
  );

}


/*
 * ============================================================
 * EJES
 * ============================================================
 *
 * NUMÉRICOS:
 * - etiquetas arriba
 * - línea punteada vertical a través de los niveles
 *
 * ALFABÉTICOS:
 * - etiquetas al costado izquierdo
 * - línea punteada sobre el nivel superior
 *
 * Sin círculos.
 * ============================================================
 */

function vaBuildAxesSvg_(
  panosVisibles,
  cfg,
  limites
) {

  const ejesNumMap =
    {};

  const ejesAlfMap =
    {};

  panosVisibles.forEach(
    p => {

      ejesNumMap[
        p.ejeNumDesdeLabel
      ] =
        p.x1;

      ejesNumMap[
        p.ejeNumHastaLabel
      ] =
        p.x2;

      ejesAlfMap[
        p.ejeAlfDesdeLabel
      ] =
        p.y1;

      ejesAlfMap[
        p.ejeAlfHastaLabel
      ] =
        p.y2;

    }
  );

  const ejesNum =
    Object
      .keys(
        ejesNumMap
      )
      .map(
        label => ({
          label: label,
          pos:
            ejesNumMap[label]
        })
      )
      .sort(
        (a, b) =>
          a.pos - b.pos
      );

  const ejesAlf =
    Object
      .keys(
        ejesAlfMap
      )
      .map(
        label => ({
          label: label,
          pos:
            ejesAlfMap[label]
        })
      )
      .sort(
        (a, b) =>
          a.pos - b.pos
      );


  let out =
    "";


  /*
   * ----------------------------------------------------------
   * EJES NUMÉRICOS
   * ----------------------------------------------------------
   */

  ejesNum.forEach(
    eje => {

      const top =
        vaProjectIso_(
          eje.pos,
          limites.minY,
          cfg.nivelHasta,
          cfg
        );

      const bottom =
        vaProjectIso_(
          eje.pos,
          limites.minY,
          cfg.nivelDesde,
          cfg
        );

      const labelY =
        top.y -
        110;

      /*
       * LÍNEA PUNTEADA
       */

      out +=
        '<line x1="' +
        top.x +
        '"' +
        ' y1="' +
        (labelY + 18) +
        '"' +
        ' x2="' +
        bottom.x +
        '"' +
        ' y2="' +
        (bottom.y + 16) +
        '"' +
        ' stroke="' +
        cfg.axisStroke +
        '"' +
        ' stroke-width="1.0"' +
        ' stroke-dasharray="5,7"' +
        ' opacity="0.62"/>';

      /*
       * NUMERO
       */

      out +=
        '<rect x="' +
        (top.x - 17) +
        '" y="' +
        (labelY - 21) +
        '" width="34" height="24" rx="7" fill="#FFFFFF" stroke="#BFD0E0" stroke-width="1.3"/>' +
        '<text x="' +
        top.x +
        '"' +
        ' y="' +
        labelY +
        '"' +
        ' text-anchor="middle"' +
        ' font-family="Arial"' +
        ' font-size="15"' +
        ' font-weight="700"' +
        ' fill="' +
        cfg.axisText +
        '">' +
        vaEscapeXml_(
          eje.label
        ) +
        '</text>';

    }
  );


  /*
   * ----------------------------------------------------------
   * EJES ALFABÉTICOS
   * ----------------------------------------------------------
   */

  let ultimoLabelY =
    null;

  ejesAlf.forEach(
    (eje, indice) => {

      const inicio =
        vaProjectIso_(
          limites.minX,
          eje.pos,
          cfg.nivelHasta,
          cfg
        );

      const fin =
        vaProjectIso_(
          limites.maxX,
          eje.pos,
          cfg.nivelHasta,
          cfg
        );

      /*
       * LÍNEA PUNTEADA DE GRILLA
       * SOLO EN EL NIVEL SUPERIOR.
       */

      out +=
        '<line x1="' +
        inicio.x +
        '"' +
        ' y1="' +
        inicio.y +
        '"' +
        ' x2="' +
        fin.x +
        '"' +
        ' y2="' +
        fin.y +
        '"' +
        ' stroke="' +
        cfg.axisStroke +
        '"' +
        ' stroke-width="1.0"' +
        ' stroke-dasharray="5,7"' +
        ' opacity="0.58"/>';


      /*
       * LABEL A LA IZQUIERDA.
       *
       * C1 y C están muy cerca, por eso se escalonan.
       */

      let labelY =
        inicio.y -
        70;

      if (
        ultimoLabelY !== null &&
        Math.abs(
          labelY -
          ultimoLabelY
        ) < 28
      ) {

        labelY +=
          (
            indice % 2 === 0
              ?
              -24
              :
              24
          );

      }

      ultimoLabelY =
        labelY;

      const labelX =
        inicio.x -
        54 -
        (
          indice % 2 === 0
            ?
            0
            :
            22
        );


      out +=
        '<line x1="' +
        (labelX + 26) +
        '"' +
        ' y1="' +
        (labelY - 4) +
        '"' +
        ' x2="' +
        (inicio.x - 5) +
        '"' +
        ' y2="' +
        inicio.y +
        '"' +
        ' stroke="' +
        cfg.axisStroke +
        '"' +
        ' stroke-width="0.95"' +
        ' stroke-dasharray="4,5"' +
        ' opacity="0.65"/>';


      out +=
        '<rect x="' +
        (labelX - 26) +
        '" y="' +
        (labelY - 17) +
        '" width="28" height="22" rx="6" fill="#FFFFFF" stroke="#BFD0E0" stroke-width="1.2"/>' +
        '<text x="' +
        (labelX - 12) +
        '"' +
        ' y="' +
        labelY +
        '"' +
        ' text-anchor="middle"' +
        ' font-family="Arial"' +
        ' font-size="14"' +
        ' font-weight="700"' +
        ' fill="' +
        cfg.axisText +
        '">' +
        vaEscapeXml_(
          eje.label
        ) +
        '</text>';

    }
  );


  return out;

}


/*
 * ============================================================
 * PANEL LATERAL
 * ============================================================
 */

function vaBuildInfoPanelSvg_(
  cfg,
  nivelDesde,
  nivelHasta,
  totalPanos,
  estadoConteo,
  secuenciaActual
) {

  const x =
    1254;

  const panelW =
    404;

  let out =
    "";


  /*
   * BLOQUE ESTADOS
   */

  out +=
    '<rect x="' + x + '" y="118" width="' + panelW + '" height="374" rx="12" fill="#FFFFFF" stroke="' + cfg.panelStroke + '" stroke-width="1.8"/>' +
    '<rect x="' + x + '" y="118" width="' + panelW + '" height="42" rx="12" fill="#F3F7FB" stroke="' + cfg.panelStroke + '" stroke-width="1.8"/>' +
    '<text x="' + (x + 20) + '" y="145" font-family="Arial" font-size="17" font-weight="700" letter-spacing="0.5" fill="#173B67">ESTADOS</text>' +
    '<text x="' + (x + panelW - 20) + '" y="145" text-anchor="end" font-family="Arial" font-size="13" font-weight="700" fill="#5D7692">NIVELES ' + nivelDesde + ' — ' + nivelHasta + '</text>' +
    '<text x="' + (x + 20) + '" y="180" font-family="Arial" font-size="14" font-weight="700" fill="#5D7692">' + totalPanos + ' PAÑOS EN VISTA</text>';

  const items = [
    ["FAENA ACTUAL", "#E85C4A", estadoConteo["FAENA ACTUAL"] || 0],
    ["100% ALZAPRIMAS", "#3E82E0", estadoConteo["100% ALZAPRIMAS"] || 0],
    ["50% ALZAPRIMAS", "#F2C94C", estadoConteo["50% ALZAPRIMAS"] || 0],
    ["DISPONIBLE DESCIMBRE", "#6ECF9C", estadoConteo["DISPONIBLE PARA DESALZAPRIMAR"] || 0],
    ["DESCIMBRADA", "#238B57", estadoConteo["DESALZAPRIMADA"] || 0],
    ["SIN HORMIGONAR", "#DDE4EC", estadoConteo["SIN HORMIGONAR"] || 0]
  ];

  let y = 224;
  items.forEach((item, idx) => {
    out +=
      '<line x1="' + (x + 18) + '" y1="' + (y + 17) + '" x2="' + (x + panelW - 18) + '" y2="' + (y + 17) + '" stroke="#E4EBF2" stroke-width="1"/>' +
      '<rect x="' + (x + 22) + '" y="' + (y - 12) + '" width="20" height="14" rx="3" fill="' + item[1] + '" stroke="#6D7E90" stroke-width="0.9"/>' +
      '<text x="' + (x + 56) + '" y="' + y + '" font-family="Arial" font-size="14" font-weight="700" fill="#1F2D3D">' + item[0] + '</text>' +
      '<text x="' + (x + panelW - 24) + '" y="' + y + '" text-anchor="end" font-family="Arial" font-size="14" font-weight="700" fill="#1F2D3D">' + item[2] + '</text>';
    y += 42;
  });


  /*
   * SECUENCIA ACTUAL
   */

  out +=
    '<rect x="' + x + '" y="515" width="' + panelW + '" height="282" rx="12" fill="#FFFFFF" stroke="' + cfg.panelStroke + '" stroke-width="1.8"/>' +
    '<rect x="' + x + '" y="515" width="' + panelW + '" height="42" rx="12" fill="#F3F7FB" stroke="' + cfg.panelStroke + '" stroke-width="1.8"/>' +
    '<text x="' + (x + 20) + '" y="542" font-family="Arial" font-size="16" font-weight="700" letter-spacing="0.4" fill="#173B67">SECUENCIA ACTUAL</text>' +
    '<text x="' + (x + 20) + '" y="578" font-family="Arial" font-size="12" font-weight="700" fill="#6B7A8C">NIVEL</text>' +
    '<text x="' + (x + 95) + '" y="578" font-family="Arial" font-size="12" font-weight="700" fill="#6B7A8C">PAÑO</text>' +
    '<text x="' + (x + panelW - 20) + '" y="578" text-anchor="end" font-family="Arial" font-size="12" font-weight="700" fill="#6B7A8C">ESTADO</text>' +
    '<line x1="' + (x + 18) + '" y1="588" x2="' + (x + panelW - 18) + '" y2="588" stroke="#C9D5E3" stroke-width="1.2"/>';

  let ys = 620;
  (secuenciaActual.rows || []).forEach(row => {
    out +=
      '<line x1="' + (x + 18) + '" y1="' + (ys + 14) + '" x2="' + (x + panelW - 18) + '" y2="' + (ys + 14) + '" stroke="#E4EBF2" stroke-width="1"/>' +
      '<text x="' + (x + 20) + '" y="' + ys + '" font-family="Arial" font-size="13" font-weight="700" fill="#173B67">' + vaEscapeXml_(row.nivelTxt || '—') + '</text>' +
      '<text x="' + (x + 95) + '" y="' + ys + '" font-family="Arial" font-size="13" font-weight="700" fill="#1F2D3D">' + vaEscapeXml_(row.label || '—') + '</text>' +
      '<rect x="' + (x + panelW - 156) + '" y="' + (ys - 11) + '" width="12" height="12" rx="2" fill="' + (row.color || '#DDE4EC') + '" stroke="#6D7E90" stroke-width="0.8"/>' +
      '<text x="' + (x + panelW - 20) + '" y="' + ys + '" text-anchor="end" font-family="Arial" font-size="12" font-weight="700" fill="#58708D">' + vaEscapeXml_(row.estado || '—') + '</text>';
    ys += 34;
  });

  out +=
    '<line x1="' + (x + 18) + '" y1="748" x2="' + (x + panelW - 18) + '" y2="748" stroke="#C9D5E3" stroke-width="1.1"/>' +
    '<text x="' + (x + 20) + '" y="772" font-family="Arial" font-size="11" font-weight="700" fill="#6B7A8C">ÚLTIMO HORMIGONADO</text>' +
    '<text x="' + (x + panelW - 20) + '" y="772" text-anchor="end" font-family="Arial" font-size="12" font-weight="700" fill="#173B67">' + vaEscapeXml_(secuenciaActual.ultimoHormigonado || '—') + '</text>';
  return out;

}


/*
 * ============================================================
 * ESTADO TÉCNICO
 * ============================================================
 */

function vaCalcularEstadoTecnico_(
  pano,
  hormigonadosSet,
  familiaNivelHormigonado
) {

  if (
    !hormigonadosSet.has(
      pano.id
    )
  ) {

    return "SIN HORMIGONAR";

  }


  const sup1 =
    familiaNivelHormigonado.has(
      pano.familia +
      "|" +
      (
        pano.nivel +
        1
      )
    );


  const sup2 =
    familiaNivelHormigonado.has(
      pano.familia +
      "|" +
      (
        pano.nivel +
        2
      )
    );


  const sup3 =
    familiaNivelHormigonado.has(
      pano.familia +
      "|" +
      (
        pano.nivel +
        3
      )
    );


  if (!sup1) {

    return "FAENA ACTUAL";

  }


  if (
    sup1 &&
    !sup2
  ) {

    return "100% ALZAPRIMAS";

  }


  if (
    sup2 &&
    !sup3
  ) {

    return "50% ALZAPRIMAS";

  }


  if (sup3) {

    return "DISPONIBLE PARA DESALZAPRIMAR";

  }


  return "SIN HORMIGONAR";

}


/*
 * ============================================================
 * COLORES
 * ============================================================
 */

function vaColorEstado_(
  estado
) {

  switch (
    estado
  ) {

    case "FAENA ACTUAL":
      return "#E85C4A";

    case "100% ALZAPRIMAS":
      return "#3E82E0";

    case "50% ALZAPRIMAS":
      return "#F2C94C";

    case "DISPONIBLE PARA DESALZAPRIMAR":
      return "#6ECF9C";

    case "DESALZAPRIMADA":
      return "#238B57";

    default:
      return "#DDE4EC";
  }

}


/*
 * ============================================================
 * GEOMETRÍA
 * ============================================================
 */

function vaProjectIso_(
  x,
  y,
  nivel,
  cfg
) {

  const indiceNivel =
    nivel -
    cfg.nivelDesde;


  return {

    x:
      vaRound2_(
        cfg.originX +
        (
          x *
          cfg.scaleX
        ) +
        (
          y *
          cfg.perspectiveX
        )
      ),

    y:
      vaRound2_(
        cfg.originY -
        (
          indiceNivel *
          cfg.levelGap
        ) -
        (
          y *
          cfg.perspectiveY
        )
      )

  };

}


function vaPanoToIso_(
  p,
  cfg
) {

  const A =
    vaProjectIso_(
      p.x1,
      p.y1,
      p.nivel,
      cfg
    );

  const B =
    vaProjectIso_(
      p.x2,
      p.y1,
      p.nivel,
      cfg
    );

  const C =
    vaProjectIso_(
      p.x2,
      p.y2,
      p.nivel,
      cfg
    );

  const D =
    vaProjectIso_(
      p.x1,
      p.y2,
      p.nivel,
      cfg
    );


  const th =
    cfg.slabThickness;


  const A2 = {
    x: A.x,
    y: A.y + th
  };


  const B2 = {
    x: B.x,
    y: B.y + th
  };


  const D2 = {
    x: D.x,
    y: D.y + th
  };


  const C2 = {
    x: C.x,
    y: C.y + th
  };


  return {

    top:
      A.x + "," + A.y + " " +
      B.x + "," + B.y + " " +
      C.x + "," + C.y + " " +
      D.x + "," + D.y,

    leftEdge: {
      x1: A.x,
      y1: A.y,
      x2: D.x,
      y2: D.y
    },

    /*
     * SOLO CARA FRONTAL
     * A - B
     */

    front:
      A.x + "," + A.y + " " +
      B.x + "," + B.y + " " +
      B2.x + "," + B2.y + " " +
      A2.x + "," + A2.y,

    /*
     * COSTADO DERECHO
     * B - C
     */

    right:
      B.x + "," + B.y + " " +
      C.x + "," + C.y + " " +
      C2.x + "," + C2.y + " " +
      B2.x + "," + B2.y,

    center: {

      x:
        vaRound2_(
          (
            A.x +
            B.x +
            C.x +
            D.x
          ) / 4
        ),

      y:
        vaRound2_(
          (
            A.y +
            B.y +
            C.y +
            D.y
          ) / 4
        )

    }

  };

}


/*
 * ============================================================
 * MAPA DE EJES
 * ============================================================
 */

function vaCrearMapaEjes_(
  filas,
  columnaId,
  columnaLabel
) {

  const mapa =
    {};


  filas.forEach(
    fila => {

      const key =
        String(
          fila[columnaId] || ""
        ).trim();


      const label =
        String(
          fila[columnaLabel] || ""
        ).trim();


      const posicion =
        vaToNum_(
          fila.DISTANCIA_ACUMULADA
        );


      if (!key) {
        return;
      }


      const objeto = {

        key: key,

        label:
          label || key,

        posicion:
          posicion

      };


      mapa[
        vaNormalizarClave_(
          key
        )
      ] =
        objeto;


      if (label) {

        mapa[
          vaNormalizarClave_(
            label
          )
        ] =
          objeto;

      }

    }
  );


  return mapa;

}


function vaResolverEje_(
  mapa,
  valor
) {

  const clave =
    vaNormalizarClave_(
      valor
    );


  if (!clave) {
    return null;
  }


  return (
    mapa[clave] ||
    null
  );

}


function vaNormalizarClave_(
  valor
) {

  return String(
    valor === null ||
    valor === undefined
      ?
      ""
      :
      valor
  )
    .trim()
    .toUpperCase();

}


/*
 * ============================================================
 * GUARDAR SVG EN DRIVE
 * ============================================================
 */

function vaGuardarSvgDrive_(
  ss,
  idVista,
  svg
) {

  /*
   * ----------------------------------------------------------
   * CARPETA DESTINO
   * ----------------------------------------------------------
   *
   * Desde v5.8.2 NO se utiliza la carpeta del Spreadsheet.
   * El SVG se guarda exclusivamente en SVG_Alzaprimado.
   *
   * El parámetro "ss" se mantiene en la firma de la función
   * para no alterar las llamadas existentes.
   */

  let carpeta;

  try {

    carpeta =
      DriveApp.getFolderById(
        CONFIG_VISTA_ALZ.SVG_FOLDER_ID
      );

  } catch (error) {

    throw new Error(
      "No fue posible acceder a la carpeta SVG_Alzaprimado. " +
      "Revisar SVG_FOLDER_ID y permisos. Detalle: " +
      error.message
    );

  }


  /*
   * ----------------------------------------------------------
   * ID SEGURO / PREFIJO
   * ----------------------------------------------------------
   */

  const idSeguro =
    String(
      idVista
    )
      .replace(
        /[^A-Za-z0-9_-]/g,
        "_"
      );


  const prefijo =
    "ALZAPRIMADO_" +
    idSeguro +
    "_";


  /*
   * HISTORIAL DE INSTANTÁNEAS:
   * No se elimina el SVG anterior. Cada archivo conservará la fecha
   * de creación real de Drive; Cloud Run podrá elegir el último
   * archivo disponible antes de la FECHA_CORTE del informe.
   *
   * Aviso: los SVG antiguos ya eliminados no se pueden restaurar
   * automáticamente con esta modificación.
   */


  /*
   * ----------------------------------------------------------
   * NUEVO NOMBRE
   * ----------------------------------------------------------
   */

  const timestamp =
    Utilities.formatDate(
      new Date(),
      Session.getScriptTimeZone(),
      "yyyyMMdd_HHmmss_SSS"
    );


  const nombreArchivo =
    prefijo +
    timestamp +
    ".svg";


  /*
   * ----------------------------------------------------------
   * CREAR SVG
   * ----------------------------------------------------------
   */

  const blob =
    Utilities.newBlob(
      svg,
      "image/svg+xml",
      nombreArchivo
    );


  const archivoCreado =
    carpeta.createFile(
      blob
    );


  /*
   * ----------------------------------------------------------
   * VALOR PARA APPSHEET
   * ----------------------------------------------------------
   *
   * Se devuelve la ruta relativa:
   *
   * SVG_Alzaprimado/ALZAPRIMADO_xxx.svg
   *
   * Esto permite que VISTA_ALZAPRIMADO[SVG_URI] continúe
   * trabajando como ruta de archivo, sin guardar el SVG
   * directamente en Mi unidad.
   */

  const rutaRelativa =
    CONFIG_VISTA_ALZ.SVG_FOLDER_NAME +
    "/" +
    nombreArchivo;


  console.log(
    "SVG guardado en carpeta dedicada: " +
    carpeta.getName()
  );

  console.log(
    "ID archivo SVG: " +
    archivoCreado.getId()
  );

  console.log(
    "Ruta AppSheet: " +
    rutaRelativa
  );


  return rutaRelativa;

}


/*
 * ============================================================
 * BUSCAR HOJA
 * ============================================================
 */

function vaBuscarHoja_(
  ss,
  nombres
) {

  for (
    let i = 0;
    i < nombres.length;
    i++
  ) {

    const hoja =
      ss.getSheetByName(
        nombres[i]
      );


    if (hoja) {
      return hoja;
    }

  }


  return null;

}


/*
 * ============================================================
 * SHEET -> OBJETOS
 * ============================================================
 */

function vaSheetToObjects_(
  hoja
) {

  const datos =
    hoja
      .getDataRange()
      .getValues();


  if (
    datos.length <
    2
  ) {
    return [];
  }


  const headers =
    datos[0]
      .map(
        h =>
          String(
            h || ""
          ).trim()
      );


  return datos
    .slice(1)
    .filter(
      row =>
        row.some(
          v =>
            v !== ""
        )
    )
    .map(
      row => {

        const obj =
          {};


        headers.forEach(
          (
            h,
            i
          ) => {

            if (h) {
              obj[h] =
                row[i];
            }

          }
        );


        return obj;

      }
    );

}


/*
 * ============================================================
 * ESCRIBIR POR KEY
 * ============================================================
 */

function vaWriteValueByKey_(
  hoja,
  keyHeader,
  keyValue,
  writeHeader,
  writeValue
) {

  const datos =
    hoja
      .getDataRange()
      .getValues();


  if (
    datos.length <
    2
  ) {

    throw new Error(
      "La hoja " +
      hoja.getName() +
      " no tiene registros."
    );

  }


  const headers =
    datos[0]
      .map(
        e =>
          String(
            e || ""
          ).trim()
      );


  const keyCol =
    headers.indexOf(
      keyHeader
    );


  const writeCol =
    headers.indexOf(
      writeHeader
    );


  if (
    keyCol === -1
  ) {

    throw new Error(
      "No existe columna " +
      keyHeader +
      " en " +
      hoja.getName()
    );

  }


  if (
    writeCol === -1
  ) {

    throw new Error(
      "No existe columna " +
      writeHeader +
      " en " +
      hoja.getName()
    );

  }


  for (
    let r = 1;
    r < datos.length;
    r++
  ) {

    if (
      String(
        datos[r][keyCol]
      ).trim()
      ===
      String(
        keyValue
      ).trim()
    ) {

      hoja
        .getRange(
          r + 1,
          writeCol + 1
        )
        .setValue(
          writeValue
        );


      return;

    }

  }


  throw new Error(
    "No se encontró " +
    keyHeader +
    " = " +
    keyValue +
    " en " +
    hoja.getName()
  );

}


/*
 * ============================================================
 * HELPERS
 * ============================================================
 */

function vaYesNo_(
  valor
) {

  if (
    valor === true
  ) {
    return true;
  }


  if (
    valor === false
  ) {
    return false;
  }


  const txt =
    String(
      valor || ""
    )
      .trim()
      .toUpperCase();


  return (
    txt === "TRUE" ||
    txt === "Y" ||
    txt === "YES" ||
    txt === "SI" ||
    txt === "SÍ"
  );

}


function vaToNum_(
  valor,
  defecto
) {

  defecto =
    (
      defecto ===
      undefined
    )
      ?
      0
      :
      defecto;


  if (
    valor === null ||
    valor === undefined ||
    valor === ""
  ) {

    return defecto;

  }


  if (
    typeof valor ===
    "number"
  ) {

    return valor;

  }


  const txt =
    String(
      valor
    )
      .trim()
      .replace(
        /\s/g,
        ""
      );


  const norm =
    txt
      .replace(
        /\./g,
        ""
      )
      .replace(
        ",",
        "."
      );


  const n =
    Number(
      norm
    );


  return (
    isNaN(
      n
    )
      ?
      defecto
      :
      n
  );

}


function vaRound2_(
  n
) {

  return (
    Math.round(
      n *
      100
    )
    /
    100
  );

}


function vaEscapeXml_(
  texto
) {

  return String(
    texto || ""
  )
    .replace(
      /&/g,
      "&amp;"
    )
    .replace(
      /</g,
      "&lt;"
    )
    .replace(
      />/g,
      "&gt;"
    )
    .replace(
      /"/g,
      "&quot;"
    );

}


function vaShadeColor_(
  hex,
  percent
) {

  const num =
    parseInt(
      hex.replace(
        "#",
        ""
      ),
      16
    );


  let r =
    (num >> 16) +
    percent;


  let g =
    (
      (
        num >> 8
      )
      &
      0x00FF
    ) +
    percent;


  let b =
    (
      num &
      0x0000FF
    ) +
    percent;


  r =
    Math.max(
      Math.min(
        255,
        r
      ),
      0
    );


  g =
    Math.max(
      Math.min(
        255,
        g
      ),
      0
    );


  b =
    Math.max(
      Math.min(
        255,
        b
      ),
      0
    );


  return (
    "#"
    +
    (
      0x1000000 +
      (
        r *
        0x10000
      ) +
      (
        g *
        0x100
      ) +
      b
    )
      .toString(
        16
      )
      .slice(
        1
      )
  );

}


function vaGetField_(
  obj,
  posiblesCampos
) {

  for (
    let i = 0;
    i < posiblesCampos.length;
    i++
  ) {

    const campo =
      posiblesCampos[i];


    if (
      Object.prototype
        .hasOwnProperty
        .call(
          obj,
          campo
        )
    ) {

      return obj[campo];

    }

  }


  return "";

}


function vaBuildSecuenciaActual_(
  panosRender
) {

  const colorMap = {
    "FAENA ACTUAL": "#E85C4A",
    "100% ALZAPRIMAS": "#3E82E0",
    "50% ALZAPRIMAS": "#F2C94C",
    "DISPONIBLE PARA DESALZAPRIMAR": "#6ECF9C",
    "DESALZAPRIMADA": "#238B57",
    "SIN HORMIGONAR": "#DDE4EC"
  };

  const prioridad = [
    "FAENA ACTUAL",
    "100% ALZAPRIMAS",
    "50% ALZAPRIMAS",
    "DISPONIBLE PARA DESALZAPRIMAR",
    "DESALZAPRIMADA"
  ];

  const activos =
    panosRender.filter(
      item => item.estadoVisual !== "SIN HORMIGONAR"
    );

  if (activos.length === 0) {
    return {
      rows: [
        { nivelTxt: "—", label: "—", estado: "—", color: "#DDE4EC" },
        { nivelTxt: "—", label: "—", estado: "—", color: "#DDE4EC" },
        { nivelTxt: "—", label: "—", estado: "—", color: "#DDE4EC" },
        { nivelTxt: "—", label: "—", estado: "—", color: "#DDE4EC" }
      ],
      ultimoHormigonado: "—"
    };
  }

  let semilla = null;

  prioridad.some(estado => {
    const candidato = activos
      .filter(item => item.estadoVisual === estado)
      .sort((a, b) => b.pano.nivel - a.pano.nivel)[0];

    if (candidato) {
      semilla = candidato;
      return true;
    }

    return false;
  });

  if (!semilla) {
    semilla = activos
      .sort((a, b) => b.pano.nivel - a.pano.nivel)[0];
  }

  const familia = semilla.pano.familia;

  const familiaItems = panosRender
    .filter(
      item =>
        item.pano.familia === familia &&
        item.estadoVisual !== "SIN HORMIGONAR"
    )
    .sort((a, b) => b.pano.nivel - a.pano.nivel);

  const rows = familiaItems.slice(0, 4).map(item => ({
    nivelTxt: "N" + item.pano.nivel,
    label: item.pano.label,
    estado:
      item.estadoVisual === "DISPONIBLE PARA DESALZAPRIMAR"
        ? "DISP. DESCIMBRE"
        : item.estadoVisual === "DESALZAPRIMADA"
          ? "DESCIMBRADA"
          : item.estadoVisual,
    color: colorMap[item.estadoVisual] || "#DDE4EC"
  }));

  while (rows.length < 4) {
    rows.push({
      nivelTxt: "—",
      label: "—",
      estado: "—",
      color: "#DDE4EC"
    });
  }

  const fechas = familiaItems
    .map(item => item.fechaHormigonado)
    .filter(Boolean)
    .sort((a, b) => b.getTime() - a.getTime());

  return {
    rows: rows,
    ultimoHormigonado:
      fechas.length > 0
        ? vaFormatDate_(fechas[0])
        : "—"
  };

}


function vaBuildEstadoFechas_(
  panosRender
) {

  const resultado = {};

  const estados = [
    "FAENA ACTUAL",
    "100% ALZAPRIMAS",
    "50% ALZAPRIMAS",
    "DISPONIBLE PARA DESALZAPRIMAR",
    "DESALZAPRIMADA"
  ];

  estados.forEach(estado => {

    const fechas =
      panosRender
        .filter(
          item => item.estadoVisual === estado && item.fechaCumplimiento
        )
        .map(
          item => item.fechaCumplimiento
        )
        .sort(
          (a, b) => a.getTime() - b.getTime()
        );

    const key =
      estado === "DISPONIBLE PARA DESALZAPRIMAR"
        ? "DISPONIBLE"
        : estado === "DESALZAPRIMADA"
          ? "DESCIMBRADA"
          : estado;

    if (fechas.length === 0) {
      resultado[key] = "—";
    } else if (fechas.length === 1) {
      resultado[key] = vaFormatDate_(fechas[0]);
    } else {
      resultado[key] =
        vaFormatDate_(fechas[0]) +
        " a " +
        vaFormatDate_(fechas[fechas.length - 1]);
    }

  });

  return resultado;

}


function vaParseDate_(valor) {

  if (!valor) {
    return null;
  }

  if (
    Object.prototype.toString.call(valor) === '[object Date]' &&
    !isNaN(valor.getTime())
  ) {
    return valor;
  }

  const txt = String(valor).trim();

  if (!txt) {
    return null;
  }

  let m = txt.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})$/);
  if (m) {
    return new Date(Number(m[3]), Number(m[2]) - 1, Number(m[1]));
  }

  m = txt.match(/^(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})$/);
  if (m) {
    return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  }

  const d = new Date(txt);
  return isNaN(d.getTime()) ? null : d;

}


function vaFormatDate_(fecha) {

  if (!fecha) {
    return "—";
  }

  return Utilities.formatDate(
    fecha,
    Session.getScriptTimeZone(),
    "dd/MM/yyyy"
  );

}


/*
 * ============================================================
 * DIAGNÓSTICO
 * ============================================================
 */

function diagnosticarVistaAlzaprimas() {

  const ss =
    SpreadsheetApp
      .getActiveSpreadsheet();


  console.log(
    "===== HOJAS ====="
  );


  ss
    .getSheets()
    .forEach(
      sh =>
        console.log(
          sh.getName()
        )
    );


  console.log(
    "================="
  );

}


/*
 * OPCIONAL: programar una instantánea diaria de cierre.
 * Ejecutar UNA SOLA VEZ instalarSnapshotDiarioAlzaprimas() desde
 * Apps Script y autorizarla. Se conserva igualmente la función
 * actualizarVistaAlzaprimas() para las actualizaciones normales.
 *
 * Google aproxima el horario; se captura en torno a las 23:30
 * según la zona horaria configurada en el proyecto Apps Script.
 * Configurar la zona horaria del proyecto en America/Santiago.
 */
function snapshotAlzaprimasDiario() {
  actualizarVistaAlzaprimas();
}

function instalarSnapshotDiarioAlzaprimas() {
  const handler = "snapshotAlzaprimasDiario";
  const existente = ScriptApp.getProjectTriggers().some(
    trigger => trigger.getHandlerFunction() === handler
  );
  if (existente) {
    console.log("Ya existe el disparador diario de instantáneas.");
    return;
  }
  ScriptApp.newTrigger(handler)
    .timeBased()
    .everyDays(1)
    .atHour(23)
    .nearMinute(30)
    .inTimezone("America/Santiago")
    .create();
  console.log("Instantánea diaria programada alrededor de las 23:30 (Chile).");
}
