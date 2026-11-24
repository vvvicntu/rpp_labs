"""Добавляет в копию отчёта фактические JSON-ответы и снимки GraphiQL.
Не заменяет примеры в основном тексте и не создаёт фиктивных снимков.
"""
import argparse, json
from pathlib import Path
from docx import Document
from docx.shared import Cm, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('report',type=Path);args=parser.parse_args()
d=Document(args.report)
results=ROOT/'results'; files=sorted(results.glob('*.json')); shots=sorted((results/'screenshots').glob('*.png'))
if not files and not shots: raise SystemExit('Сначала выполните verify.py и/или capture_graphiql.py.')
d.add_page_break();d.add_paragraph('Приложение. Фактические результаты интеграционной проверки','лр заголовок')
for f in files:
    obj=json.loads(f.read_text(encoding='utf-8'))
    if f.stem.startswith('A_'):
        # Полные ответы запроса А остаются в JSON; в отчёте — число записей и SQL.
        obj={'request':obj['request'],'orders_count':len(obj['response']['data']['orders']),'sql_count':obj['sql_count'],'http_status':obj['http_status']}
    if f.stem=='restaurants':
        obj={'request':obj['request'],'restaurants_count':len(obj['response']['data']['restaurants']),'sql_count':obj['sql_count'],'http_status':obj['http_status']}
    d.add_paragraph(f.stem,'лр заголовок')
    x=d.add_paragraph();x.paragraph_format.line_spacing=1; r=x.add_run(json.dumps(obj,ensure_ascii=False,indent=2));r.font.name='Courier New';r.font.size=Pt(9)
for i,f in enumerate(shots,1):
    x=d.add_paragraph();x.alignment=WD_ALIGN_PARAGRAPH.CENTER;x.paragraph_format.keep_with_next=True
    x.add_run().add_picture(str(f),width=Cm(16))
    x=d.add_paragraph(f'Рисунок {i} – GraphiQL: {f.stem}');x.alignment=WD_ALIGN_PARAGRAPH.CENTER
    for r in x.runs:r.font.name='Times New Roman';r.font.size=Pt(12)
out=args.report.with_name(args.report.stem+'_с_результатами.docx');d.save(out);print(out)
