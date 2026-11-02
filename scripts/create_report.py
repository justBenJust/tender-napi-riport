#!/usr/bin/env python3
"""Render factual HTML/XLSX/CSV reports from collector output + Claude assessments.
Never invent ratings or missing values.
"""
import argparse,csv,html,json,re
import datetime as dt
from decimal import Decimal
from collections import Counter
from pathlib import Path
from processing import safe_url, opportunity, enrich, parse_date, validate, assessment_error, get_budapest_today, NOT_TENDER_ASSESSMENT, HISTORICAL_ASSESSMENT

COLS=['Ajánlatkérő','Tárgy','Teljesítési / ajánlattételi határidő','Megrendelés értéke']
STATUS={'success':'Sikeres','partial':'Részleges','failed':'Nem elérhető / sikertelen','not_attempted':'Nem történt lekérés'}
CLASS={'active':'Aktív','preliminary':'Előzetes','consultation':'Piaci konzultáció','award':'Eredmény / lezárt','modification':'Szerződésmódosítás','not_tender':'Nem tender','unknown':'Ismeretlen'}
LABELS={'business_category':'Üzleti kategória','expected_match':'Várt beszerzés','uncertainty':'Bizonytalanság','recommended_action':'Javasolt lépés','assumptions':'Feltételezések',
        'buyer':'Ajánlatkérő','title':'Tárgy','publication_date':'Közzététel','deadline':'Határidő','value':'Érték','url':'Hivatkozás'}

def esc(text):return html.escape(str(text if text is not None else ''),quote=True)

VERSION_FILE=Path(__file__).resolve().parents[1]/'VERSION'
SKILL_VERSION=VERSION_FILE.read_text(encoding='utf-8').strip() if VERSION_FILE.is_file() else 'ismeretlen'


def period_text(window):
  """Hungarian period line, e.g. '2026.10.31. – 2026.11.02. (3 nap)'; empty if unknown."""
  start,end=parse_date((window or {}).get('start')),parse_date((window or {}).get('end'))
  if not start or not end:return ''
  dot=lambda day:day.replace('-','.')+'.'
  days=(dt.date.fromisoformat(end)-dt.date.fromisoformat(start)).days+1
  return f'{dot(start)} ({days} nap)' if start==end else f'{dot(start)} – {dot(end)} ({days} nap)'
def safe_excel(x):
  x=str(x or '')
  return "'"+x if x.lstrip().startswith(('=','+','-','@')) else x

def link_title(r):
  title=esc(r.get('title') or 'Nincs megadva')
  url=r.get('url') or ''
  if isinstance(url,str) and safe_url(url):
    return f'<a href="{esc(url)}" style="color:#164a8b;text-decoration:underline">{title}</a>'
  return title


def business_value(record):
  amount=record.get('procurement_value')
  if amount is not None:
    value=f'{Decimal(amount):,.2f}'.replace(',', ' ').replace('.', ',')
    return f"{value} {record.get('currency') or 'ismeretlen pénznem'} ({record.get('value_kind') or 'nem tisztázott'})"
  value=record.get('value')
  return f"{value} ({record.get('value_kind') or 'nem tisztázott'})" if value else 'Nincs megadva'


def apply_assessments(records,assessments):
  """Attach valid assessments; return the rejected or unmatched ones instead of dropping them silently."""
  valid={};issues=[]
  if not isinstance(assessments,dict):
    if assessments:issues.append('Az értékelésfájl nem JSON objektum; egyik tétel sem értékelt.')
    assessments={}
  for k,v in assessments.items():
    error=assessment_error(v)
    if error:issues.append(f'{k}: {error}')
    else:valid[k]=validate(v)
  keys=set()
  for r in records:
    key=r.get('record_key') or (f'{r["source"]}:{r["id"]}' if r.get('id') else '')
    keys.add(key)
    found=valid.get(key)
    if r.get('classification')=='not_tender':
      # A non-tender email is always scored 0; only Claude's own 0-point wording is kept.
      if found and found['score']!=0:issues.append(f'{key}: nem tender tétel pontszáma csak 0 lehet')
      found=found if found and found['score']==0 else dict(NOT_TENDER_ASSESSMENT)
    elif not found and r.get('classification') in ('award','modification'):
      r['assessment']=dict(HISTORICAL_ASSESSMENT);r['ai_score']=None;r['ai_reasoning']=r['assessment']['reason']
      r['review']='automatikus';continue
    r['assessment']=found or {'decision':'nem értékelt','score':None,'reason':'Nem készült Claude-értékelés ehhez a tételhez.'}
    r['ai_score']=r['assessment']['score'];r['ai_reasoning']=r['assessment']['reason']
    r['review']='értékelt' if found else 'nem értékelt'
  issues+=[f'{k}: nincs ilyen record_key a bemenetben' for k in valid if k not in keys]
  return issues


