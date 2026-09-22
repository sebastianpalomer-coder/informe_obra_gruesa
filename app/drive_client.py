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
        # Compatibilidad: si PHOTO_FOLDER_ID no está definido,
        # se usa APP_ROOT_FOLDER_ID como carpeta de fotografías.
        self.photo_folder_id = (
            os.getenv("PHOTO_FOLDER_ID", "").strip()
            or os.getenv("APP_ROOT_FOLDER_ID", "").strip()
        )

        self.svg_folder_id = os.getenv(
            "SVG_FOLDER_ID",
            "",
        ).strip()

        self.report_folder_id = os.getenv(
            "REPORT_FOLDER_ID",
            "",
        ).strip()

        # Ruta relativa que se escribirá en INFORME[ARCHIVO_INFORME].
        # Debe coincidir con la ubicación que AppSheet reconoce
        # respecto de la carpeta del archivo fuente.
        self.report_appsheet_path = os.getenv(
            "REPORT_APPSHEET_PATH",
            "INFORMES_SEMANALES",
        ).strip().strip("/")

        # Fallback V1.0, por si REPORT_FOLDER_ID todavía no existe.
        self.root_folder_id = os.getenv(
            "APP_ROOT_FOLDER_ID",
            "",
        ).strip()

        self.report_folder_name = os.getenv(
            "REPORT_FOLDER_NAME",
            "INFORMES_SEMANALES",
        ).strip() or "INFORMES_SEMANALES"

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

    @staticmethod
    def _basename(value: str) -> str:
        normalized = str(value).replace("\\", "/").strip()
        return PurePosixPath(normalized).name

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

    def resolve_path_from_root(
        self,
        value: str,
    ) -> dict[str, Any]:
        if not value:
            raise DriveError("Ruta de archivo vacía.")

        if not self.root_folder_id:
            raise DriveError(
                "Falta APP_ROOT_FOLDER_ID para resolver una ruta relativa."
            )

        text = str(value).strip()

        if text.startswith("http://") or text.startswith("https://"):
            drive_id = self._drive_id_from_url(text)

            if drive_id:
                return self.service.files().get(
                    fileId=drive_id,
                    fields="id,name,mimeType,webViewLink",
                ).execute()

            return {
                "id": "",
                "name": text.rsplit("/", 1)[-1] or "archivo",
                "mimeType": "",
                "external_url": text,
            }

        normalized = text.replace("\\", "/").lstrip("/")

        parts = [
            p
            for p in PurePosixPath(normalized).parts
            if p not in ("", ".")
        ]

        if not parts:
            raise DriveError(f"Ruta inválida: {value!r}")

        parent = self.root_folder_id

        for folder_name in parts[:-1]:
            child = self._find_child(
                parent,
                folder_name,
                FOLDER_MIME,
            )

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

    def resolve_file_in_folder(
        self,
        folder_id: str,
        file_name_or_path: str,
    ) -> dict[str, Any]:
        if not folder_id:
            raise DriveError("ID de carpeta vacío.")

        file_name = self._basename(file_name_or_path)

        result = self._find_child(
            folder_id,
            file_name,
        )

        if not result:
            raise DriveError(
                f"No se encontró '{file_name}' "
                f"en la carpeta Drive {folder_id}."
            )

        return result

    def _download_file(
        self,
        meta: dict[str, Any],
    ) -> tuple[bytes, str, str]:
        if meta.get("external_url"):
            response = requests.get(
                meta["external_url"],
                timeout=90,
            )
            response.raise_for_status()

            mime = response.headers.get(
                "Content-Type",
                "application/octet-stream",
            ).split(";")[0]

            return (
                response.content,
                mime,
                meta["name"],
            )

        file_id = meta["id"]
        mime_type = meta.get(
            "mimeType",
            "application/octet-stream",
        )
        name = meta.get(
            "name",
            "archivo",
        )

        request = self.service.files().get_media(
            fileId=file_id
        )

        buffer = io.BytesIO()

        downloader = MediaIoBaseDownload(
            buffer,
            request,
        )

        done = False

        while not done:
            _, done = downloader.next_chunk()

        return (
            buffer.getvalue(),
            mime_type,
            name,
        )

    @staticmethod
    def _as_data_uri(
        content: bytes,
        mime: str,
    ) -> str:
        encoded = base64.b64encode(
            content
        ).decode("ascii")

        return f"data:{mime};base64,{encoded}"

    def data_uri(
        self,
        value: str,
    ) -> str:
        meta = self.resolve_path_from_root(
            value
        )

        content, mime, _ = self._download_file(
            meta
        )

        return self._as_data_uri(
            content,
            mime,
        )

    def data_uri_from_folder(
        self,
        folder_id: str,
        file_name_or_path: str,
    ) -> str:
        meta = self.resolve_file_in_folder(
            folder_id,
            file_name_or_path,
        )

        content, mime, _ = self._download_file(
            meta
        )

        return self._as_data_uri(
            content,
            mime,
        )

    def data_uri_photo(
        self,
        image_path: str,
    ) -> str:
        """
        Busca directamente la fotografía dentro de PHOTO_FOLDER_ID.
        Si PHOTO_FOLDER_ID no está configurado, usa el mecanismo
        compatible de APP_ROOT_FOLDER_ID.
        """

        if self.photo_folder_id:
            return self.data_uri_from_folder(
                self.photo_folder_id,
                image_path,
            )

        return self.data_uri(
            image_path
        )

    def data_uri_svg(
        self,
        svg_path: str,
    ) -> str:
        """
        Busca el SVG directamente dentro de SVG_FOLDER_ID.
        VISTA_ALZAPRIMADO[SVG_URI] puede contener:
        SVG_Alzaprimado/ALZAPRIMADO_xxx.svg
        """

        if self.svg_folder_id:
            return self.data_uri_from_folder(
                self.svg_folder_id,
                svg_path,
            )

        return self.data_uri(
            svg_path
        )

    def _ensure_report_folder_legacy(
        self,
    ) -> str:
        if not self.root_folder_id:
            raise DriveError(
                "Falta REPORT_FOLDER_ID y también APP_ROOT_FOLDER_ID."
            )

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

    def _report_folder(self) -> str:
        if self.report_folder_id:
            return self.report_folder_id

        return self._ensure_report_folder_legacy()

    def upload_or_replace_pdf(
        self,
        pdf_bytes: bytes,
        filename: str,
    ) -> DriveUploadResult:
        folder_id = self._report_folder()

        existing = self._find_child(
            folder_id,
            filename,
        )

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

        if self.report_appsheet_path:
            relative_path = (
                f"{self.report_appsheet_path}/"
                f"{filename}"
            )
        else:
            relative_path = filename

        return DriveUploadResult(
            file_id=uploaded["id"],
            name=uploaded["name"],
            relative_path=relative_path,
            web_view_link=uploaded.get("webViewLink"),
        )
