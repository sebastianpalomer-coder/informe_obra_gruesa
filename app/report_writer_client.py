from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Any

import requests


class ReportWriterError(RuntimeError):
    pass


@dataclass
class ReportWriterResult:
    file_id: str
    name: str
    relative_path: str
    web_view_link: str | None


class ReportWriterClient:
    """
    Envía PDFs generados por Cloud Run al Google Apps Script Web App.

    El Web App se ejecuta como el propietario humano del script y puede
    escribir en carpetas de "Mi unidad".

    V1.3:
    admite destinos lógicos:
    - weekly       -> REPORT_FOLDER_ID
    - daily_photos -> DAILY_REPORT_FOLDER_ID
    """

    def __init__(self) -> None:
        self.writer_url = os.getenv(
            "REPORT_WRITER_URL",
            "",
        ).strip()

        self.writer_token = os.getenv(
            "REPORT_WRITER_TOKEN",
            "",
        ).strip()

        self.weekly_appsheet_path = os.getenv(
            "REPORT_APPSHEET_PATH",
            "INFORMES_SEMANALES",
        ).strip().strip("/")

        self.daily_appsheet_path = os.getenv(
            "DAILY_REPORT_APPSHEET_PATH",
            "REPORTES_FOTOGRAFICOS_DIARIOS",
        ).strip().strip("/")

        if not self.writer_url:
            raise ReportWriterError(
                "Falta REPORT_WRITER_URL en Cloud Run."
            )

        if not self.writer_token:
            raise ReportWriterError(
                "Falta REPORT_WRITER_TOKEN en Cloud Run."
            )

    def upload_or_replace_pdf(
        self,
        pdf_bytes: bytes,
        filename: str,
        *,
        folder_key: str = "weekly",
        appsheet_path: str | None = None,
    ) -> ReportWriterResult:
        payload = {
            "token": self.writer_token,
            "folder_key": folder_key,
            "filename": filename,
            "content_type": "application/pdf",
            "content_base64": base64.b64encode(
                pdf_bytes
            ).decode("ascii"),
        }

        try:
            response = requests.post(
                self.writer_url,
                json=payload,
                timeout=180,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            raise ReportWriterError(
                f"No fue posible conectar con Apps Script: {exc}"
            ) from exc

        if not response.ok:
            raise ReportWriterError(
                f"Apps Script Writer HTTP {response.status_code}: "
                f"{response.text[:1500]}"
            )

        try:
            result: Any = response.json()
        except Exception as exc:
            raise ReportWriterError(
                "Apps Script Writer devolvió una respuesta no JSON: "
                f"{response.text[:1500]}"
            ) from exc

        if not isinstance(result, dict):
            raise ReportWriterError(
                "Apps Script Writer devolvió un formato inesperado."
            )

        if not result.get("ok"):
            message = (
                result.get("error")
                or result.get("message")
                or "Error desconocido en Apps Script Writer."
            )
            raise ReportWriterError(str(message))

        file_id = str(result.get("file_id", "")).strip()
        name = str(result.get("name", filename)).strip() or filename
        web_view_link = (
            str(result.get("web_view_link", "")).strip()
            or None
        )

        if not file_id:
            raise ReportWriterError(
                "Apps Script Writer no devolvió file_id."
            )

        if appsheet_path is None:
            if folder_key == "daily_photos":
                appsheet_path = self.daily_appsheet_path
            else:
                appsheet_path = self.weekly_appsheet_path

        clean_path = str(appsheet_path or "").strip().strip("/")

        relative_path = (
            f"{clean_path}/{name}"
            if clean_path
            else name
        )

        return ReportWriterResult(
            file_id=file_id,
            name=name,
            relative_path=relative_path,
            web_view_link=web_view_link,
        )
