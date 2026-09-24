/**
 * ============================================================
 * INFORMES OBRA - DRIVE WRITER
 * Version: 1.1.0
 * ============================================================
 *
 * Recibe PDFs desde Cloud Run y los guarda en carpetas de Mi unidad.
 *
 * PROPIEDADES DEL SCRIPT:
 *
 * REPORT_WRITER_TOKEN
 * REPORT_FOLDER_ID
 * DAILY_REPORT_FOLDER_ID
 *
 * folder_key admitidos:
 *
 * weekly       -> REPORT_FOLDER_ID
 * daily_photos -> DAILY_REPORT_FOLDER_ID
 */


const WRITER_VERSION = "1.1.0";


function doGet() {

  return jsonResponse_({
    ok: true,
    service: "informes-obra-drive-writer",
    version: WRITER_VERSION
  });

}


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


    if (!expectedToken) {

      return jsonResponse_({
        ok: false,
        error:
          "Falta REPORT_WRITER_TOKEN "
          + "en Propiedades del script."
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


    const folderKey =
      String(
        payload.folder_key || "weekly"
      ).trim();


    const folderId =
      resolveFolderId_(
        properties,
        folderKey
      );


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
     * si existe un archivo anterior con igual nombre,
     * se envía a papelera.
     */
    const existing =
      folder.getFilesByName(
        filename
      );


    while (
      existing.hasNext()
    ) {

      existing
        .next()
        .setTrashed(
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
      folder_key: folderKey,
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


function resolveFolderId_(
  properties,
  folderKey
) {

  let propertyName;


  if (
    folderKey === "weekly"
  ) {

    propertyName =
      "REPORT_FOLDER_ID";

  } else if (
    folderKey === "daily_photos"
  ) {

    propertyName =
      "DAILY_REPORT_FOLDER_ID";

  } else {

    throw new Error(
      "folder_key no permitido: "
      + folderKey
    );

  }


  const folderId =
    String(
      properties.getProperty(
        propertyName
      ) || ""
    ).trim();


  if (!folderId) {

    throw new Error(
      "Falta "
      + propertyName
      + " en Propiedades del script."
    );

  }


  return folderId;

}


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


function jsonResponse_(data) {

  return ContentService
    .createTextOutput(
      JSON.stringify(data)
    )
    .setMimeType(
      ContentService.MimeType.JSON
    );

}
