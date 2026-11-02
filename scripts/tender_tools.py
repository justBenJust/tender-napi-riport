#!/usr/bin/env python3
"""Manual exports, Word screenshots and Claude web results -> normalized JSON.
Python 3.10+; openpyxl for XLSX and tzdata for Windows time zones.
"""
import argparse
import datetime as dt
import json
import sys
import re
import zipfile
import posixpath
from collections import Counter
from xml.etree import ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from ekr_connector import ALIASES, import_ekr
from processing import normalized_key, enrich, get_budapest_today, safe_url, parse_date
import ted_api


def report_window(today, days=None, start=None, end=None):
    """One calendar-day window (Europe/Budapest) used by every source; default: today only."""
    if days is not None and (start or end):raise ValueError('A --days nem adható meg a --start/--end mellett')
    if days is not None:
        if days<1:raise ValueError('A --days legalább 1 legyen')
        return today-dt.timedelta(days=days-1),today
    finish=dt.date.fromisoformat(end) if end else today
    begin=dt.date.fromisoformat(start) if start else finish
    if finish<begin:raise ValueError('Végdátum megelőzi a kezdődátumot')
    return begin,finish


def window_status(record, start, end):
    """Email arrival decides for Outlook items, otherwise the publication date; no date = unknown."""
    email=(record.get('source_metadata') or {}).get('email') or {}
    day=parse_date(email.get('received_at')) or parse_date(record.get('publication_date'))
    if not day:return 'unknown'
    return 'in' if start.isoformat()<=day<=end.isoformat() else 'out'


def write_ted_web_prompt(path, start, end, profile=None):
    """Prepare instructions for Claude's web tools; never execute a network request."""
    root=Path(__file__).resolve().parents[1]
    zone=ZoneInfo('Europe/Budapest')
    begin=dt.datetime.combine(start,dt.time.min,tzinfo=zone)
    finish=dt.datetime.combine(end,dt.time(23,59,59),tzinfo=zone)
    template=(root/'references/ted_web_prompt.md').read_text(encoding='utf-8')
    values={'{{START}}':begin.isoformat(),'{{END}}':finish.isoformat(),
            '{{DATES}}':f'{begin.date().isoformat()} – {finish.date().isoformat()}',
            '{{SKILL_ROOT}}':'<skill>',
            # The profile is read in step 1 of SKILL.md; only point to it instead of repeating ~10 KB.
            '{{PROFILE}}':f'`{Path(profile).name}`' if profile else '`references/company_profile.md`'}
    for token,value in values.items():template=template.replace(token,value)
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(template,encoding='utf-8')
    return path


def import_ted_web(data):
    """Validate claimed evidence structure; unverified candidates stay report-only."""
    rows,details=import_source('TED',data)
    candidates=data.get('candidates',[])
    if not isinstance(candidates,list):raise ValueError('A candidates mező lista legyen')
    candidates=list(candidates)
    verified=[];rejected=[]
    metadata=dict(details.get('metadata') or {})
    window=metadata.get('search_window') or {}
    begin=parse_date(window.get('start'));end=parse_date(window.get('end'))
    for record in rows:
        evidence=record.get('source_metadata') or {}
        number=str(record.get('id',''))
        def official_link(value):
            url=safe_url(value)
            return bool(url and urlsplit(url).hostname=='ted.europa.eu' and
                        re.search(r'/(?:detail/)?'+re.escape(number)+r'(?:/|$)',urlsplit(url).path))
        date=parse_date(record.get('publication_date'))
        valid=(bool(re.fullmatch(r'\d+-\d{4}',number)) and evidence.get('verification')=='official_notice'
               and official_link(record.get('url')) and official_link(evidence.get('evidence_url'))
               and date and begin and end and begin<=date<=end
               and evidence.get('performance_country')=='HUN' and evidence.get('performance_country_evidence'))
        if valid:verified.append(record)
        else:
            record['source_metadata']={**evidence,'verification':'unverified',
                'validation_note':'Nem igazolt a TED-link/azonosító, a közzétételi dátumablak vagy a magyar teljesítési hely.'}
            rejected.append(record)
    candidates+=rejected
    candidate_rows,_=import_source('TED_JELOLT',{'status':'partial','records':candidates})
    for record in candidate_rows:record['source_metadata']={**(record.get('source_metadata') or {}),'verification':'unverified'}
    metadata.update(collection_method='claude_web',coverage='search_index_only')
    details['metadata']=metadata
    details['warnings']=list(details.get('warnings') or [])
    if details['status'] in ('success','partial'):
      details['status']='partial'
      details['warnings'].append('Webes keresés; a teljes napi lista lefedettsége nem igazolt.')
    if candidate_rows:details['warnings'].append(f'{len(candidate_rows)} ellenőrizetlen jelölt csak az ellenőrző riportban szerepel.')
    return verified,details,candidate_rows


