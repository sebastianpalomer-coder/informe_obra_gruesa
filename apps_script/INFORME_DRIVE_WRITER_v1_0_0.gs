/**
 * ============================================================
 * INFORME SEMANAL OBRA GRUESA - DRIVE WRITER
 * Version: 1.0.0
 * ============================================================
 *
 * Objetivo:
 * Recibir desde Cloud Run un PDF en Base64 y guardarlo/reemplazarlo
 * dentro de una carpeta de "Mi unidad".
 *
 * IMPORTANTE:
 * Este Web App debe desplegarse con:
 *
 *   Ejecutar como: YO
 *   Quién tiene acceso: Cualquiera
 *
 * La seguridad se controla mediante REPORT_WRITER_TOKEN, almacenado
 * en Propiedades del script. El token viaja dentro del JSON POST.
 *
 * Propiedades del script requeridas:
 *
 *   REPORT_FOLDER_ID
 *   REPORT_WRITER_TOKEN
 *
 * REPORT_FOLDER_ID debe ser el ID de la carpeta:
 *   INFORMES_SEMANALES
 *
 * No es necesario habilitar Drive API avanzada.
 * Se utiliza DriveApp.
 */


const WRITER_VERSION = "1.0.0";


/**
 * Endpoint simple para comprobar que el Web App está activo.
 */
function doGet() {

  return jsonResponse_({
    ok: true,
    service: "informe-semanal-drive-writer",
    version: WRITER_VERSION
  });

}


/**
 * Recibe:
 *
 * {
 *   "token": "...",
 *   "filename": "Informe_Semanal_OG_xxx.pdf",
 *   "content_type": "application/pdf",
 *   "content_base64": "JVBERi0xLjc..."
 * }
 */
function doPost(e) {

  try {

    if (
      !e ||
      !e.postData ||
      !e.postData.contents
    ) {

      return jsonResponse_({
        ok: false,
        error: "Solicitud POST sin body."
      });

    }


    const payload =
      JSON.parse(
        e.postData.contents
      );


    const properties =
      PropertiesService
        .getScriptProperties();


    const expectedToken =
      String(
        properties.getProperty(
          "REPORT_WRITER_TOKEN"
        ) || ""
      ).trim();


    const folderId =
      String(
        properties.getProperty(
          "REPORT_FOLDER_ID"
        ) || ""
      ).trim();


    if (!expectedToken) {

      return jsonResponse_({
        ok: false,
        error:
          "Falta REPORT_WRITER_TOKEN en Propiedades del script."
      });

    }


    if (!folderId) {

      return jsonResponse_({
        ok: false,
        error:
          "Falta REPORT_FOLDER_ID en Propiedades del script."
      });

    }


    const receivedToken =
      String(
        payload.token || ""
      ).trim();


    if (
      !receivedToken ||
      receivedToken !== expectedToken
    ) {

      return jsonResponse_({
        ok: false,
        error: "Token inválido."
      });

    }


    const filename =
      sanitizeFilename_(
        payload.filename
      );


    if (!filename) {

      return jsonResponse_({
        ok: false,
        error: "filename vacío o inválido."
      });

    }


    if (
      !filename
        .toLowerCase()
        .endsWith(".pdf")
    ) {

      return jsonResponse_({
        ok: false,
        error:
          "Solo se permiten archivos PDF."
      });

    }


    const base64Content =
      String(
        payload.content_base64 || ""
      ).trim();


    if (!base64Content) {

      return jsonResponse_({
        ok: false,
        error: "content_base64 vacío."
      });

    }


    const bytes =
      Utilities.base64Decode(
        base64Content
      );


    if (
      !bytes ||
      bytes.length === 0
    ) {

      return jsonResponse_({
        ok: false,
        error:
          "El PDF recibido está vacío."
      });

    }


    const folder =
      DriveApp.getFolderById(
        folderId
      );


    /*
     * Reemplazo determinístico:
     * si existe un archivo anterior con el mismo nombre,
     * se envía a la papelera antes de crear el nuevo.
     */
    const existing =
      folder.getFilesByName(
        filename
      );


    while (
      existing.hasNext()
    ) {

      const oldFile =
        existing.next();


      oldFile.setTrashed(
        true
      );

    }


    const blob =
      Utilities.newBlob(
        bytes,
        "application/pdf",
        filename
      );


    const file =
      folder.createFile(
        blob
      );


    return jsonResponse_({
      ok: true,
      version: WRITER_VERSION,
      file_id: file.getId(),
      name: file.getName(),
      web_view_link: file.getUrl(),
      size_bytes: bytes.length
    });


  } catch (error) {

    return jsonResponse_({
      ok: false,
      error:
        error && error.message
          ? error.message
          : String(error)
    });

  }

}


/**
 * Elimina rutas y caracteres problemáticos.
 */
function sanitizeFilename_(value) {

  let filename =
    String(
      value || ""
    )
      .replace(/\\/g, "/")
      .split("/")
      .pop()
      .trim();


  filename =
    filename.replace(
      /[\u0000-\u001F<>:"|?*]/g,
      "_"
    );


  return filename;

}


/**
 * Respuesta JSON estándar.
 */
function jsonResponse_(data) {

  return ContentService
    .createTextOutput(
      JSON.stringify(data)
    )
    .setMimeType(
      ContentService.MimeType.JSON
    );

}
