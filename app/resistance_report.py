"""Control de resistencia por muestra/grado para el informe semanal.

Principios:
- una observación = promedio de dos testigos definitivos a 28 días;
- la media móvil usa TRES observaciones definitivas del mismo grado;
- la proyección a 7 días NUNCA participa de los ensayos definitivos;
- el corte histórico usa el registro de certificados, no únicamente el Ref
  mutable TABLA_RESISTENCIA[ID_CERTIFICADO].
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
import math
import re
from typing import Any

from .formatters import parse_appsheet_date, to_float_or_none


def _get(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def _yes(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"true", "yes", "1", "si", "sí"}


def _grade(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().upper())


def _grade_sort(value: str):
    match = re.search(r"(\d+(?:[.,]\d+)?)", value)
    return (0, float(match.group(1).replace(",", ".")), value) if match else (1, value)


def _natural_key(value: str):
    return tuple((1, int(part)) if part.isdigit() else (0, part.casefold())
                 for part in re.split(r"(\d+)", str(value)))


def _valid_limit(value: Any) -> float | None:
    n = to_float_or_none(value)
    return n if n is not None and math.isfinite(n) and n > 0 else None


def _location(
    row: dict[str, Any],
    visit: dict[str, Any],
    guide: dict[str, Any],
    cert: dict[str, Any],
    floor_map: dict[str, Any],
    element_map: dict[str, str] | None = None,
):
    """Ubicación de la visita de muestreo (fuente prioritaria).

    TABLA_VISITA_TOMA_MUESTRA[PISO] y [ELEMENTO] son referencias de
    AppSheet: PISO se resuelve con PISOS[ID_PISO] -> PISOS[PISO];
    ELEMENTO se resuelve con ELEMENTOS[ID_ELEMENTOS] -> ELEMENTOS[ELEMENTO].
    """
    def first(fields, sources):
        for source in sources:
            result = _get(source, *fields)
            if result is not None:
                return str(result).strip()
        return "—"

    sources = (visit, row, guide, cert)
    floor_ref = first(("PISO", "PISO_MUESTRA", "NIVEL_MUESTRA", "NIVEL", "N PISO"), sources)
    floor = str(floor_map.get(floor_ref, floor_ref))
    element_ref = first(("ELEMENTO", "ELEMENTO_MUESTRA", "TIPO_ELEMENTO"), sources)
    element = (element_map or {}).get(element_ref, element_ref)
    sector = first(("DESCRIPCION_SECTOR",), (visit,))
    if sector == "—":
        sector = first(("EJE_MUESTRA", "EJE", "UBICACION_MUESTRA", "UBICACION"), sources)
    location = " / ".join(part for part in (element, sector) if part != "—") or "—"
    return floor, location


def _visits_by_sample(
    visits: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], set[str]]:
    """Índice por ID_VISITA y fallback seguro por guía solamente si es única."""
    by_id: dict[str, dict[str, Any]] = {}
    by_guide: dict[str, dict[str, Any]] = {}
    repeated_guide: set[str] = set()
    for visit in visits:
        key = str(visit.get("ID_VISITA") or "").strip()
        guide = str(visit.get("ID_GUIA") or "").strip()
        if key:
            by_id[key] = visit
        if guide:
            if guide in by_guide:
                repeated_guide.add(guide)
            else:
                by_guide[guide] = visit
    for guide in repeated_guide:
        by_guide.pop(guide, None)
    return by_id, by_guide, repeated_guide


def _guide_label(guide: dict[str, Any], key: str) -> str:
    # GUIAS[ID_REGISTRO] puede ser la clave compuesta RUT-TIPO-FOLIO.
    # Se privilegia el folio visible cuando está disponible.
    value = _get(guide, "NUMERO_GUIA", "N_GUIA", "N° GUIA", "FOLIO", "FOLIO_GUIA")
    return str(value).strip() if value is not None else key


def _certificate_availability(cert: dict[str, Any]):
    """Regresa (fecha de disponibilidad, estimada).

    FECHA_CERTIFICADO es fecha documental; sin FECHA_REGISTRO no permite
    garantizar que el certificado estuviera cargado al corte.
    """
    registered = _get(cert, "FECHA_REGISTRO", "FECHA_INGRESO")
    if registered is not None:
        return parse_appsheet_date(registered), False
    return parse_appsheet_date(cert.get("FECHA_CERTIFICADO")), True


def _certificate_is_final(cert: dict[str, Any]) -> bool:
    return all(
        to_float_or_none(cert.get(col)) is not None
        for col in ("R_7_DIAS", "R_28_DIAS_1", "R_28_DIAS_2")
    )


def _snapshot_certificates(
    certs: list[dict[str, Any]], cutoff: date
) -> tuple[dict[str, dict[str, Any]], list[str], bool]:
    by_guide: dict[str, list[tuple[date, int, dict[str, Any]]]] = defaultdict(list)
    warnings = []
    date_estimated = False
    bad_dates = 0

    for cert in certs:
        guide = str(cert.get("ID_GUIA") or "").strip()
        if not guide:
            continue
        available, estimated = _certificate_availability(cert)
        if available is None:
            bad_dates += 1
            continue
        if estimated:
            date_estimated = True
        if available > cutoff:
            continue
        # En la misma fecha, priorizar certificado definitivo y orden estable.
        by_guide[guide].append((available, int(_certificate_is_final(cert)), cert))

    result = {}
    for guide, versions in by_guide.items():
        versions.sort(key=lambda x: (x[0], x[1], str(x[2].get("ID_CERTIFICADO") or "")))
        # El último definitivo sustituye al preliminar. Un preliminar tardío
        # no debe degradar un resultado definitivo ya registrado.
        finals = [v for v in versions if v[1] == 1]
        result[guide] = (finals[-1] if finals else versions[-1])[2]

    if date_estimated:
        warnings.append(
            "CONTROL HISTÓRICO PROVISORIO: uno o más certificados no tienen "
            "FECHA_REGISTRO. Se usó FECHA_CERTIFICADO como aproximación; "
            "esta fecha NO demuestra cuándo se cargaron en AppSheet."
        )
    if bad_dates:
        warnings.append(
            f"{bad_dates} certificado(s) sin fecha verificable se excluyeron "
            "del corte histórico."
        )
    return result, warnings, date_estimated


def _sample_has_future_final(
    row: dict[str, Any], current_cert: dict[str, Any] | None, chosen_cert: dict[str, Any] | None,
) -> bool:
    """Indica si los valores virtuales actuales son seguros para el corte."""
    if not _yes(row.get("CERTIFICADO_FINAL_28D")):
        return False
    return bool(
        current_cert and chosen_cert and
        str(current_cert.get("ID_CERTIFICADO")) == str(chosen_cert.get("ID_CERTIFICADO"))
    )


def build_resistance_report(
    rows: list[dict[str, Any]],
    certificates: list[dict[str, Any]],
    guide_rows: list[dict[str, Any]],
    floor_map: dict[str, Any],
    cutoff: date,
    week_start: date | None = None,
    visit_rows: list[dict[str, Any]] | None = None,
    element_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Devuelve datos de capítulo y advertencias, sin E/S, testeable."""
    warnings: list[str] = []
    guide_map = {str(r.get("ID_REGISTRO") or "").strip(): r for r in guide_rows}
    cert_map = {str(r.get("ID_CERTIFICADO") or "").strip(): r for r in certificates}
    visits_by_id, visits_by_guide, repeated_guide_visits = _visits_by_sample(visit_rows or [])
    orphan_visits = 0
    guide_visit_fallbacks = 0
    mismatched_visits = 0
    cert_asof, cert_warnings, historical_estimated = _snapshot_certificates(certificates, cutoff)
    warnings.extend(cert_warnings)

    prepared = []
    missing_date = 0
    missing_grade = 0
    fallback_guide_date = 0
    missing_current_cert = 0
    old_projection_mismatch = 0

    for row in rows:
        guide_key = str(row.get("ID_GUIA") or "").strip()
        guide = guide_map.get(guide_key, {})
        sample_date = parse_appsheet_date(_get(row, "Fecha_Toma_Muestra", "FECHA_TOMA_MUESTRA"))
        if sample_date is None:
            # Fallback solo si coincide con el origen ya identificado por el
            # usuario: TABLA_RESISTENCIA[Fecha_Toma_Muestra] dereferencia GUIAS.
            sample_date = parse_appsheet_date(guide.get("FECHA_EMISION"))
            if sample_date is not None:
                fallback_guide_date += 1
        if sample_date is None:
            missing_date += 1
            continue
        if sample_date > cutoff:
            continue
        grade = _grade(_get(row, "Grado del Hormigon", "GRADO_DEL_HORMIGON", "GRADO_HORMIGON"))
        if not grade:
            missing_grade += 1
            continue

        cert = cert_asof.get(guide_key, {})
        current_ref = str(row.get("ID_CERTIFICADO") or "").strip()
        current_cert = cert_map.get(current_ref)
        if current_ref and current_cert is None:
            missing_current_cert += 1
        final = _certificate_is_final(cert) if cert else False

        # Resultado individual: la VC de AppSheet es la fuente normal. Para
        # cortes históricos donde el Ref actual apunta a una versión futura,
        # reconstruimos el mismo promedio desde el certificado vigente al corte.
        individual = None
        if final:
            if _sample_has_future_final(row, current_cert, cert):
                individual = to_float_or_none(row.get("Resistencia_Individual"))
            if individual is None:
                r1 = to_float_or_none(cert.get("R_28_DIAS_1"))
                r2 = to_float_or_none(cert.get("R_28_DIAS_2"))
                if r1 is not None and r2 is not None:
                    individual = (r1 + r2) / 2

        min_ind = _valid_limit(row.get("Resis_Indiv_Minima"))
        min_mov = _valid_limit(row.get("Resis_movil_minima"))
        r7 = to_float_or_none(cert.get("R_7_DIAS")) if cert else None
        expected = to_float_or_none(row.get("resistencia_Esperada"))
        # La estimación virtual actual puede referenciar un certificado 28D
        # posterior al corte. Si su R7 difiere del preliminar histórico, no
        # presentar una proyección anacrónica como si fuera conocida al corte.
        if not final and cert and current_cert and current_ref != str(cert.get("ID_CERTIFICADO")):
            current_r7 = to_float_or_none(current_cert.get("R_7_DIAS"))
            if r7 != current_r7:
                if expected is not None:
                    old_projection_mismatch += 1
                expected = None
        due28 = sample_date + timedelta(days=28)
        visit_ref = str(row.get("ID_VISITA") or "").strip()
        visit = visits_by_id.get(visit_ref, {}) if visit_ref else {}
        if visit_ref and not visit:
            orphan_visits += 1
        if visit and str(visit.get("ID_GUIA") or "").strip() not in ("", guide_key):
            mismatched_visits += 1
            visit = {}  # no usar ubicación de otra guía
        if not visit and guide_key in visits_by_guide:
            visit = visits_by_guide[guide_key]
            guide_visit_fallbacks += 1
        floor, location = _location(
            row, visit, guide, cert, floor_map, element_map=element_map,
        )

        prepared.append({
            "id_muestra": str(row.get("ID_MUESTRA") or "").strip(),
            "id_guia": guide_key,
            "guia": _guide_label(guide, guide_key),
            "grade": grade,
            "date": sample_date,
            "floor": floor,
            "location": location,
            "final": final,
            "individual": individual,
            "min_individual": min_ind,
            "min_moving": min_mov,
            "r7": r7,
            "expected": expected,
            "due28": due28,
            "overdue": (not final and cutoff >= due28),
            "pending": not final,
            "raw": row,
            "cert": cert,
        })

    if orphan_visits:
        warnings.append(
            f"{orphan_visits} referencia(s) ID_VISITA de TABLA_RESISTENCIA "
            "no aparecen en TABLA_VISITA_TOMA_MUESTRA; verificar sincronización."
        )
    if mismatched_visits:
        warnings.append(
            f"{mismatched_visits} visita(s) ID_VISITA apuntan a una ID_GUIA diferente; "
            "se descartó su ubicación para impedir cruces incorrectos."
        )
    if repeated_guide_visits:
        warnings.append(
            f"{len(repeated_guide_visits)} guía(s) tienen varias visitas; "
            "el respaldo por ID_GUIA está deshabilitado para ellas."
        )
    if guide_visit_fallbacks:
        warnings.append(
            f"{guide_visit_fallbacks} ubicación(es) obtenidas mediante ID_GUIA "
            "porque no pudo resolverse ID_VISITA; revisar vínculo."
        )
    if fallback_guide_date:
        warnings.append(
            f"{fallback_guide_date} Fecha_Toma_Muestra vacía(s) se completaron "
            "provisionalmente con GUIAS[FECHA_EMISION]; confirmar equivalencia."
        )
    if missing_current_cert:
        warnings.append(
            f"{missing_current_cert} referencia(s) ID_CERTIFICADO de TABLA_RESISTENCIA "
            "no se encontraron en TABLA_CERTIFICADO_HORMIGON. Revisar datos sincronizados."
        )
    if old_projection_mismatch:
        warnings.append(
            f"{old_projection_mismatch} proyección(es) históricas se omitieron "
            "porque el R7 del certificado archivado difiere del R7 vigente actual."
        )
    if missing_date:
        warnings.append(f"{missing_date} muestra(s) sin Fecha_Toma_Muestra se excluyeron.")
    if missing_grade:
        warnings.append(f"{missing_grade} muestra(s) sin Grado del Hormigon se excluyeron.")

    duplicates = [g for g, n in Counter(x["id_guia"] for x in prepared if x["id_guia"]).items() if n > 1]
    if duplicates:
        warnings.append(
            f"Se detectaron {len(duplicates)} guía(s) repetidas en TABLA_RESISTENCIA; "
            "revisar posible duplicidad de muestras."
        )

    by_grade = defaultdict(list)
    for item in prepared:
        by_grade[item["grade"]].append(item)

    grades = []
    total_ind_fail = total_mov_fail = 0
    total_ind_evaluated = total_mov_evaluated = 0
    for grade in sorted(by_grade, key=_grade_sort):
        samples = sorted(
            by_grade[grade],
            key=lambda x: (x["date"], _natural_key(x["guia"]), x["id_muestra"]),
        )

        definitives = [x for x in samples if x["final"] and x["individual"] is not None]

        # Media móvil de 3 resistencias individuales definitivas consecutivas.
        # Para un corte histórico se reconstruye para evitar contaminación con
        # certificados cargados después del corte.
        moving = []
        for idx, item in enumerate(definitives):
            if idx < 2:
                continue
            window = definitives[idx - 2: idx + 1]
            calculated = sum(x["individual"] for x in window) / 3
            app_value = to_float_or_none(item["raw"].get("Resis_Media_Movil"))

            # La VC se usa/valida cuando corresponde al estado actual.
            # Si difiere materialmente, preservamos el cálculo del corte y avisamos.
            value = calculated
            if app_value is not None and all(_sample_has_future_final(x["raw"], cert_map.get(str(x["raw"].get("ID_CERTIFICADO") or "").strip()), x["cert"]) for x in window):
                if abs(app_value - calculated) <= 0.02:
                    value = app_value
                else:
                    warnings.append(
                        f"{grade} - guía {item['guia']}: Resis_Media_Movil AppSheet "
                        f"({app_value:.2f}) difiere del promedio del corte ({calculated:.2f})."
                    )

            min_value = item["min_moving"]
            moving.append({
                "date": item["date"],
                "guia": item["guia"],
                "guides": " / ".join(x["guia"] for x in window),
                "floor": item["floor"],
                "location": item["location"],
                "value": value,
                "minimum": min_value,
                "difference": value - min_value if min_value is not None else None,
                "below": min_value is not None and value < min_value,
            })

        individual_failures = []
        for x in definitives:
            minimum = x["min_individual"]
            if minimum is not None and x["individual"] < minimum:
                individual_failures.append({
                    **x,
                    "difference": x["individual"] - minimum,
                })

        moving_failures = [x for x in moving if x["below"]]
        total_ind_fail += len(individual_failures)
        total_mov_fail += len(moving_failures)
        total_ind_evaluated += sum(x["min_individual"] is not None for x in definitives)
        total_mov_evaluated += sum(x["minimum"] is not None for x in moving)

        pending_projections_missing = sum(
            x["pending"] and x["r7"] is not None and x["expected"] is None
            for x in samples
        )
        if pending_projections_missing:
            warnings.append(
                f"{grade}: {pending_projections_missing} muestra(s) con R7 "
                "sin resistencia_Esperada devuelta por AppSheet; revisar VC."
            )
        projected = [
            x for x in samples
            if x["pending"] and x["r7"] is not None and x["expected"] is not None
        ]
        projection_alerts = [
            x for x in projected
            if x["min_individual"] is not None and x["expected"] < x["min_individual"]
        ]
        overdue = [x for x in samples if x["overdue"]]

        grade_warnings = []
        if definitives and any(x["min_individual"] is None for x in definitives):
            grade_warnings.append("Hay resultados definitivos sin Resis_Indiv_Minima; no se clasifican como cumplimiento/incumplimiento.")
        if len(definitives) >= 3 and any(x["min_moving"] is None for x in definitives[2:]):
            grade_warnings.append("Hay medias móviles sin Resis_movil_minima; no se clasifican como cumplimiento/incumplimiento.")

        grades.append({
            "grade": grade,
            "samples": samples,
            "definitives": definitives,
            "moving": moving,
            "individual_failures": individual_failures,
            "moving_failures": moving_failures,
            "projected": projected,
            "projection_alerts": projection_alerts,
            "overdue": overdue,
            "summary": {
                "taken": len(samples),
                "final": len(definitives),
                "pending": len([x for x in samples if x["pending"]]),
                "overdue": len(overdue),
                "individual_failures": len(individual_failures),
                "moving_failures": len(moving_failures),
                "individual_evaluated": sum(x["min_individual"] is not None for x in definitives),
                "moving_evaluated": sum(x["minimum"] is not None for x in moving),
                "projected": len(projected),
                "projection_alerts": len(projection_alerts),
            },
            "warnings": grade_warnings,
        })

    final_count = sum(g["summary"]["final"] for g in grades)
    pending_count = sum(g["summary"]["pending"] for g in grades)
    overdue_count = sum(g["summary"]["overdue"] for g in grades)

    week_taken = 0
    week_results = 0
    if week_start:
        week_taken = sum(week_start <= x["date"] <= cutoff for x in prepared)
        # Fecha de disponibilidad del certificado vigente al corte.
        for x in prepared:
            if not x["final"]:
                continue
            av, _ = _certificate_availability(x["cert"])
            if av and week_start <= av <= cutoff:
                week_results += 1

    return {
        "available": bool(prepared),
        "cutoff": cutoff,
        "historical_estimated": historical_estimated,
        "summary": {
            "taken": len(prepared),
            "final": final_count,
            "pending": pending_count,
            "overdue": overdue_count,
            "individual_failures": total_ind_fail,
            "moving_failures": total_mov_fail,
            "individual_evaluated": total_ind_evaluated,
            "moving_evaluated": total_mov_evaluated,
            "week_taken": week_taken,
            "week_results": week_results,
        },
        "grades": grades,
        "warnings": warnings,
    }