def export_csv(records,path):
  with path.open('w',encoding='utf-8-sig',newline='') as fh:
    w=csv.writer(fh,delimiter=';')
    w.writerow(['Forrás',*COLS,'Értékelés','Pontszám','Indoklás','Hivatkozás','Hirdetményazonosító'])
    for r in records:
      ev=r['assessment']
      w.writerow([safe_excel(r.get('source','')),safe_excel(r.get('buyer','')),safe_excel(r.get('title','')),
        safe_excel(r.get('deadline','')),safe_excel(r.get('value','')),ev['decision'],ev['score'] if ev['score'] is not None else '',
        safe_excel(ev['reason']),safe_excel(r.get('url','')),safe_excel(r.get('id',''))])

def source_statuses(data):
    sources = {name: dict(details) for name, details in data.get('sources', {}).items()}
    for name in ('TED', 'EKR'):
        if name.lower() + '_status' in data:
            sources.setdefault(name, {'status': data[name.lower() + '_status']})
    for record in data.get('records', []):
        sources.setdefault(record['source'], {'status': 'not_attempted'})
    return sources


ACTIVE = [('buyer', 'Ajánlatkérő'), ('buyer_on_behalf', 'Ajánlatkérő nevében eljár'),
          ('title', 'Tárgy'), ('deadline', 'Teljesítési / ajánlattételi határidő'),
          ('framework', 'KM'), ('procedure_type', 'Eljárás típusa'),
          ('value', 'Megrendelés értéke'), ('supplier', 'Számlakiállító szállító'),
          ('status', 'Státusz'), ('comment', 'Megjegyzés')]
PRELIMINARY = [('buyer', 'Ajánlatkérő'), ('title', 'Tárgy'), ('submission_deadline', 'Ajánlattételi határidő'),
               ('framework', 'KM'), ('procedure_type', 'Eljárás típusa'), ('status', 'Státusz')]
EKR_COLUMNS = [('buyer', 'Ajánlatkérő'), ('title', 'Tárgy'),
               ('submission_deadline', 'Ajánlattételi határidő'), ('procedure_type', 'Eljárás típusa')]
GENERAL_COLUMNS = [('buyer', 'Ajánlatkérő'), ('title', 'Tárgy'),
                   ('deadline', 'Teljesítési / ajánlattételi határidő'), ('value', 'Megrendelés értéke')]
SOURCE_ORDER = ('IDPR', 'EKR', 'TED', 'KEF', 'ARIBA', 'FLUENTA', 'UNIVERZAL')
CELL = 'border:1px solid #777;padding:4px 6px;font-family:Times New Roman,serif;font-size:11pt;color:#000;vertical-align:middle;'
SOURCE_HEADINGS = {'UNIVERZAL': 'Univerzálon'}


def source_heading(name):
    """Hungarian locative suffix for the email section title, e.g. EKR-en, ARIBA-n."""
    if name in SOURCE_HEADINGS:
        return SOURCE_HEADINGS[name]
    return f'{name}-n' if name[-1:] in 'AEIOUÁÉÍÓÖŐÚÜŰ' else f'{name}-en'


def format_deadline(record, field='deadline'):
    raw = record.get(field) or ''
    note = ''
    if field == 'submission_deadline' and not raw and record.get('deadline'):
        # Do not present an ambiguous or performance deadline as a submission deadline.
        raw, note = record['deadline'], ' (nem igazolt ajánlattételi határidő)'
    date = parse_date(raw)
    if not date:
        return str(raw) + note if raw else 'Nincs megadva'
    match = re.search(r'(?:T|\s)((?:[01]\d|2[0-3]):[0-5]\d)', str(raw))
    time = record.get('deadline_time') or (match.group(1) if match else '')
    return date.replace('-', '.') + (' ' + str(time) if time else '') + note


