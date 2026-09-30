"""Demo de maquetación SIN datos reales y sin llamadas externas.
Ejecutar: python -m tests.build_preview
"""
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from app.resistance_report import build_resistance_report
from app.resistance_charts import attach_resistance_charts
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import CSS, HTML
from app.charts import weekly_trend_charts
from app import formatters as f


CUTOFF = date(2026, 9, 30)
rows = []
certs = []
guides = []
visits = []

for grade in ("G20", "G30"):
    for i, (a, b) in enumerate([(27,28),(29,28),(25,26),(28,28),(26,27),(30,31)], 1):
        guide=f"{grade}_{i}"
        when = f"09/{i+1:02d}/2026"
        d = {
            "ID_MUESTRA":guide,
            "ID_GUIA":guide,
            "ID_VISITA":f"VIS_{guide}",
            "ID_CERTIFICADO":f"CERT_{guide}",
            "Grado del Hormigon":grade,
            "Fecha_Toma_Muestra":when,
            "Resistencia_Individual":(a+b)/2 if grade=="G20" else (a+b)/2+4,
            "Resis_Indiv_Minima":27 if grade=="G20" else 31,
            "Resis_movil_minima":28 if grade=="G20" else 32,
            "CERTIFICADO_FINAL_28D":True,
        }
        if i>2:
            d["Resis_Media_Movil"] = None
        rows.append(d)
        c={
            "ID_CERTIFICADO":f"CERT_{guide}", "ID_GUIA":guide,
            "FECHA_REGISTRO":f"2026-09-{i+10:02d}T14:00:00",
            "R_7_DIAS":21.0,
            "R_28_DIAS_1":a if grade=="G20" else a+4,
            "R_28_DIAS_2":b if grade=="G20" else b+4,
        }
        certs.append(c)
        guides.append({"ID_REGISTRO":guide,"FOLIO":f"10{i}"})
        visits.append({"ID_VISITA":f"VIS_{guide}","ID_GUIA":guide,"PISO":"P4" if i<4 else "P5",
                       "ELEMENTO":"ELM01" if i<4 else "ELM02",
                       "DESCRIPCION_SECTOR":f"Eje C/{i}"})

for grade, num in (("G20",7),("G30",7)):
    guide=f"{grade}_{num}"
    rows.append({"ID_MUESTRA":guide, "ID_GUIA":guide,"ID_CERTIFICADO":f"CERT_{guide}", "ID_VISITA":f"VIS_{guide}",
                 "Grado del Hormigon":grade, "Fecha_Toma_Muestra":"08/01/2026",
                 "resistencia_Esperada":23 if grade=="G20" else 25,
                 "Resis_Indiv_Minima":27 if grade=="G20" else 31,"Resis_movil_minima":28 if grade=="G20" else 32})
    certs.append({"ID_CERTIFICADO":f"CERT_{guide}","ID_GUIA":guide,"FECHA_REGISTRO":"2026-08-11T14:00:00",
                  "R_7_DIAS":18})
    guides.append({"ID_REGISTRO":guide,"FOLIO":f"10{num}"})
    visits.append({"ID_VISITA":f"VIS_{guide}","ID_GUIA":guide,"PISO":"P6",
                   "ELEMENTO":"ELM03", "DESCRIPCION_SECTOR":"Sector oriente"})

res = attach_resistance_charts(build_resistance_report(rows,certs,guides,{"P4":"Piso 4","P5":"Piso 5","P6":"Piso 6"},CUTOFF,date(2026,9,24),visit_rows=visits,
    element_map={"ELM01":"MURO", "ELM02":"LOSA", "ELM03":"VIGA"}))

weekly={"current":SimpleNamespace(projected=13.5,real=12,geometric=11.5,compliance=.88,loss=.05),
        "weeks":[], "daily":[],"guides_total":0,"m3_total":0}
invoices=SimpleNamespace(count_month=1,net_month=1000,total_month=1190,total_accum=1190,m3_invoiced=30,
                         uf_pending=4,m3_contract=200,m3_consumed=80,m3_balance=120,oc_consumption=.4)
bundle={
    "data":{"NOMBRE_OBRA":"HOTEL ANTONIO BELLET","FECHA_CORTE":"09/30/2026",
            "ID_INFORME":"DEMO","RESPONSABLE_INFORME":"Equipo de obra", "BITACORA_SEMANAL":"Demostración de maquetación."},
    "general":{"available":False,"week_start":date(2026,9,24),"week_end":CUTOFF},
    "weekly":weekly,"invoices":invoices,"svg":None,"photos":[],"warnings":[],"resistance":res,
}
base=Path(__file__).resolve().parent.parent
out=base/'preview_resistencia_demo.pdf' 
E=Environment(loader=FileSystemLoader(str(base/'templates')),autoescape=select_autoescape(['html','xml']))
html=E.get_template('informe_semanal.html').render(
 d=bundle['data'], general=bundle['general'], weekly=bundle['weekly'],invoices=bundle['invoices'],
 resistance=bundle['resistance'], svg_alzaprimado=None, fotos=[], warnings=[],chart_curves=None,
 trend_charts=weekly_trend_charts(bundle['weekly']),
 logo_path=(base/'static/logo_altius.png').resolve().as_uri(),
 f=SimpleNamespace(date=f.fmt_date,m3=f.fmt_m3,num=f.fmt_number,pct=f.fmt_percent,clp=f.fmt_clp,
 uf=f.fmt_uf,signed_m3=f.fmt_signed_m3,month_year=f.fmt_month_year,days_deviation=f.fmt_days_deviation,
 floor=f.fmt_floor,first=f.first_value)
)
out.write_bytes(HTML(string=html,base_url=str(base)).write_pdf(stylesheets=[CSS(filename=str(base/'static/report.css'))]))
print(out)
print('res summary',res['summary'])