def extract_docx(path, outdir):
    """Expose actual embedded screenshots for Claude to inspect, without OCR or URL fetches."""
    path=Path(path);outdir=Path(outdir)
    if path.suffix.lower()!='.docx' or path.stat().st_size>35*1024*1024:
        raise ValueError('Legfeljebb 35 MB méretű DOCX fájl szükséges')
    ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
        'a':'http://schemas.openxmlformats.org/drawingml/2006/main',
        'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
    manifest={'document':path.name,'paragraphs':[],'images':[],'warnings':[]}
    with zipfile.ZipFile(path) as archive:
        if sum(info.file_size for info in archive.infolist())>150*1024*1024:
            raise ValueError('Túl nagy kibontott Word-dokumentum')
        def xml(name):
            data=archive.read(name)
            if b'<!DOCTYPE' in data.upper():raise ValueError('DTD-t tartalmazó dokumentum nem támogatott')
            return ET.fromstring(data)
        document=xml('word/document.xml')
        relations={r.attrib['Id']:r.attrib for r in xml('word/_rels/document.xml.rels')} if 'word/_rels/document.xml.rels' in archive.namelist() else {}
        outdir.mkdir(parents=True,exist_ok=True)
        saved={}
        for number,paragraph in enumerate(document.findall('.//w:p',ns),1):
            entry={'paragraph':number,'text':''.join(t.text or '' for t in paragraph.findall('.//w:t',ns)),'images':[],'links':[]}
            for link in paragraph.findall('.//w:hyperlink',ns):
                relation=relations.get(link.get('{'+ns['r']+'}id'),{})
                if safe_url(relation.get('Target')):
                    entry['links'].append({'text':''.join(t.text or '' for t in link.findall('.//w:t',ns)),'url':relation['Target']})
            for image in paragraph.findall('.//a:blip',ns):
                relation=relations.get(image.get('{'+ns['r']+'}embed'),{})
                target=posixpath.normpath('word/'+relation.get('Target',''))
                if relation.get('TargetMode')=='External' or not target.startswith('word/media/') or target not in archive.namelist():
                    manifest['warnings'].append(f'{number}. bekezdés: nem beágyazott vagy nem olvasható kép; nem töltöttük le.');continue
                suffix=Path(target).suffix.lower()
                if suffix not in ('.png','.jpg','.jpeg','.webp','.gif'):
                    manifest['warnings'].append(f'{number}. bekezdés: nem támogatott képformátum ({suffix}).');continue
                if target not in saved:
                    filename=f'image_{len(saved)+1:03}{suffix}'
                    (outdir/filename).write_bytes(archive.read(target))
                    saved[target]=filename;manifest['images'].append(filename)
                entry['images'].append(saved[target])
            if entry['text'] or entry['images'] or entry['links']:manifest['paragraphs'].append(entry)
        if not manifest['images']:manifest['warnings'].append('Nincs feldolgozható beágyazott képernyőkép; ellenőrizd a dokumentum szövegét és formátumát.')
    (outdir/'document.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest


def import_source(name, data):
    """Accept normalized output from a future approved connector or manual import."""
    if not re.fullmatch(r'[A-Z][A-Z0-9_-]{0,29}', name):
        raise ValueError('Forrásnév: legfeljebb 30 nagybetű, szám, kötőjel vagy aláhúzás')
    if not isinstance(data, dict) or data.get('status') not in ('success', 'partial', 'failed', 'not_attempted'):
        raise ValueError('A forrás JSON-ból hiányzik az érvényes status mező')
    records = data.get('records', [])
    if not isinstance(records, list) or any(not isinstance(r, dict) or not isinstance(r.get('title'), str) for r in records):
        raise ValueError('A records lista elemeinek legalább title mezőt kell tartalmazniuk')
    if data['status'] in ('failed', 'not_attempted') and records:
        raise ValueError('Sikertelen vagy nem lekért forrás nem adhat vissza rekordokat')
    normalized = []
    for record in records:
        record = {**record, 'source': name}
        for field in ('id', 'buyer', 'title', 'notice_type', 'deadline', 'value'):
            record.setdefault(field, '')
        if not record['notice_type']:record['notice_type']=record.get('procedure_type','')
        record.pop('record_key', None)
        normalized.append(enrich(record))
    return normalized, {k: data.get(k, default) for k, default in
                        (('status', 'not_attempted'), ('metadata', {}), ('warnings', []))}


def check_email_coverage(records, details):
    """Every email read from Outlook must appear in the report, as a tender or as 'nem tender'."""
    metadata=details.get('metadata') or {}
    read=metadata.get('messages_read')
    if metadata.get('collection_channel')!='outlook_connector' or type(read) is not int:return
    ids={((r.get('source_metadata') or {}).get('email') or {}).get('message_id') for r in records}-{None,''}
    if len(ids)!=read:
        details['warnings']=list(details.get('warnings') or [])+[
            f'{read} elolvasott levélből {len(ids)} szerepel a rekordokban; minden levél kerüljön be tenderként vagy „nem tender” tételként.']
        if details['status']=='success':details['status']='partial'


def check_browser_coverage(records, details):
    """A Chrome read is complete only if every row the portal's own counter reported was captured."""
    metadata=details.get('metadata') or {}
    total=metadata.get('portal_result_count')
    if metadata.get('collection_channel')!='claude_in_chrome' or type(total) is not int:return
    if len(records)<total:
        details['warnings']=list(details.get('warnings') or [])+[
            f'A portál {total} találatot jelzett, a böngészőből {len(records)} rekord került be; a gyűjtés részleges.']
        if details['status']=='success':details['status']='partial'


def dedup(records):
  seen=set();out=[]
  for r in records:
    # Never dedup solely based on similar titles across sources.
    key=(r['source'], r.get('record_key') or r.get('id') or json.dumps(r,sort_keys=True,ensure_ascii=False))
    if key not in seen:seen.add(key);out.append(r)
  return out

def main():
  p=argparse.ArgumentParser(description='Kézi exportok, Word-képek és Claude webes találatainak feldolgozása')
  p.add_argument('--out',default='tender_input.json')
  p.add_argument('--ted-web-prompt',metavar='FILE',help='Strukturált prompt készítése Claude webes kereséséhez; hálózati hívás nélkül')
  p.add_argument('--profile',help='A TED webes promptjához használt cégprofil')
  p.add_argument('--ted-api',action='store_true',help='Hivatalos TED Search API lekérdezés (--start/--end közzétételi napok, magyar teljesítési hely); az egyetlen hálózati művelet')
  p.add_argument('--ted-web-input',help='Claude webes kereséséből készült ted_web.json importja')
  p.add_argument('--ted-skipped',metavar='OK',help='A TED-webkeresés kihagyásának oka, pl. "felhasználó kérésére kihagyva"')
  p.add_argument('--aliases',help='JSON: mezőnév -> további fejlécnevek')
  p.add_argument('--source-input',action='append',default=[],metavar='SOURCE=FILE',help='Új forrás normalizált JSON-fájlja')
  p.add_argument('--source-file',action='append',default=[],metavar='SOURCE=FILE',help='Kézi CSV/XLSX export, a forrás nevével')
  p.add_argument('--extract-docx',help='Word képernyőképeinek kinyerése Claude számára; külön művelet, hálózat nélkül')
  p.add_argument('--outdir',default='output/document',help='A Word-képek és document.json kimeneti mappája')
  p.add_argument('--days',type=int,help='A riport időszaka: a mai nappal végződő N naptári nap (Europe/Budapest); alap: 1 = csak ma')
  p.add_argument('--start',help='Az időszak első napja YYYY-MM-DD (a --days helyett)')
  p.add_argument('--end',help='Az időszak utolsó napja YYYY-MM-DD; alap: ma')
  a=p.parse_args()
  if a.extract_docx:
    print(json.dumps(extract_docx(a.extract_docx,a.outdir),ensure_ascii=False,indent=2));return
  try:start,end=report_window(get_budapest_today(),a.days,a.start,a.end)
  except ValueError as exc:p.error(str(exc))
  if a.ted_web_prompt:
    print(write_ted_web_prompt(a.ted_web_prompt,start,end,a.profile));return
  manual={}
  for kind,values in (('json',a.source_input),('table',a.source_file)):
    for value in values:
      name,separator,filename=value.partition('=');name=name.upper()
      if not separator or not re.fullmatch(r'[A-Z][A-Z0-9_-]{0,29}',name) or name in manual:
        p.error('Egyedi FORRÁS=fájl szükséges, max. 30 nagybetűvel, számmal, _ vagy - jellel')
      manual[name]=(kind,filename)
  if a.ted_api and a.ted_web_input:p.error('A --ted-api és a --ted-web-input közül csak az egyiket add meg')
  if a.ted_web_input or a.ted_api:
    if 'TED' in manual:p.error('A TED API / webes bemenet nem kombinálható másik TED-bemenettel')
    manual['TED']=('api',None) if a.ted_api else ('web',a.ted_web_input)
  if a.ted_skipped and (a.ted_web_input or a.ted_api):p.error('A --ted-skipped nem adható meg TED-lekérdezés mellett')
  aliases={k:list(v) for k,v in ALIASES.items()}
  if a.aliases:
    for k,v in json.loads(Path(a.aliases).read_text(encoding='utf-8')).items():
      if k not in aliases or not isinstance(v,list): p.error('Hibás alias konfiguráció')
      aliases[k]=[normalized_key(n) for n in v]+aliases[k]
  result={'generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),
          'search_window':{'start':str(start),'end':str(end),'days':(end-start).days+1,'timezone':'Europe/Budapest',
                           'definition':'A riport naptári napjai minden forrásra: közzététel, Outlooknál a levél érkezése'},
          'ted_status':'not_attempted','ekr_status':'not_attempted','ted_metadata':{},'warnings':[],'records':[]}
  if not manual:result['warnings'].append('Nincs megadott forrás; csak üres riport készülhet.')
  result['sources']={name:{'status':result[name.lower()+'_status']} for name in ('TED','EKR')}
  if a.ted_skipped:
    # A manual TED export may still replace the TED details; the warning keeps the skip visible.
    result['sources']['TED']['metadata']={'skip_reason':f'TED-webkeresés: {a.ted_skipped}'}
    result['warnings'].append(f'TED-webkeresés: {a.ted_skipped}')
  for name,(kind,filename) in manual.items():
    try:
      if kind=='table':
        records,warnings=import_ekr(Path(filename),aliases,source=name)
        details={'status':'partial' if warnings else 'success','warnings':warnings,'metadata':{'file':Path(filename).name,'input_kind':'manual_export'}}
      elif kind=='api':
        records,details=import_source('TED',ted_api.fetch(start,end))
      elif kind=='web':
        records,details,candidates=import_ted_web(json.loads(Path(filename).read_text(encoding='utf-8')))
        result['records']+=candidates
        if candidates:result['sources']['TED_JELOLT']={'status':'partial','report_only':True,'metadata':details['metadata']}
      else:
        records,details=import_source(name,json.loads(Path(filename).read_text(encoding='utf-8')))
        check_email_coverage(records,details)
        check_browser_coverage(records,details)
        # Non-tender emails are listed in the report only, never in the sales email.
        if name=='OUTLOOK':details['report_only']=True
      result['records']+=records;result['sources'][name]=details
      result['warnings'] += [f'{name}: {warning}' for warning in details.get('warnings',[])]
    except Exception as exc:
      result['sources'][name]={'status':'failed'}
      result['warnings'].append(f'{name}: {exc}')
    if name in ('TED','EKR'):result[name.lower()+'_status']=result['sources'][name]['status']
    if name=='TED' and kind in ('web','api'):result['ted_metadata']=result['sources'][name].get('metadata',{})
  result['records']=dedup(result['records'])
  outside=Counter()
  for record in result['records']:
    record['window_status']=window_status(record,start,end)
    if record['window_status']=='out':outside[record['source']]+=1
  result['warnings']+=[f'{name}: {count} tétel a riport időszakán ({start} – {end}) kívül jelent meg / érkezett; csak a riportban szerepel.'
                       for name,count in outside.items()]
  ekr_input=manual.get('EKR',('',''))[1]
  result['ekr_file']=Path(ekr_input).name if ekr_input else None
  result['schema_version']=2
  out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True)
  out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
  print(json.dumps({'output':str(out),'window':result['search_window'],'ted_status':result['ted_status'],'ekr_status':result['ekr_status'],
      'ted_count':sum(r['source']=='TED' for r in result['records']),'ekr_count':sum(r['source']=='EKR' for r in result['records']),
      'warnings':result['warnings']},ensure_ascii=False,indent=2))
  if not any(details['status'] in ('success','partial') for details in result['sources'].values()):sys.exit(2)

if __name__=='__main__':main()