def table(records, preliminary, source=None):
    source=source or (records[0].get('source') if records else '')
    columns = (PRELIMINARY if preliminary else ACTIVE) if source=='IDPR' else EKR_COLUMNS if source=='EKR' else GENERAL_COLUMNS
    headers = '<th style="' + CELL + '"></th>' + ''.join(
        f'<th style="{CELL}font-weight:bold;text-align:center">{esc(label)}</th>' for _, label in columns)
    rows = []
    for number, record in enumerate(records, 1):
        cells = [f'<td style="{CELL}text-align:center">{number}.</td>']
        for field, _ in columns:
            value = record.get(field, '')
            if field in ('buyer', 'title'):
                value = value or 'Nincs megadva'
            if field in ('deadline', 'submission_deadline'):
                value = format_deadline(record, field)
            if field == 'value':
                value = business_value(record)
            if field == 'status':
                value = record.get('procedure_status') or ''
            if field == 'procedure_type' and preliminary:
                value = value or ('piaci konzultáció' if record.get('classification') == 'consultation' else 'indikatív')
            if field == 'procedure_type' and not value:
                value=record.get('notice_type') or 'Nincs megadva'
            content = esc(value)
            if field == 'title' and safe_url(record.get('url')):
                content = f'<a href="{esc(record["url"])}" style="color:#367588;text-decoration:underline">{content}</a>'
            alignment = 'left' if field in ('title', 'comment') else 'center'
            cells.append(f'<td style="{CELL}text-align:{alignment}">{content}</td>')
        rows.append('<tr>' + ''.join(cells) + '</tr>')
    return f'<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;mso-table-lspace:0pt;mso-table-rspace:0pt;width:100%"><thead><tr>{headers}</tr></thead><tbody>{"".join(rows)}</tbody></table>'


def render_email(records, sources, window=None):
    parts = ['<div style="font-family:Times New Roman,serif;font-size:11pt;color:#000">']
    if period_text(window):
        parts.append(f'<p style="margin:0 0 12px"><b>Időszak:</b> {esc(period_text(window))}</p>')
    ordered=sorted(sources,key=lambda name:(SOURCE_ORDER.index(name) if name in SOURCE_ORDER else len(SOURCE_ORDER),name))
    index=0
    for name in ordered:
        details=sources[name]
        if details.get('report_only'):continue
        group = [r for r in records if r['source'] == name]
        if details['status']=='not_attempted' or (details['status']=='success' and not group):continue
        index+=1
        parts.append(f'<p style="margin:16px 0 8px"><b>{index}.&nbsp; {esc(source_heading(name))}:</b></p>')
        if details['status'] not in ('success', 'partial'):
            parts.append('<p style="margin:0 0 12px">A forrás adatai nem érhetők el.</p>')
            continue
        if details['status'] == 'partial':
            parts.append('<p>Részleges adatgyűjtés; a lista nem teljes.</p>')
        active_label='Közvetlen megrendelés(ek), verseny újranyitás(ok):' if name=='IDPR' else 'Aktív felhívások:'
        for preliminary, label in [(False, active_label),
                                   (True, 'Indikatív ajánlatkérés(ek):')]:
            subset = [r for r in group if (r['classification'] in ('preliminary', 'consultation')) == preliminary]
            if subset:
                parts.append(f'<p style="margin:12px 0 2px;text-decoration:underline">{label}</p>')
                parts.append(table(subset, preliminary,name))
        if not group:
            parts.append('<p>Nincs értékelt, releváns aktív vagy indikatív lehetőség.</p>')
    if not index:parts.append('<p>Nincs értékelt, releváns aktív vagy indikatív lehetőség a feldolgozott forrásokban.</p>')
    parts.append('</div>')
    return '\n'.join(parts)


