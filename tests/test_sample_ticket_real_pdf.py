from datetime import date
from pathlib import Path

import pytest

from app.sample_ticket_parser import parse_sample_ticket


PDF_PATH = Path("/mnt/data/file_261006_170724.pdf")


@pytest.mark.skipif(not PDF_PATH.exists(), reason="PDF real no disponible en este entorno")
def test_parse_uploaded_reference_pdf():
    ticket = parse_sample_ticket(PDF_PATH.read_bytes())

    assert ticket.sample_number == "202342"
    assert ticket.guide_number == "727872"
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
