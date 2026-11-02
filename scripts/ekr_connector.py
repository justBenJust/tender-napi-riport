"""Manual EKR file connector; never performs network access."""
import csv
import io
import re
import datetime as dt
import zipfile
from openpyxl import load_workbook
from processing import enrich, normalized_key, parse_date, safe_url

ALIASES = {
  'buyer':['ajanlatkero','ajanlatkero neve','ajanlatkero szervezet','ajánlatkérő','buyer','contracting authority','szervezet neve','ajanlatkerő'],
  'title':['targy','beszerzes targya','kozbeszerzes targya','megnevezes','hirdetmeny targya','title','subject','eljaras targya','beszerzesi targy'],
  'deadline':['ajanlatteteli hatarido','teljesitesi/ajanlatteteli hatarido','hatarido','beadasi hatarido','deadline','ajanlattetel hatarideje'],
  'value':['megrendeles erteke','becsult ertek','osszeg','ertek','procurement value','estimated value','netto ertek','megrendeles osszege','szerződés értéke'],
  'currency':['penznem','devizanem','currency'],
  'url':['hivatkozas','link','url','eljaras link','hirdetmeny url','hirdetmeny hivatkozas'],
  'identifier':['azonosito','ekr azon','ekr azonosito','eljarasazonosito','hirdetmenyazonosito','external id','id','iktatószám','iktato szam','hirdetmény iktatószáma'],
  'description':['leiras','rovid leiras','szoveg','description'],
  'cpv':['cpv','cpv kod','cpv kodok'],
  'status':['statusz','allapot','eljárás állapota'],
  'notice_type':['hirdetmeny tipusa','tipus'],
  'publication_date':['közzététel dátuma','megjelenés dátuma','közzététel időpontja','publication date'],
  'performance_deadline':['teljesítési határidő'],
  'performance_place':['teljesítés helye'],
  'buyer_on_behalf':['ajánlatkérő nevében eljár'],
  'framework':['km','keretmegállapodás','keretmegállapodás azonosító'],
  'procedure_type':['eljárás típusa'],
  'supplier':['számlakiállító szállító','szállító'],
  'comment':['megjegyzés']
}

ALIASES = {k:[normalized_key(a) for a in vals] for k,vals in ALIASES.items()}

def read_xlsx(path):
    with zipfile.ZipFile(path) as archive:
        if sum(entry.file_size for entry in archive.infolist()) > 150 * 1024 * 1024:
            raise ValueError('Túl nagy kibontott XLSX (max 150 MB)')
    workbook = load_workbook(path, read_only=True, data_only=False, keep_links=False)
    sheets = []
    try:
        for sheet in workbook:
            if sheet.sheet_state != 'visible':
                continue
            # Read-only dimensions may be missing (None), so the limit is enforced while reading too.
            if (sheet.max_column or 0) > 300 or (sheet.max_row or 0) > 20000:
                raise ValueError('EKR munkalap túl nagy (max 20 000 sor / 300 oszlop)')
            rows = []
            for row in sheet:
                if len(rows) >= 20000 or len(row) > 300:
                    raise ValueError('EKR munkalap túl nagy (max 20 000 sor / 300 oszlop)')
                values = []
                for cell in row:
                    if cell.data_type == 'f':
                        raise ValueError('Az EKR-export képletet tartalmaz. Exportálj csak értékeket.')
                    value = cell.value
                    if isinstance(value, (dt.datetime, dt.date)):
                        value = value.isoformat()
                    values.append(value if value is not None else '')
                rows.append(values)
            if rows:
                sheets.append((sheet.title, rows))
    finally:
        workbook.close()
    return sheets

def read_csv(path):
  raw=path.read_bytes()
  # UTF-8 first, fallback typical Hungarian Excel export.
  for codec in ('utf-8-sig','cp1250','iso-8859-2'):
    try: txt=raw.decode(codec);break
    except UnicodeDecodeError:continue
  else: raise ValueError('CSV karakterkódolása nem felismerhető')
  try: dialect=csv.Sniffer().sniff(txt[:5000], delimiters=',;\t|')
  except csv.Error:dialect=csv.excel
  return list(csv.reader(io.StringIO(txt),dialect))

def find_columns(row, aliases=None):
  norm=[normalized_key(x) for x in row]
  result={}
  for field, names in (aliases or ALIASES).items():
    exact=next((i for i,item in enumerate(norm) if item in names),None)
    if exact is not None:result[field]=exact;continue
    for i,item in enumerate(norm):
      if any(item.startswith(n+' ') for n in names if len(n)>=8):result[field]=i;break
  return result