CLIPBOARD_JS = """
function copySelection(el){
  // Run within the click, before asynchronous permission checks lose activation.
  const selection=window.getSelection();
  if(!selection || typeof document.execCommand!=='function')return false;
  const saved=[];
  for(let i=0;i<selection.rangeCount;i++)saved.push(selection.getRangeAt(i).cloneRange());
  const range=document.createRange();
  range.selectNodeContents(el);
  const onCopy=event=>{
    if(!event.clipboardData)return;
    event.clipboardData.setData('text/html',el.innerHTML);
    event.clipboardData.setData('text/plain',el.innerText);
    event.preventDefault();
  };
  try{
    selection.removeAllRanges();selection.addRange(range);
    document.addEventListener('copy',onCopy);
    return document.execCommand('copy');
  }catch(error){return false;}
  finally{
    document.removeEventListener('copy',onCopy);
    selection.removeAllRanges();
    for(const previous of saved)selection.addRange(previous);
  }
}

async function richCopy(){
  const el=document.getElementById('email-body');
  const status=document.getElementById('copy-status');
  if(copySelection(el)){
    status.textContent='Másolva. Outlookban Ctrl+V.';
    return;
  }
  try{
    await navigator.clipboard.write([new ClipboardItem({
      'text/html':new Blob([el.innerHTML],{type:'text/html'}),
      'text/plain':new Blob([el.innerText],{type:'text/plain'})
    })]);
    status.textContent='Másolva. Outlookban Ctrl+V.';
  }catch(error){
    try{await navigator.clipboard.writeText(el.innerText);status.textContent='Egyszerű szöveg másolva. Outlookban Ctrl+V. A táblázatformázás nem másolható ebben a böngészőben.';}
    catch(error){
      const range=document.createRange();range.selectNodeContents(el);
      const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);
      status.textContent='A böngésző letiltotta az automatikus másolást. Nyisd meg a letöltött outlook.html fájlt külön böngészőlapon, és kattints újra a gombra. Kézi másolás: Ctrl+C, majd Outlookban Ctrl+V.';
    }
  }
}
"""


def email_page(body):
    return f'''<!doctype html><html lang="hu"><head><meta charset="utf-8"><title>Tender email</title></head>
<body style="margin:24px;background:white">
<p><button onclick="richCopy()">Másolás Outlookhoz</button> <span id="copy-status" aria-live="polite"></span></p>
<div id="email-body">{body}</div><script>{CLIPBOARD_JS}</script></body></html>'''


def text_cell(cell, value):
    # Explicit string type prevents formulas, including leading whitespace/control characters.
    value = str(value if value is not None else '')
    value = ''.join(c for c in value if c in '\t\n\r' or ord(c) >= 32)
    cell.value = value[:32767]
    cell.data_type = 's'


def style(sheet, widths, color):
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = sheet.dimensions
    sheet.sheet_view.showGridLines = False
    for col, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(col)].width = width
    for row in sheet:
        for cell in row:
            cell.alignment = Alignment(vertical='top', wrap_text=True)
            if cell.row == 1:
                cell.fill = PatternFill('solid', fgColor=color)
                cell.font = Font(color='FFFFFF', bold=True)
            elif cell.row % 2 == 0:
                cell.fill = PatternFill('solid', fgColor='F1F5F9')
        sheet.row_dimensions[row[0].row].height = 34 if row[0].row == 1 else 58


