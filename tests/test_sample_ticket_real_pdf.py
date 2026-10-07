from pathlib import Path

import pytest

from app.sample_ticket_parser import parse_sample_ticket


PDF_PATH = Path("/mnt/data/file_261006_170724.pdf")


@pytest.mark.skipif(not PDF_PATH.exists(), reason="PDF real no disponible en este entorno")
def test_parse_real_pdf():
    ticket = parse_sample_ticket(PDF_PATH.read_bytes())
    assert ticket.sample_number == "202342"
    assert ticket.guide_number == "727872"