def pick(row, col, field):
  i=col.get(field,-1)
  return str(row[i]).strip() if 0<=i<len(row) and row[i] is not None else ''

def normalize_ekr_sheet(rows, label, aliases=None):
  for k,line in enumerate(rows[:30]):
    mapping=find_columns(line, aliases)
    if 'title' in mapping and 'buyer' in mapping:break
  else:return [],f'{label}: nem található Ajánlatkérő + Tárgy fejléc az első 30 sorban'
  out=[]
  for row_index,line in enumerate(rows[k+1:],k+2):
    buyer=pick(line,mapping,'buyer');title=pick(line,mapping,'title')
    if not any(str(v or '').strip() for v in line):continue
    if title.lower() in {'tárgy','targy'} and normalized_key(buyer)=='ajanlatkero':continue
    rid=pick(line,mapping,'identifier')
    if len(rid)>200 or any(ord(c)<32 for c in rid) or rid.startswith(('=','+','@')):rid=''
    deadline=parse_date(pick(line,mapping,'deadline'))
    deadline_time=re.search(r'(?:T|\s)((?:[01]\d|2[0-3]):[0-5]\d)',pick(line,mapping,'deadline') or pick(line,mapping,'performance_deadline'))
    deadline_header=normalized_key(rows[k][mapping['deadline']]) if 'deadline' in mapping else ''
    submission=deadline if ('ajanlattet' in deadline_header or 'beadas' in deadline_header) and 'teljesit' not in deadline_header else ''
    money=pick(line,mapping,'value');currency=pick(line,mapping,'currency')
    # Do not claim an estimated value is an actual order value.
    value_type='nem tisztázott'
    if 'value' in mapping and 'becsult' in normalized_key(rows[k][mapping['value']]):value_type='becsült érték'
    if 'value' in mapping and normalized_key(rows[k][mapping['value']]) in ('megrendeles erteke','szerzodes erteke'):
      value_type='forrás szerinti szerződéses érték'
    record=enrich({'source':'EKR','id':rid or '', 'buyer':buyer,'title':title,'deadline':deadline,'submission_deadline':submission,
        'deadline_time':deadline_time.group(1) if deadline_time else '',
        'value':(' '.join((money,currency))).strip(),'value_kind':value_type if money else '',
        'publication_date':parse_date(pick(line,mapping,'publication_date')),
        'notice_type':pick(line,mapping,'notice_type') or pick(line,mapping,'procedure_type') or 'nem ismert',
        'procedure_status':pick(line,mapping,'status'),
        'performance_deadline':parse_date(pick(line,mapping,'performance_deadline')),
        'description':pick(line,mapping,'description'), 'cpv':pick(line,mapping,'cpv'),
        **{field:pick(line,mapping,field) for field in ('buyer_on_behalf','framework','procedure_type','supplier','comment')},
        'url':safe_url(pick(line,mapping,'url')),'performance_place':pick(line,mapping,'performance_place'), 'review':'nem értékelt'},
        {'file':label, 'row':row_index, 'columns':dict(zip(rows[k],line)), 'raw_row':line})
    out.append(record)
  return out, None

def import_ekr(path, aliases=None, source='EKR'):
  if not path.is_file():raise FileNotFoundError(f'EKR fájl nem található: {path}')
  if path.stat().st_size>35*1024*1024:raise ValueError('Túl nagy fájl (max 35 MB)')
  if path.suffix.lower()=='.csv':sheets=[(path.name,read_csv(path))]
  elif path.suffix.lower()=='.xlsx':sheets=read_xlsx(path)
  else:raise ValueError('Csak .csv vagy .xlsx EKR-exportot tölts fel')
  out=[];warn=[]
  for name,rows in sheets:
    label=path.name if path.suffix.lower()=='.csv' else f'{path.name} / {name}'
    records,issue=normalize_ekr_sheet(rows,label,aliases)
    if source!='EKR':
      for record in records:
        record['source']=source;record.pop('record_key',None)
      records=[enrich(record) for record in records]
    out+=records
    if issue:warn.append(issue)
  if not out and (not sheets or len(warn)==len(sheets)): raise ValueError('Nem sikerült importálható EKR-adatot azonosítani. '+ '; '.join(warn))
  return out,warn
