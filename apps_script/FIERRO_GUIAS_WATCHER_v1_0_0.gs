/**
 * FIERRO_GUIAS_WATCHER_v1_0_0.gs
 *
 * Revisa una carpeta de Google Drive y envía cada PDF nuevo al endpoint
 * /guia-fierro de Cloud Run.
 *
 * Script Properties requeridas:
 *   FIERRO_GUIAS_FOLDER_ID
 *   REPORT_WEBHOOK_TOKEN
 */

const FG_WATCHER_CONFIG = {
  CLOUD_RUN_BASE_URL:
    'https://informe-obra-gruesa-541351636997.southamerica-west1.run.app',
  PROCESS_PATH: '/guia-fierro',
  PING_PATH: '/ping',
  FOLDER_ID_PROPERTY: 'FIERRO_GUIAS_FOLDER_ID',
  TOKEN_PROPERTY: 'REPORT_WEBHOOK_TOKEN',
  MAX_FILES_PER_RUN: 20,
  LOCK_TIMEOUT_MS: 20000,
  SUCCESS_PREFIX: 'FIERRO_GUIA_OK_',
};


function procesarGuiasFierroDrive() {
  const lock = LockService.getScriptLock();

  if (!lock.tryLock(FG_WATCHER_CONFIG.LOCK_TIMEOUT_MS)) {
    Logger.log('Otro proceso de guías de fierro está en ejecución.');
    return {
      ok: false,
      skipped: true,
      reason: 'LOCKED',
    };
  }

  try {
    const properties = PropertiesService.getScriptProperties();
    const folderId = obtenerPropiedadGuiasFierro_(
      properties,
      FG_WATCHER_CONFIG.FOLDER_ID_PROPERTY
    );
    const token = obtenerPropiedadGuiasFierro_(
      properties,
      FG_WATCHER_CONFIG.TOKEN_PROPERTY
    );

    const folder = DriveApp.getFolderById(folderId);
    const files = folder.getFiles();

    let revisados = 0;
    let enviados = 0;
    let yaProcesados = 0;
    let errores = 0;

    while (
      files.hasNext() &&
      enviados < FG_WATCHER_CONFIG.MAX_FILES_PER_RUN
    ) {
      const file = files.next();
      if (!esPdfGuiaFierro_(file)) {
        continue;
      }

      revisados += 1;
      const successKey = claveExitoGuiaFierro_(file.getId());

      if (properties.getProperty(successKey) === 'OK') {
        yaProcesados += 1;
        continue;
      }

      try {
        const result = llamarCloudRunGuiaFierro_(file, token);
        Logger.log(
          'Guía fierro ' + file.getName() + ': ' + JSON.stringify(result)
        );
        properties.setProperty(successKey, 'OK');
        enviados += 1;
      } catch (error) {
        errores += 1;
        Logger.log(
          'ERROR guía fierro ' + file.getName() + ': ' + String(error)
        );
      }
    }

    const resumen = {
      ok: errores === 0,
      carpeta: folder.getName(),
      revisados: revisados,
      enviados: enviados,
      yaProcesados: yaProcesados,
      errores: errores,
    };

    Logger.log(JSON.stringify(resumen));
    return resumen;
  } finally {
    lock.releaseLock();
  }
}


function probarConexionGuiasFierro() {
  const properties = PropertiesService.getScriptProperties();
  const token = obtenerPropiedadGuiasFierro_(
    properties,
    FG_WATCHER_CONFIG.TOKEN_PROPERTY
  );

  const response = UrlFetchApp.fetch(
    FG_WATCHER_CONFIG.CLOUD_RUN_BASE_URL + FG_WATCHER_CONFIG.PING_PATH,
    {
      method: 'get',
      headers: {
        'X-Report-Token': token,
      },
      muteHttpExceptions: true,
    }
  );

  const code = response.getResponseCode();
  const body = response.getContentText();

  Logger.log('HTTP ' + code);
  Logger.log(body);

  if (code !== 200) {
    throw new Error('Cloud Run respondió HTTP ' + code + ': ' + body);
  }

  return JSON.parse(body);
}


