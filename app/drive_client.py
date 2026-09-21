\
from __future__ import annotations

import base64
import io
import os
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import google.auth
import requests
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload


FOLDER_MIME = "application/vnd.google-apps.folder"


class DriveError(RuntimeError):
    pass


@dataclass
class DriveUploadResult:
    file_id: str
    name: str
    relative_path: str
    web_view_link: str | None


class DriveClient:
    def __init__(self) -> None:
        self.root_folder_id = os.getenv("APP_ROOT_FOLDER_ID", "").strip()
        self.report_folder_name = os.getenv(
            "REPORT_FOLDER_NAME",
            "INFORMES_SEMANALES",
        ).strip() or "INFORMES_SEMANALES"

        if not self.root_folder_id:
            raise DriveError("Falta APP_ROOT_FOLDER_ID.")

        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        self.service = build(
            "drive",
            "v3",
            credentials=credentials,
            cache_discovery=False,
        )

    @staticmethod
    def _q_escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "\\'")

    def _find_child(
        self,
        parent_id: str,
        name: str,
        mime_type: str | None = None,
    ) -> dict[str, Any] | None:
        escaped = self._q_escape(name)
        q = (
            f"'{parent_id}' in parents and "
            f"name = '{escaped}' and trashed = false"
        )
        if mime_type:
            q += f" and mimeType = '{self._q_escape(mime_type)}'"

        result = self.service.files().list(
            q=q,
            spaces="drive",
            fields="files(id,name,mimeType,webViewLink)",
            pageSize=50,
        ).execute()

        files = result.get("files", [])
        return files[0] if files else None

    @staticmethod
    def _drive_id_from_url(value: str) -> str | None:
        patterns = [
            r"/d/([A-Za-z0-9_-]+)",
            r"[?&]id=([A-Za-z0-9_-]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, value)
            if match:
                return match.group(1)
        return None

    def resolve_path(self, value: str) -> dict[str, Any]:
        if not value:
            raise DriveError("Ruta de archivo vacía.")

        text = str(value).strip()

        if text.startswith("http://") or text.startswith("https://"):
            drive_id = self._drive_id_from_url(text)
            if drive_id:
                return self.service.files().get(
                    fileId=drive_id,
                    fields="id,name,mimeType,webViewLink",
                ).execute()

            # URL no Drive: se maneja fuera de Drive.
            return {
                "id": "",
                "name": text.rsplit("/", 1)[-1] or "archivo",
                "mimeType": "",
                "external_url": text,
            }

        normalized = text.replace("\\", "/").lstrip("/")
        parts = [p for p in PurePosixPath(normalized).parts if p not in ("", ".")]
        if not parts:
            raise DriveError(f"Ruta inválida: {value!r}")

        parent = self.root_folder_id

        for folder_name in parts[:-1]:
            child = self._find_child(parent, folder_name, FOLDER_MIME)
            if not child:
                raise DriveError(
                    f"No se encontró la carpeta '{folder_name}' "
                    f"dentro de la ruta '{value}'."
                )
            parent = child["id"]

        file_name = parts[-1]
        result = self._find_child(parent, file_name)
        if not result:
            raise DriveError(
                f"No se encontró el archivo '{file_name}' "
                f"en la ruta '{value}'."
            )
        return result

    def download(self, value: str) -> tuple[bytes, str, str]:
        meta = self.resolve_path(value)

        if meta.get("external_url"):
            response = requests.get(meta["external_url"], timeout=90)
            response.raise_for_status()
            mime = response.headers.get(
                "Content-Type",
                "application/octet-stream",
            ).split(";")[0]
            return response.content, mime, meta["name"]

        file_id = meta["id"]
        mime_type = meta.get("mimeType", "application/octet-stream")
        name = meta.get("name", "archivo")

        request = self.service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)

        done = False
        while not done:
            _, done = downloader.next_chunk()

        return buffer.getvalue(), mime_type, name

    def data_uri(self, value: str) -> str:
        content, mime, _ = self.download(value)
        encoded = base64.b64encode(content).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    def _ensure_report_folder(self) -> str:
        folder = self._find_child(
            self.root_folder_id,
            self.report_folder_name,
            FOLDER_MIME,
        )
        if folder:
            return folder["id"]

        created = self.service.files().create(
            body={
                "name": self.report_folder_name,
                "mimeType": FOLDER_MIME,
                "parents": [self.root_folder_id],
            },
            fields="id,name",
        ).execute()

        return created["id"]

    def upload_or_replace_pdf(
        self,
        pdf_bytes: bytes,
        filename: str,
    ) -> DriveUploadResult:
        folder_id = self._ensure_report_folder()
        existing = self._find_child(folder_id, filename)

        media = MediaIoBaseUpload(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            resumable=False,
        )

        if existing:
            uploaded = self.service.files().update(
                fileId=existing["id"],
                media_body=media,
                fields="id,name,webViewLink",
            ).execute()
        else:
            uploaded = self.service.files().create(
                body={
                    "name": filename,
                    "parents": [folder_id],
                },
                media_body=media,
                fields="id,name,webViewLink",
            ).execute()

        relative = f"{self.report_folder_name}/{filename}"

        return DriveUploadResult(
            file_id=uploaded["id"],
            name=uploaded["name"],
            relative_path=relative,
            web_view_link=uploaded.get("webViewLink"),
        )
