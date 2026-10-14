from datetime import date

from app.sample_ticket_parser import parse_sample_ticket


def test_parse_ticket_with_technical_fields(monkeypatch):
    import app.sample_ticket_parser as module

    text = """
BOLETA DE MUESTREO DE HORMIGÓN / MORTERO
MUESTRA N° 202342
CAMIÓN N° 075     GUIA N° 727871     CANT.(en m3) 8     PLANTA Quilicura
CÓDIGO DE PRODUCTO 4842     GRADO/TIPO GB30902012     HORA DE CARGA 13:45
SALIDA PLANTA 13:51
LLEGADA A OBRA 14:29
COLOCADO EN Dado Grua
FECHA DE MUESTREO Martes 06 de Octubre de 2026     HORA MUESTREO 14:50
TEMPERATURA AMBIENTE 14,0 °C     TEMPERATURA DE MEZCLA 25,9 °C     EDADES DE ENSAYO 3,3,28
ASENTAMIENTO 13,0 (en cm)
PROBETA EMPLEADA: Cilindro     CANT.: 3
COMPACTACIÓN DE PROBETAS: Vibrado     CURADO DE PROBETAS EN OBRA: Cubierta plástica
MUESTRA SE EXTRAE A 1,0 m3 DESCARGADOS
HORA INICIO DESCARGA 14:40     OPERADOR MIXER (nombre) Maikol manriquez
Jonathan chavez                                                                       Cristóbal Jiménez.
RESPONSABLE EN OBRA                                       FIRMA                              MUEST. TECNHOR
"""

    monkeypatch.setattr(module, "extract_pdf_text", lambda _pdf: text)
    ticket = parse_sample_ticket(b"fake")

    assert ticket.sample_number == "202342"
    assert ticket.guide_number == "727871"
    assert ticket.truck_number == "075"
    assert ticket.guide_m3 == 8.0
    assert ticket.product_code == "4842"
    assert ticket.grade_type == "GB30902012"
    assert ticket.load_time == "13:45:00"
    assert ticket.plant_departure_time == "13:51:00"
    assert ticket.site_arrival_time == "14:29:00"
    assert ticket.placement == "Dado Grua"
    assert ticket.sample_date == date(2026, 10, 6)
    assert ticket.sample_time == "14:50:00"
    assert ticket.ambient_temperature == 14.0
    assert ticket.mix_temperature == 25.9
    assert ticket.slump_cm == 13.0
    assert ticket.specimen_type == "Cilindro"
    assert ticket.specimen_count == 3
    assert ticket.test_ages == "3,3,28"
    assert ticket.specimen_compaction == "Vibrado"
    assert ticket.specimen_curing == "Cubierta plástica"
    assert ticket.discharged_m3_at_sample == 1.0
    assert ticket.discharge_start_time == "14:40:00"
    assert ticket.mixer_operator == "Maikol manriquez"
    assert ticket.site_responsible == "Jonathan chavez"
    assert ticket.lab_sampler == "Cristóbal Jiménez"


def test_parse_ticket_v162_preserves_full_grade_and_flexible_specimen_quantity(monkeypatch):
    import app.sample_ticket_parser as module

    text = """
BOLETA DE MUESTREO DE HORMIGÓN / MORTERO
MUESTRA N° 202342
CAMIÓN N° 075     GUIA N° 727871     CANT.(en m3) 8
CÓDIGO DE PRODUCTO 4842     GRADO/TIPO R03 GB30-90%-20 C/10     HORA DE CARGA 13:45
FECHA DE MUESTREO Martes 06 de Octubre de 2026     HORA MUESTREO 14:50
PROBETA EMPLEADA: Cilindro     CANT. : 3     *CONSISTENCIA DE MORTERO
"""

    monkeypatch.setattr(module, "extract_pdf_text", lambda _pdf: text)
    ticket = parse_sample_ticket(b"fake")

    assert ticket.truck_number == "075"
    assert ticket.grade_type == "R03 GB30-90%-20 C/10"
    assert ticket.specimen_type == "Cilindro"
    assert ticket.specimen_count == 3