function probarPrimeraGuiaFierro() {
  const properties = PropertiesService.getScriptProperties();
  const folderId = obtenerPropiedadGuiasFierro_(
    properties,
    FG_WATCHER_CONFIG.FOLDER_ID_PROPERTY
  );
  const token = obtenerPropiedadGuiasFierro_(
    properties,
    FG_WATCHER_CONFIG.TOKEN_PROPERTY
  );

  const folder = DriveApp.getFolderById(folderId);
  const files = folder.getFiles();

  while (files.hasNext()) {
    const file = files.next();
    if (!esPdfGuiaFierro_(file)) {
      continue;
    }

    const result = llamarCloudRunGuiaFierro_(file, token);
    Logger.log(JSON.stringify(result, null, 2));
    return result;
  }

  throw new Error('No se encontraron archivos PDF en FIERRO_GUIAS.');
}


function configurarTriggerGuiasFierro() {
  const functionName = 'procesarGuiasFierroDrive';

  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    if (trigger.getHandlerFunction() === functionName) {
      ScriptApp.deleteTrigger(trigger);
    }
  });

  ScriptApp.newTrigger(functionName)
    .timeBased()
    .everyMinutes(5)
    .create();

  Logger.log('Trigger creado: procesarGuiasFierroDrive cada 5 minutos.');
}


function reprocesarGuiaFierroPorId(fileId) {
  if (!fileId) {
    throw new Error('Debes indicar el ID Drive del PDF.');
  }

  const properties = PropertiesService.getScriptProperties();
  const token = obtenerPropiedadGuiasFierro_(
    properties,
    FG_WATCHER_CONFIG.TOKEN_PROPERTY
  );

  properties.deleteProperty(claveExitoGuiaFierro_(fileId));

  const file = DriveApp.getFileById(fileId);
  const result = llamarCloudRunGuiaFierro_(file, token);

  if (result && result.ok) {
    properties.setProperty(claveExitoGuiaFierro_(fileId), 'OK');
  }

  Logger.log(JSON.stringify(result, null, 2));
  return result;
}


function limpiarMarcasLocalesGuiasFierro() {
  const properties = PropertiesService.getScriptProperties();
  const all = properties.getProperties();
  let deleted = 0;

  Object.keys(all).forEach(function(key) {
    if (key.indexOf(FG_WATCHER_CONFIG.SUCCESS_PREFIX) === 0) {
      properties.deleteProperty(key);
      deleted += 1;
    }
  });

  Logger.log('Marcas locales eliminadas: ' + deleted);
  return deleted;
}


function llamarCloudRunGuiaFierro_(file, token) {
  const payload = {
    drive_file_id: file.getId(),
    nombre_archivo: file.getName(),
  };

  const response = UrlFetchApp.fetch(
    FG_WATCHER_CONFIG.CLOUD_RUN_BASE_URL +
      FG_WATCHER_CONFIG.PROCESS_PATH,
    {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify(payload),
      headers: {
        'X-Report-Token': token,
      },
      muteHttpExceptions: true,
    }
  );

  const code = response.getResponseCode();
  const body = response.getContentText();

  if (code < 200 || code >= 300) {
    throw new Error('Cloud Run HTTP ' + code + ': ' + body);
  }

  let result;
  try {
    result = JSON.parse(body);
  } catch (error) {
    throw new Error('Cloud Run no devolvió JSON válido: ' + body);
  }

  if (!result.ok) {
    throw new Error('Cloud Run respondió sin ok=true: ' + body);
  }

  return result;
}


function esPdfGuiaFierro_(file) {
  const mime = String(file.getMimeType() || '').toLowerCase();
  const name = String(file.getName() || '').toLowerCase();
  return mime === MimeType.PDF || name.endsWith('.pdf');
}


function obtenerPropiedadGuiasFierro_(properties, name) {
  const value = String(properties.getProperty(name) || '').trim();
  if (!value) {
    throw new Error('Falta Script Property: ' + name);
  }
  return value;
}


function claveExitoGuiaFierro_(fileId) {
  return FG_WATCHER_CONFIG.SUCCESS_PREFIX + fileId;
}
