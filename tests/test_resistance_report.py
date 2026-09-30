import unittest
from datetime import date

from app.resistance_report import build_resistance_report


def sample(key, grade, when, c, indiv=None, moving=None, expected=None):
    return {
        "ID_MUESTRA": f"M-{key}", "ID_GUIA": key,
        "ID_CERTIFICADO": c, "ID_VISITA": f"V-{key}", "Grado del Hormigon": grade,
        "Fecha_Toma_Muestra": when, "Resistencia_Individual": indiv,
        "Resis_Media_Movil": moving,
        "Resis_Indiv_Minima": 26 if grade == "G20" else 29,
        "Resis_movil_minima": 28 if grade == "G20" else 31,
        "resistencia_Esperada": expected,
        "CERTIFICADO_FINAL_28D": bool(indiv),
    }


def cert(key, guide, when, r7, a=None, b=None):
    return {
        "ID_CERTIFICADO": key, "ID_GUIA": guide,
        "FECHA_REGISTRO": when,
        "FECHA_CERTIFICADO": when[:10],
        "R_7_DIAS": r7, "R_28_DIAS_1": a, "R_28_DIAS_2": b,
    }


class ResistanceReportTest(unittest.TestCase):
    def setUp(self):
        self.rows = [
            sample("G1", "G20", "08/01/2026", "C1F", 25.5),
            sample("G2", "G20", "08/07/2026", "C2F", 27.5),
            sample("G3", "G20", "08/09/2026", "C3F", 28.0, moving=27.0),
            sample("G4", "G20", "08/15/2026", "C4P", None, expected=24),
            sample("G5", "G30", "09/10/2026", "C5F", 33),
        ]
        self.certs = [
            cert("C1P", "G1", "2026-08-10T10:00:00", 19),
            cert("C1F", "G1", "2026-09-01T10:00:00", 19, 25, 26),
            cert("C2F", "G2", "2026-09-08T10:00:00", 21, 27, 28),
            cert("C3F", "G3", "2026-09-10T10:00:00", 22, 28, 28),
            cert("C4P", "G4", "2026-08-23T10:00:00", 18),
            cert("C5F", "G5", "2026-09-28T10:00:00", 24, 33, 33),
        ]
        self.visits = [
            {"ID_VISITA": "V-G1", "ID_GUIA": "G1", "PISO": "PISO5",
             "ELEMENTO": "Muro", "DESCRIPCION_SECTOR": "Ejes A/3"},
            {"ID_VISITA": "V-G2", "ID_GUIA": "G2", "PISO": "PISO4",
             "ELEMENTO": "Losa", "DESCRIPCION_SECTOR": "Ejes B/7"},
        ]
        self.guides = [
            {"ID_REGISTRO": "G1", "FOLIO": "1001", "PISO": "PISO4"},
            {"ID_REGISTRO": "G2", "FOLIO": "1002", "PISO": "PISO4"},
            {"ID_REGISTRO": "G3", "FOLIO": "1003", "PISO": "PISO5"},
            {"ID_REGISTRO": "G4", "FOLIO": "1004", "PISO": "PISO6"},
        ]

    def test_full_window(self):
        report = build_resistance_report(
            self.rows, self.certs, self.guides, {"PISO4": "4", "PISO5": "5"},
            date(2026, 9, 30), date(2026, 9, 24), visit_rows=self.visits,
        )
        self.assertEqual(report["summary"]["taken"], 5)
        self.assertEqual(report["summary"]["final"], 4)
        self.assertEqual(report["summary"]["overdue"], 1)
        self.assertEqual(report["summary"]["individual_failures"], 1)
        self.assertEqual(report["summary"]["moving_failures"], 1)
        self.assertEqual(report["summary"]["week_results"], 1)
        g20, g30 = report["grades"]
        self.assertEqual((g20["grade"], g30["grade"]), ("G20", "G30"))
        self.assertAlmostEqual(g20["moving"][0]["value"], 27)
        self.assertEqual(g20["moving"][0]["guides"], "1001 / 1002 / 1003")
        self.assertEqual(g20["individual_failures"][0]["floor"], "5")
        self.assertEqual(g20["individual_failures"][0]["location"], "Muro / Ejes A/3")
        self.assertEqual(g20["summary"]["projection_alerts"], 1)
        self.assertEqual(g20["overdue"][0]["guia"], "1004")
        self.assertEqual(g30["summary"]["moving_failures"], 0)

    def test_prior_cutoff_never_uses_future_certificate_virtual_values(self):
        report = build_resistance_report(
            self.rows, self.certs, self.guides, {}, date(2026, 8, 31), date(2026, 8, 24)
        )
        self.assertEqual([x["grade"] for x in report["grades"]], ["G20"])
        g20 = report["grades"][0]
        self.assertEqual(g20["summary"]["final"], 0)
        self.assertEqual(g20["summary"]["pending"], 4)
        self.assertEqual(g20["moving"], [])
        self.assertEqual(g20["individual_failures"], [])
        # C1 tiene resultado preliminar al 31/08 aun si el Ref actual apunta a C1F.
        self.assertEqual(g20["samples"][0]["r7"], 19)

    def test_missing_threshold_not_silently_compliant(self):
        self.rows[0]["Resis_Indiv_Minima"] = None
        report = build_resistance_report(
            self.rows, self.certs, self.guides, {}, date(2026, 9, 30)
        )
        self.assertEqual(report["summary"]["individual_failures"], 0)
        self.assertTrue(any("sin Resis_Indiv_Minima" in w for w in report["grades"][0]["warnings"]))

    def test_visit_from_id_is_authoritative_and_guide_fallback_is_safe(self):
        visits = [
            {"ID_VISITA": "V-G1", "ID_GUIA": "G1", "PISO": "PISO5", "ELEMENTO": "Muro",
             "DESCRIPCION_SECTOR": "Ejes A/3"},
            {"ID_VISITA": "V-G2", "ID_GUIA": "G2", "PISO": "PISO4", "ELEMENTO": "Losa",
             "DESCRIPCION_SECTOR": "Ejes B/7"},
            {"ID_VISITA": "V-OTHER", "ID_GUIA": "G2", "PISO": "PISO6", "ELEMENTO": "Viga"},
        ]
        report = build_resistance_report(
            self.rows, self.certs, self.guides, {"PISO5": "5", "PISO4": "4"},
            date(2026, 9, 30), visit_rows=visits,
        )
        g20 = report["grades"][0]
        self.assertEqual(g20["samples"][0]["location"], "Muro / Ejes A/3")
        self.assertEqual(g20["samples"][1]["location"], "Losa / Ejes B/7")
        self.assertTrue(any("varias visitas" in w for w in report["warnings"]))

    def test_mismatched_visit_does_not_use_unrelated_location(self):
        visits = [{"ID_VISITA": "V-G1", "ID_GUIA": "DIFFERENT", "PISO": "PISO9",
                   "ELEMENTO": "Incorrecto"}]
        report = build_resistance_report(
            self.rows, self.certs, self.guides, {"PISO4": "4"},
            date(2026, 9, 30), visit_rows=visits,
        )
        g20 = report["grades"][0]
        self.assertNotIn("Incorrecto", g20["samples"][0]["location"])
        self.assertTrue(any("diferente" in w for w in report["warnings"]))

    def test_element_and_floor_refs_resolve_to_visible_labels(self):
        self.visits[0]["ELEMENTO"] = "ELM001"
        report = build_resistance_report(
            self.rows, self.certs, self.guides,
            {"PISO5": "Quinto piso", "PISO4": "Cuarto piso"},
            date(2026, 9, 30), visit_rows=self.visits,
            element_map={"ELM001": "Muro estructural"},
        )
        sample = report["grades"][0]["samples"][0]
        self.assertEqual(sample["floor"], "Quinto piso")
        self.assertEqual(sample["location"], "Muro estructural / Ejes A/3")

    def test_unknown_element_ref_falls_back_without_dropping_sector(self):
        self.visits[0]["ELEMENTO"] = "ELM999"
        report = build_resistance_report(
            self.rows, self.certs, self.guides, {"PISO5": "Quinto piso"},
            date(2026, 9, 30), visit_rows=self.visits,
            element_map={"ELM001": "Muro estructural"},
        )
        sample = report["grades"][0]["samples"][0]
        self.assertEqual(sample["location"], "ELM999 / Ejes A/3")

    def test_without_registration_date_explicit_warning(self):
        for c in self.certs:
            c.pop("FECHA_REGISTRO")
        report = build_resistance_report(
            self.rows, self.certs, self.guides, {}, date(2026, 9, 30)
        )
        self.assertTrue(report["historical_estimated"])
        self.assertTrue(any("FECHA_REGISTRO" in w for w in report["warnings"]))


if __name__ == "__main__":
    unittest.main()