def export_xlsx(records, opportunities, data, path):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    workbook = Workbook()
    workbook.remove(workbook.active)
    reserved={'AI Evaluation','Összesítő'}
    for source in source_statuses(data):
        color='334155'
        if source in reserved:raise ValueError('A forrás neve foglalt munkalapnév')
        sheet = workbook.create_sheet(source)
        sheet.append(COLS)
        for record in opportunities:
            if record['source'] != source:
                continue
            index = sheet.max_row + 1
            for col, field in enumerate(('buyer', 'title', 'deadline', 'value'), 1):
                cell = sheet.cell(index, col)
                value = record.get(field) or 'Nincs megadva'
                if field == 'value':
                    value = business_value(record)
                text_cell(cell, value)
                if field == 'deadline' and parse_date(record.get(field)):
                    cell.value = dt.date.fromisoformat(parse_date(record[field]))
                    cell.number_format = 'yyyy. mm. dd.'
                if field == 'value' and record.get('procurement_value') is not None:
                    cell.value = float(Decimal(record['procurement_value']))
                    currency = record.get('currency', '')
                    kind = record.get('value_kind') or 'nem tisztázott'
                    suffix = f'{currency} ({kind})'.replace('"', '')
                    cell.number_format = '#,##0.00 "' + suffix + '"'
                if field == 'title' and safe_url(record.get('url')):
                    cell.hyperlink = safe_url(record['url'])
                    cell.font = Font(color='164A8B', underline='single')
        style(sheet, [35, 80, 30, 38], color)
    sheet = workbook.create_sheet('AI Evaluation')
    sheet.append(['Rekordkulcs', 'Forrás', 'Tárgy', 'Besorolás', 'Minősítés', 'Pontszám', 'Indoklás',
                  'Üzleti kategória', 'Várt beszerzés', 'Bizonytalanság', 'Javasolt lépés', 'Feltételezések', 'Hiányzó adatok'])
    for record in records:
        ev = record['assessment']
        values = [record.get('record_key'), record['source'], record.get('title'), record.get('classification'),
                  ev['decision'], ev['score'], ev['reason'], ev.get('business_category'), ev.get('expected_match'),
                  ev.get('uncertainty'), ev.get('recommended_action'), ev.get('assumptions'), ', '.join(record.get('missing_fields', []))]
        index = sheet.max_row + 1
        for col, value in enumerate(values, 1):
            text_cell(sheet.cell(index, col), value)
        if ev['score'] is not None:
            sheet.cell(index, 6).value = ev['score']
    style(sheet, [34, 12, 65, 20, 22, 12, 70, 30, 40, 50, 50, 50, 40], '334155')
    sheet = workbook.create_sheet('Összesítő')
    sheet.append(['Mutató', 'Érték'])
    summary = [('Riport dátuma', data.get('generated_at')), ('TED státusz', data.get('ted_status')),
               ('EKR státusz', data.get('ekr_status')), ('EKR fájl', data.get('ekr_file')),
               ('Rekordok', len(records)), ('Levélbe kerülő lehetőségek', len(opportunities)),
               ('Hibák / korlátok', '; '.join(data.get('warnings', [])))]
    for name, value in summary:
        index = sheet.max_row + 1
        text_cell(sheet.cell(index, 1), name)
        text_cell(sheet.cell(index, 2), value)
    style(sheet, [35, 110], '334155')
    workbook.save(path)


