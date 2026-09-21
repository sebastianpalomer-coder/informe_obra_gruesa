\
from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import requests


class AppSheetError(RuntimeError):
    pass


class AppSheetClient:
    def __init__(self) -> None:
        self.app_id = os.getenv("APPSHEET_APP_ID", "").strip()
        self.access_key = os.getenv("APPSHEET_ACCESS_KEY", "").strip()
        self.domain = os.getenv("APPSHEET_DOMAIN", "www.appsheet.com").strip()
        self.locale = os.getenv("APPSHEET_LOCALE", "en-US").strip()
        self.timezone = os.getenv("APPSHEET_TIMEZONE", "Pacific SA Standard Time").strip()

        if not self.app_id:
            raise AppSheetError("Falta APPSHEET_APP_ID.")
        if not self.access_key:
            raise AppSheetError("Falta APPSHEET_ACCESS_KEY.")

    def _url(self, table: str) -> str:
        table_encoded = quote(table, safe="")
        return (
            f"https://{self.domain}/api/v2/apps/{self.app_id}"
            f"/tables/{table_encoded}/Action"
        )

    def _post(self, table: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "ApplicationAccessKey": self.access_key,
            "Content-Type": "application/json",
        }

        response = requests.post(
            self._url(table),
            headers=headers,
            json=payload,
            timeout=120,
        )

        if not response.ok:
            raise AppSheetError(
                f"AppSheet {table}: HTTP {response.status_code}: "
                f"{response.text[:1500]}"
            )

        if not response.content:
            return {}

        try:
            return response.json()
        except Exception as exc:
            raise AppSheetError(
                f"AppSheet {table}: respuesta no JSON: {response.text[:1000]}"
            ) from exc

    def _properties(self) -> dict[str, Any]:
        return {
            "Locale": self.locale,
            "Timezone": self.timezone,
        }

    def find_rows(
        self,
        table: str,
        selector: str | None = None,
        key_rows: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        properties = self._properties()
        if selector:
            properties["Selector"] = selector

        payload = {
            "Action": "Find",
            "Properties": properties,
            "Rows": key_rows or [],
        }

        result = self._post(table, payload)
        rows = result.get("Rows", result if isinstance(result, list) else [])
        return rows if isinstance(rows, list) else []

    def find_by_key(
        self,
        table: str,
        key_name: str,
        key_value: Any,
    ) -> dict[str, Any]:
        rows = self.find_rows(
            table,
            key_rows=[{key_name: key_value}],
        )
        if not rows:
            raise AppSheetError(
                f"No se encontró {table}[{key_name}]={key_value!r}."
            )
        return rows[0]

    def edit_row(
        self,
        table: str,
        row: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "Action": "Edit",
            "Properties": self._properties(),
            "Rows": [row],
        }
        return self._post(table, payload)
