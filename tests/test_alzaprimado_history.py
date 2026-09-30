import unittest
from datetime import date, datetime
from unittest.mock import MagicMock

# Los tests de selección no necesitan credenciales ni Drive real.
# Permite correrlos también en un entorno mínimo sin SDK Google.
try:
    import google.auth
    from googleapiclient.discovery import build
except ModuleNotFoundError:
    import sys
    import types
    google_pkg = types.ModuleType("google")
    google_pkg.__path__ = []
    google_auth = types.ModuleType("google.auth")
    google_auth.default = MagicMock()
    google_pkg.auth = google_auth
    sys.modules["google"] = google_pkg
    sys.modules["google.auth"] = google_auth
    googleapi_pkg = types.ModuleType("googleapiclient")
    googleapi_pkg.__path__ = []
    api_discovery = types.ModuleType("googleapiclient.discovery")
    api_discovery.build = MagicMock()
    api_http = types.ModuleType("googleapiclient.http")
    api_http.MediaIoBaseDownload = MagicMock()
    api_http.MediaIoBaseUpload = MagicMock()
    sys.modules["googleapiclient"] = googleapi_pkg
    sys.modules["googleapiclient.discovery"] = api_discovery
    sys.modules["googleapiclient.http"] = api_http

from app.alzaprimado_history import (
    AlzaprimadoSnapshot, max_created_time_utc, select_snapshot,
)
from app.drive_client import DriveClient
from app.report_service import _load_media


def file(id_, stamp, created):
    return {
        "id": id_,
        "name": f"ALZAPRIMADO_V1_{stamp}.svg",
        "createdTime": created,
    }


class HistoricalSelectionTest(unittest.TestCase):
    def setUp(self):
        self.files = [
            file("older", "20260920_170000", "2026-09-20T20:00:00Z"),
            file("future", "20260925_172400", "2026-09-25T20:24:00Z"),
        ]

    def test_picks_last_captured_before_cutoff_not_latest(self):
        selected = select_snapshot(
            self.files, id_vista="V1", cutoff=date(2026, 9, 20),
        )
        self.assertEqual(selected.file_id, "older")
        self.assertEqual(selected.created_local.strftime("%d/%m/%Y %H:%M"), "20/09/2026 17:00")

    def test_no_archive_at_cutoff_never_falls_back_to_future(self):
        self.assertIsNone(select_snapshot(
            self.files[1:], id_vista="V1", cutoff=date(2026, 9, 20),
        ))

    def test_ignores_wrong_view_or_undated_or_future_backdated_name(self):
        candidates = self.files + [
            {"id": "x", "name": "ALZAPRIMADO_V2_20260919_100000.svg",
             "createdTime": "2026-09-19T13:00:00Z"},
            {"id": "x2", "name": "ALZAPRIMADO_V1_20260919_100000.svg",
             "createdTime": "2026-09-30T13:00:00Z"},
            {"id": "x3", "name": "ALZAPRIMADO_V1_20260919_100000.svg"},
        ]
        self.assertEqual(select_snapshot(
            candidates, id_vista="V1", cutoff=date(2026, 9, 20)
        ).file_id, "older")

    def test_picks_last_of_same_day_ms_suffix(self):
        files = self.files + [
            file("later", "20260920_233000_111", "2026-09-21T02:30:00Z"),
        ]
        self.assertEqual(select_snapshot(
            files, id_vista="V1", cutoff=date(2026, 9, 20)
        ).file_id, "later")

    def test_cutoff_exclusive_uses_local_midnight(self):
        # Septiembre corresponde a horario de verano (UTC-3 en Santiago).
        self.assertEqual(
            max_created_time_utc(date(2026, 9, 20), "America/Santiago"),
            "2026-09-21T03:00:00Z",
        )

    def test_drive_downloads_by_id_of_archived_not_current(self):
        drive = DriveClient.__new__(DriveClient)
        drive.svg_folder_id = "FOLDER"
        drive.service = MagicMock()
        drive.service.files.return_value.list.return_value.execute.side_effect = [
            {"nextPageToken": "more", "files": self.files[:1]},
            {"files": self.files[1:]},
        ]
        drive._download_file = MagicMock(return_value=(b"<svg></svg>", "image/svg+xml", "old.svg"))
        svg, snap = drive.historical_alzaprimado_svg(
            "V1", date(2026, 9, 20), "America/Santiago"
        )
        self.assertEqual(snap.file_id, "older")
        self.assertTrue(svg.startswith("data:image/svg+xml;base64,"))
        self.assertEqual(drive._download_file.call_args.args[0]["id"], "older")
        q = drive.service.files.return_value.list.call_args.kwargs["q"]
        self.assertIn("createdTime < '2026-09-21T03:00:00Z'", q)
        self.assertIn("'FOLDER' in parents", q)

    def test_page3_no_history_omits_current_image(self):
        drive = MagicMock()
        drive.historical_alzaprimado_svg.return_value = None
        svg, photos, warnings, meta = _load_media(
            drive=drive, vista={"ID_VISTA": "V1", "SVG_URI": "SVG_Alzaprimado/NEW.svg"},
            photos=[], floor_map={}, cutoff=date(2026, 9, 20),
        )
        self.assertIsNone(svg)
        self.assertEqual(photos, [])
        self.assertTrue(any("se omitió" in w for w in warnings))
        drive.data_uri_svg.assert_not_called()
        self.assertIsNone(meta["fecha"])

    def test_page3_historical_label_follows_snapshot_date(self):
        drive = MagicMock()
        dt = datetime.fromisoformat("2026-09-20T17:00:00-03:00")
        drive.historical_alzaprimado_svg.return_value = (
            "data:image/svg+xml;base64,MTIz",
            AlzaprimadoSnapshot("id", "ALZAPRIMADO_V1_20260920_170000.svg", dt),
        )
        svg, _photos, warnings, meta = _load_media(
            drive, {"ID_VISTA": "V1", "SVG_URI": "NEW.svg"}, [], {}, date(2026, 9, 20)
        )
        self.assertTrue(svg)
        self.assertEqual(meta["fecha"], "20/09/2026 17:00")
        self.assertEqual(warnings, [])
        drive.data_uri_svg.assert_not_called()


if __name__ == "__main__":
    unittest.main()
