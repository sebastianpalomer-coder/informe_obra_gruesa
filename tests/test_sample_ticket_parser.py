from app.sample_ticket_parser import parse_sample_ticket


def test_parse_real_ticket_fixture_text(monkeypatch):
    import app.sample_ticket_parser as module

    text = """
BOLETA DE MUESTREO DE HORMIGÓN / MORTERO
MUESTRA N°             202342
CAMIÓN N° 075   GUIA N° 727872   CANT.(en m3) 8
"""

    monkeypatch.setattr(module, "extract_pdf_text", lambda _pdf: text)
    ticket = parse_sample_ticket(b"fake")
    assert ticket.sample_number == "202342"
    assert ticket.guide_number == "727872"