def main():
  p=argparse.ArgumentParser()
  p.add_argument('--input',required=True)
  p.add_argument('--assessments',help='Claude által létrehozott értékelések JSON fájlja; opcionális')
  p.add_argument('--outdir',default='report_output')
  p.add_argument('--full-report',action='store_true',help='Kiegészítő XLSX, CSV és önálló levéltörzs készítése')
  a=p.parse_args();out=Path(a.outdir);out.mkdir(parents=True,exist_ok=True)
  data=json.loads(Path(a.input).read_text(encoding='utf-8'))
  recs=[enrich(r) for r in data.get('records',[])]
  data['records']=recs
  sources=source_statuses(data)
  assessments={}
  if a.assessments:
    assessments=json.loads(Path(a.assessments).read_text(encoding='utf-8'))
  assessment_issues=apply_assessments(recs,assessments)
  if assessment_issues:
    shown=assessment_issues[:20]+([f'… és további {len(assessment_issues)-20} hiba'] if len(assessment_issues)>20 else [])
    data['warnings']=list(data.get('warnings',[]))+[f'Elutasított értékelés – {issue}' for issue in shown]
  counts=Counter(r['assessment']['decision'] for r in recs)
  relevant=[r for r in recs if r['assessment']['decision'] in ('kiemelt','ellenőrzendő') and opportunity(r,get_budapest_today())
            and r.get('window_status')!='out' and sources.get(r['source'],{}).get('status') in ('success','partial') and not sources.get(r['source'],{}).get('report_only')]
  email_keys={r['record_key'] for r in relevant}
  bysource=lambda rs, s:[r for r in rs if r['source']==s]
  note='A „megrendelés értéke” oszlop becsült értéket is tartalmazhat; ilyenkor külön jelöljük.'
  warnings=' '.join(str(w) for w in data.get('warnings',[]))
  data['skill_version']=SKILL_VERSION
  mail=render_email(relevant,sources,data.get('search_window'))
  (out/'outlook.html').write_text(email_page(mail),encoding='utf-8')
  (out/'report.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
  files={'outlook':str(out/'outlook.html'),'json':str(out/'report.json')}
  def source_state(details):
    reason=(details.get('metadata') or {}).get('skip_reason')
    return STATUS.get(details['status'], details['status'])+(f' ({reason})' if reason else '')
  source_summary='; '.join(f"{name}: {source_state(details)}" for name,details in sources.items())
  ted_metadata=data.get('ted_metadata') or sources.get('TED',{}).get('metadata',{})
  method=ted_metadata.get('collection_method')
  # One window for every source, set at import (--days / --start / --end).
  report_window=data.get('search_window') or ted_metadata.get('search_window',{})
  window_days=report_window.get('days')
  collection_note={'claude_web':'TED: webes keresés, keresőindexből származó részeredmény; nem igazolt a teljes napi lista lefedettsége.',
                   'ted_api':f"TED: hivatalos TED Search API, a megadott közzétételi napok összes magyarországi teljesítési helyű hirdetménye ({ted_metadata.get('fetched','?')} db)."}.get(method,'')
  if sources.get('TED',{}).get('status') not in ('success','partial'):collection_note=''
  rows=[]
  for s in sources:
    for r in bysource(recs,s):
      ev=r['assessment']; detail=ev['reason']+' | '+' | '.join(f'{LABELS[field]}: {ev.get(field) or "Nincs megadva"}' for field in ('business_category','expected_match','uncertainty','recommended_action','assumptions'))
      detail+=' | Hiányzó adatok: '+', '.join(LABELS.get(f,f) for f in r.get('missing_fields',[]))
      if r['record_key'] in email_keys:
        state,label=('accepted','Elfogadva – emailbe kerül') if ev['decision']=='kiemelt' else ('review','Ellenőrzendő – emailbe kerül')
      elif r.get('classification')=='not_tender':
        state,label='nottender','Nem tender – nem kerül az emailbe'
      elif ev.get('method')=='auto_historical':
        state,label='historical','Történeti – nem kerül az emailbe'
      elif ev['decision']=='nem értékelt':
        state,label='unrated','Nem értékelt – nem kerül az emailbe'
      else:
        state,label='rejected','Kizárva – nem kerül az emailbe'
        reasons=[]
        if ev['decision']=='nem releváns':reasons.append('nem releváns a cégprofilhoz')
        if not opportunity(r,get_budapest_today()):reasons.append('lezárt, lejárt vagy nem igazolt aktív/indikatív hirdetménytípus')
        if r.get('window_status')=='out':reasons.append('a riport időszakán kívül jelent meg / érkezett')
        if sources[s].get('report_only'):reasons.append('ellenőrizetlen forrás, csak a riportban szerepelhet')
        if sources[s].get('status') not in ('success','partial'):reasons.append('a forrás feldolgozása nem sikeres')
        detail+=' | Emailből kizárva: '+'; '.join(reasons)
      rows.append('<tr class="decision-'+state+'"><td>'+esc(s)+'</td><td>'+link_title(r)+'</td><td>'+esc(r.get('buyer') or '')+'</td><td>'+esc(r.get('deadline') or '')+'</td><td><strong>'+esc(label)+'</strong></td><td>'+esc(CLASS.get(r.get('classification'),'Ismeretlen'))+' / '+esc(ev['decision'])+'</td><td>'+esc(ev['score'] if ev['score'] is not None else '—')+'</td><td>'+esc(detail)+'</td></tr>')
  distribution=Counter(r['classification'] for r in recs)
  highlights=''.join(f'<li>{link_title(r)} – {esc(r["assessment"]["reason"])}</li>' for r in sorted(relevant,key=lambda r:r['assessment']['score'],reverse=True))
  report=f'''<!doctype html><html lang="hu"><head><meta charset="utf-8"><title>Napi tender-riport</title><style>body{{font-family:Arial,sans-serif;color:#1e293b;max-width:1200px;margin:32px auto}}table{{width:100%;border-collapse:collapse}}td,th{{border:1px solid #d8dfe8;padding:8px;text-align:left;vertical-align:top}}th{{background:#e9eff6}}.decision-accepted{{background:#e6f4ea}}.decision-review{{background:#fff4cc}}.decision-rejected{{background:#fce8e6}}.decision-unrated{{background:#eef0f3}}.decision-nottender{{background:#f1ecf7}}.decision-historical{{background:#e8eef5}}.legend{{display:flex;flex-wrap:wrap;gap:8px}}.legend span{{padding:8px;border:1px solid #d8dfe8;border-radius:4px}}.warn{{background:#fff4d8;padding:12px;border-radius:5px}}h1{{color:#183d6d}}</style></head><body>
<h1>Napi tender-riport</h1><p>Időszak: {esc(report_window.get('start',''))} – {esc(report_window.get('end',''))}{f' ({esc(window_days)} nap, minden forrásra)' if window_days else ''}</p>
<p>{esc(collection_note)}</p>
<p>Riport készült: {esc(data.get('generated_at'))}. EKR fájl: {esc(data.get('ekr_file'))}. Skill-verzió: {esc(SKILL_VERSION)}.</p>
<p>Hirdetménybesorolás: {esc('; '.join(f'{CLASS.get(k,k)}: {v}' for k,v in distribution.items()))}</p>
<p><strong>Források:</strong> {esc(source_summary)}.</p>
<p><strong>Értékelések:</strong> kiemelt {counts['kiemelt']}, ellenőrzendő {counts['ellenőrzendő']}, nem releváns {counts['nem releváns']} (ebből nem tender levél {distribution['not_tender']}), történeti (automatikus) {counts['történeti']}, nem értékelt {counts['nem értékelt']}.</p>
{f'<p class="warn"><strong>Hibák / korlátok:</strong> {esc(warnings)}</p>' if warnings else ''}
<p>{esc(note)} Az eredeti forrás mindig ellenőrizendő. Az AI értékelés ajánlás, nem bizonyított alkalmassági döntés.</p>
<h2>Kiemelt és ellenőrzendő lehetőségek</h2><ul>{highlights}</ul>
<h2>Összes rekord – történeti és ismeretlen hirdetményekkel</h2>
<p>A nem releváns és kizárt találatok is megmaradnak ebben a táblában. A szín és a döntés az emailbe kerülést jelzi; a szakmai relevancia pontszáma és az eljárás állapota külön adat. Releváns, de lezárt, lejárt, ismeretlen típusú vagy nem igazolt forrású tétel sem kerül az emailbe.</p>
<p class="legend"><span class="decision-accepted">Zöld: elfogadva, emailbe kerül</span><span class="decision-review">Sárga: ellenőrzendő, emailbe kerül</span><span class="decision-rejected">Piros: kizárva / nem releváns, nem kerül az emailbe</span><span class="decision-unrated">Szürke: nem értékelt, nem kerül az emailbe</span><span class="decision-nottender">Lila: nem tenderértesítő levél, 0 pont, nem kerül az emailbe</span><span class="decision-historical">Kékesszürke: történeti (eredmény/módosítás), automatikusan, Claude-értékelés nélkül; nem kerül az emailbe</span></p>
<table><tr><th>Forrás</th><th>Tárgy / Hivatkozás</th><th>Ajánlatkérő</th><th>Határidő</th><th>Döntés</th><th>Minősítés</th><th>Pont</th><th>Indok</th></tr>{''.join(rows)}</table></body></html>'''
  (out/'riport.html').write_text(report,encoding='utf-8')
  files['report']=str(out/'riport.html')
  if a.full_report:
    export_csv(recs,out/'tenderek.csv')
    export_xlsx(recs,relevant,data,out/'tenderek.xlsx')
    (out/'outlook_email_body.html').write_text(mail,encoding='utf-8')
    files.update(xlsx=str(out/'tenderek.xlsx'),csv=str(out/'tenderek.csv'))
  print(json.dumps({'skill_version':SKILL_VERSION,'files':files,'count':len(recs),'assessment_counts':dict(counts),
                    'assessment_issues':assessment_issues},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
