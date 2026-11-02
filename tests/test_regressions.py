import datetime as dt
import json
import subprocess
import socket
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import tender_tools as t
import ekr_connector as ekr
import create_report as report
from processing import validate
from processing import classify, enrich, opportunity, parse_date, parse_money, safe_url
from create_report import export_xlsx


@pytest.mark.parametrize(('text','expected'), [
    ('Tájékoztató az eljárás eredményéről','award'),
    ('Előzetes tájékoztató','preliminary'), ('Előzetes piaci konzultáció','consultation'),
    ('Ajánlati felhívás','active'), ('competition','active'), ('result','award'),
    ('Szerződés módosítása','modification'), ('valami','unknown'), ('','unknown')])
def test_classification(text, expected):
    assert classify(text) == expected


def record(**kwargs):
    return enrich({'source':'EKR','id':'fiction-1','buyer':'Fiktív Hatóság','title':'LAN eszközök',
                   'notice_type':'Ajánlati felhívás','deadline':'2099-01-03','value':'1 200 000,50 HUF',
                   'value_kind':'becsült érték', **kwargs})


@pytest.mark.parametrize('codec', ['utf-8','utf-8-sig','cp1250','iso-8859-2'])
def test_encodings_aliases_and_missing(tmp_path, codec):
    path=tmp_path/'export.csv'
    path.write_bytes(('Ajánlatkérő;Tárgy;Iktatószám;Hirdetmény típusa\n'
                      'Fiktív Hatóság;Hálózati eszközök;2026/123;Tájékoztató az eljárás eredményéről\n'
                      'Fiktív Hatóság;;2026/124;\n').encode(codec))
    rows,warnings=ekr.import_ekr(path)
    assert len(rows)==2
    assert rows[0]['id']=='2026/123'
    assert rows[0]['classification']=='award'
    assert rows[0]['deadline']==''
    assert rows[1]['title']==''
    assert rows[0]['source_metadata']['columns']['Iktatószám']=='2026/123'


def test_alias_configuration():
    aliases={**t.ALIASES,'identifier':['sajat azonosito']}
    assert ekr.find_columns(['Saját azonosító'],aliases)['identifier']==0
    assert ekr.find_columns(['IktatÃ³szÃ¡m'])['identifier']==0


def test_dates_money_links():
    assert parse_date('2026.02.31.')==''
    assert parse_date('2026.10.23.')=='2026-10-23'
    assert parse_money('1.234.567,80 Ft')==('1234567.80','HUF')
    assert parse_money('ár egyeztetendő')[0] is None
    assert safe_url('https://')==''
    assert safe_url('https://user:pass@example.org')==''
    assert safe_url('javascript:alert(1)')==''


def test_no_title_merging_and_stable_keys():
    a=record(id=''); b=record(id='',publication_date='2026-10-23')
    assert len(t.dedup([a,a,b]))==2
    assert a['record_key']==record(id='')['record_key']
    assert enrich(a)['record_key']==a['record_key']


def test_ai_validation():
    assert validate({'score':99,'decision':'nem releváns','reason':'x'}) is None
    assert validate({'score':True,'decision':'kiemelt','reason':'x'}) is None
    assert validate({'score':85,'decision':'Kiemelt','reason':'Hálózati beszerzés','expected_match':'NAV LAN'})['expected_match']=='NAV LAN'


def test_opportunities():
    assert opportunity(record(),dt.date(2026,10,26))
    assert not opportunity(record(notice_type='result'),dt.date(2026,10,26))
    assert not opportunity(record(deadline='2020-01-01'),dt.date(2026,10,26))
    assert not opportunity(record(notice_type=''),dt.date(2026,10,26))


def test_ambiguous_deadline_is_not_submission():
    rows,issue=ekr.normalize_ekr_sheet([
        ['Ajánlatkérő','Tárgy','Határidő','Hirdetmény típusa'],
        ['Fiktív','LAN','2026-11-03','Ajánlati felhívás']], 'fiction.csv')
    assert rows[0]['deadline']=='2026-11-03'
    assert rows[0]['submission_deadline']==''


def test_xlsx_roundtrip_and_formula_security(tmp_path):
    r=record(title='=WEBSERVICE("https://example.org")',url='https://example.org')
    report.apply_assessments([r],{r['record_key']:{'decision':'kiemelt','score':95,'reason':'Fiktív teszt'}})
    path=tmp_path/'test.xlsx'
    export_xlsx([r],[r],{'ted_status':'failed','ekr_status':'success'},path)
    workbook=load_workbook(path)
    sheet=workbook['EKR']
    assert sheet.max_column==4 and sheet['B2'].data_type=='s'
    assert sheet['B2'].hyperlink.target=='https://example.org'
    assert sheet['C2'].is_date and sheet['D2'].data_type=='n'
    assert sheet.freeze_panes=='A2' and sheet.auto_filter.ref=='A1:D2'
    workbook.close()


def test_xlsx_import_dates_and_formula_rejection(tmp_path):
    workbook=Workbook();sheet=workbook.active
    sheet.append(['Ajánlatkérő','Tárgy','Teljesítési határidő'])
    sheet.append(['Fiktív','Router',dt.date(2026,11,3)])
    path=tmp_path/'input.xlsx';workbook.save(path)
    rows,_=ekr.import_ekr(path)
    assert rows[0]['performance_deadline']=='2026-11-03'
    assert rows[0]['submission_deadline']==''
    sheet['B2']='=1+1';workbook.save(path)
    with pytest.raises(ValueError,match='képlet'):ekr.import_ekr(path)


def test_partial_report_cli(tmp_path):
    records=[record(), record(id='result-1',notice_type='result',title='TÖRTÉNETI'),
             record(id='danger',title='<img src=x onerror=alert(1)>')]
    data={'records':records,'search_window':{'start':'2026-10-22','end':'2026-10-23'},
          'ted_status':'failed','ekr_status':'success','warnings':['TED DNS nem elérhető'], 'generated_at':'2026-10-26'}
    source=tmp_path/'source.json';source.write_text(json.dumps(data),encoding='utf-8')
    assessments=tmp_path/'ratings.json'
    assessments.write_text(json.dumps({r['record_key']:{'decision':'kiemelt','score':90,'reason':'Fiktív teszt'} for r in records}),encoding='utf-8')
    subprocess.run([sys.executable,'scripts/create_report.py','--input',str(source),'--assessments',str(assessments),'--outdir',str(tmp_path/'reports'),'--full-report'],check=True,capture_output=True)
    mail=(tmp_path/'reports/outlook.html').read_text(encoding='utf-8')
    assert 'TÖRTÉNETI' not in mail and '<img src=x' not in mail and '&lt;img' in mail
    assert mail.count('<th style=')==5 and 'writeText' in mail and 'ClipboardItem' in mail
    assert 'A forrás adatai nem érhetők el' in mail
    assert (tmp_path/'reports/tenderek.xlsx').exists()
    assert (tmp_path/'reports/report.json').exists()


def test_package_no_private_exports(tmp_path):
    from build_skill import build
    from zipfile import ZipFile
    package=build(tmp_path/'skill.zip')
    with ZipFile(package) as archive:
        names=archive.namelist()
        assert 'tender-napi-riport/SKILL.md' in names
        assert archive.read('tender-napi-riport/LICENSE')==Path('LICENSE').read_bytes()
        assert archive.read('tender-napi-riport/references/outlook_source.md')==Path('references/outlook_source.md').read_bytes()
        assert archive.read('tender-napi-riport/references/browser_source.md')==Path('references/browser_source.md').read_bytes()
        assert all(not any(part in name for part in ('.venv','__pycache__','private','output/','.csv','.xlsx')) for name in names)
        assert {Path(name).name for name in names if name.endswith('.py')}=={
            'tender_tools.py','ekr_connector.py','processing.py','create_report.py','ted_api.py'}
        archive.extractall(tmp_path/'unpacked')
    source=tmp_path/'source.json'
    source.write_text(json.dumps({'records':[record()], 'ekr_status':'success','ted_status':'failed'}),encoding='utf-8')
    target=tmp_path/'packaged_report'
    script=tmp_path/'unpacked/tender-napi-riport/scripts/create_report.py'
    subprocess.run([sys.executable,str(script),'--input',str(source),'--outdir',str(target)],check=True,capture_output=True)
    assert (target/'riport.html').is_file() and (target/'outlook.html').is_file()


def test_real_fixture_and_empty_valid_export(tmp_path):
    rows,warnings=ekr.import_ekr(Path('tests/fixtures/sample_ekr.csv'))
    assert [r['classification'] for r in rows]==['active','preliminary','award','unknown']
    empty=tmp_path/'empty.csv';empty.write_text('Ajánlatkérő;Tárgy\n',encoding='utf-8')
    assert ekr.import_ekr(empty)[0]==[]


def test_new_source_end_to_end_and_minimal_outputs(tmp_path):
    extra=tmp_path/'extra.json'
    extra.write_text(json.dumps({'status':'success','records':[
        {'id':'new-1','title':'LAN tender','notice_type':'Ajánlati felhívás','framework':'KM-TEST'},
        {'id':'new-2','title':'Tervezett LAN','notice_type':'Előzetes tájékoztató'}]}),encoding='utf-8')
    collected=tmp_path/'input.json'
    subprocess.run([sys.executable,'scripts/tender_tools.py','--source-file','EKR=tests/fixtures/sample_ekr.csv',
                    '--source-input',f'NEW={extra}','--out',str(collected)],check=True,capture_output=True)
    data=json.loads(collected.read_text(encoding='utf-8'))
    assert data['sources']['NEW']['status']=='success'
    rows=[r for r in data['records'] if r['source']=='NEW']
    assert len(rows)==2 and all(r['record_key'].startswith('NEW:') for r in rows)
    assessments=tmp_path/'ratings.json'
    assessments.write_text(json.dumps({r['record_key']:{'decision':'kiemelt','score':90,'reason':'Fiktív teszt'} for r in rows}),encoding='utf-8')
    target=tmp_path/'email'
    subprocess.run([sys.executable,'scripts/create_report.py','--input',str(collected),'--assessments',str(assessments),'--outdir',str(target)],check=True,capture_output=True)
    assert {p.name for p in target.iterdir()}=={'outlook.html','report.json','riport.html'}
    mail=(target/'outlook.html').read_text(encoding='utf-8')
    assert 'NEW-en:' in mail and 'Indikatív ajánlatkérés' in mail
    assert 'KM-TEST' in (target/'report.json').read_text(encoding='utf-8')
    assert mail.count('<table ')==2 and mail.count('<th style=')==10
    assert 'Times New Roman' in mail and 'background-color:' not in mail
    from create_report import source_statuses
    report.apply_assessments(data['records'],{})
    path=tmp_path/'new.xlsx'
    export_xlsx(data['records'],[],data,path)
    workbook=load_workbook(path)
    assert 'NEW' in workbook.sheetnames
    workbook.close()


def test_extra_email_columns_escape_and_deadline_time():
    from create_report import table
    r=record(source='IDPR',framework='<script>x</script>',buyer_on_behalf='Teszt közreműködő',supplier='Teszt szállító',
             comment='<img>',procedure_type='Versenyújranyitás',deadline='2099-11-03 10:00')
    rendered=table([r],False)
    assert '<script>' not in rendered and '&lt;script&gt;' in rendered
    assert '&lt;img&gt;' in rendered and '2099.11.03 10:00' in rendered
    assert 'Teszt közreműködő' in rendered and 'Teszt szállító' in rendered


def test_source_specific_email_sections_and_order():
    records=[record(source=name,id=name,procedure_type='Versenyújranyitás') for name in ('TED','EKR','IDPR','FLUENTA')]
    records.append(record(source='IDPR',id='indicative',notice_type='Indikatív ajánlatkérés'))
    sources={name:{'status':'success'} for name in ('FLUENTA','TED','EKR','IDPR','KEF')}
    rendered=report.render_email(records,sources)
    assert rendered.index('IDPR-en:')<rendered.index('EKR-en:')<rendered.index('TED-en:')<rendered.index('FLUENTA-n:')
    assert 'KEF-en:' not in rendered
    assert report.table([records[1]],False).count('<th style=')==5
    assert report.table([records[2]],False).count('<th style=')==11
    assert report.table([records[-1]],True).count('<th style=')==7


def test_manual_exports_for_multiple_sources_and_no_ted_network(tmp_path,monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('Manuális import nem nyithat hálózati kapcsolatot')
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    source=tmp_path/'export.csv'
    source.write_text('Ajánlatkérő nevében eljár;Ajánlatkérő;Tárgy;Eljárás típusa\nKözreműködő;Fiktív intézmény;LAN;Versenyújranyitás\n',encoding='utf-8')
    target=tmp_path/'input.json'
    monkeypatch.setattr(sys,'argv',['tender_tools','--source-file',f'IDPR={source}',
                                  '--source-file',f'TED={source}','--out',str(target)])
    t.main()
    data=json.loads(target.read_text(encoding='utf-8'))
    assert data['ted_status']=='success' and data['ekr_status']=='not_attempted'
    assert {r['source'] for r in data['records']}=={'IDPR','TED'}
    assert all(r['buyer']=='Fiktív intézmény' and r['buyer_on_behalf']=='Közreműködő' for r in data['records'])
    assert all(r['classification']=='active' for r in data['records'])


def test_docx_images_and_context_without_ocr_or_external_fetch(tmp_path):
    from zipfile import ZipFile
    import base64
    image=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a2ioAAAAASUVORK5CYII=')
    xml='''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body><w:p><w:r><w:t>IDPR – indikatív</w:t></w:r></w:p><w:p><w:r><a:blip r:embed="rId1"/></w:r></w:p><w:p><w:hyperlink r:id="rId2"><w:r><w:t>Fiktív LAN</w:t></w:r></w:hyperlink><w:r><a:blip r:embed="rId3"/></w:r></w:p></w:body></w:document>'''
    relationships='''<Relationships><Relationship Id="rId1" Target="media/shot.png"/><Relationship Id="rId2" Target="https://example.org/notice" TargetMode="External"/><Relationship Id="rId3" Target="https://example.org/image.png" TargetMode="External"/></Relationships>'''
    path=tmp_path/'screenshots.docx'
    with ZipFile(path,'w') as archive:
        archive.writestr('word/document.xml',xml)
        archive.writestr('word/_rels/document.xml.rels',relationships)
        archive.writestr('word/media/shot.png',image)
    result=t.extract_docx(path,tmp_path/'images')
    assert result['images']==['image_001.png']
    assert (tmp_path/'images/image_001.png').read_bytes()==image
    assert result['paragraphs'][0]['text']=='IDPR – indikatív'
    assert result['paragraphs'][1]['images']==['image_001.png']
    assert result['paragraphs'][2]['links'][0]['url']=='https://example.org/notice'
    assert result['warnings'] and 'records' not in result


def test_manual_normalized_ted_json_without_ekr(tmp_path,monkeypatch):
    source=tmp_path/'ted.json'
    source.write_text(json.dumps({'status':'success','records':[{'title':'Fiktív LAN','notice_type':'Ajánlati felhívás'}]}),encoding='utf-8')
    target=tmp_path/'collected.json'
    def forbidden(*args,**kwargs):raise AssertionError('Nem engedélyezett hálózati hívás')
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    monkeypatch.setattr(sys,'argv',['tender_tools','--source-input',f'TED={source}','--out',str(target)])
    t.main()
    data=json.loads(target.read_text(encoding='utf-8'))
    assert data['ted_status']=='success' and len(data['records'])==1


def test_ted_web_prompt_uses_report_days_and_profile(tmp_path):
    profile=tmp_path/'profile.md';profile.write_text('Fiktív profil: LAN és NAV kapcsolók',encoding='utf-8')
    target=t.write_ted_web_prompt(tmp_path/'prompt.md',dt.date(2026,10,24),dt.date(2026,10,25),profile)
    prompt=target.read_text(encoding='utf-8')
    # DST ended on 25 October: each calendar day keeps its own Budapest UTC offset.
    assert '2026-10-24T00:00:00+02:00' in prompt
    assert '2026-10-25T23:59:59+01:00' in prompt
    # The profile is referenced, not copied: Claude has already read it in step 1.
    assert '`profile.md`' in prompt and 'Fiktív profil' not in prompt
    assert '{{' not in prompt and '--ted-web-input' in prompt and 'web_search' in prompt
    assert 'C:/Users/' not in prompt


def web_ted_record(**overrides):
    return {'id':'123456-2026','buyer':'Fiktív hatóság','title':'Fiktív LAN',
            'publication_date':'2026-10-27','notice_type':'competition','deadline':'2099-11-03',
            'performance_place':'HUN','url':'https://ted.europa.eu/hu/notice/-/detail/123456-2026',
            'source_metadata':{'verification':'official_notice','evidence_url':'https://ted.europa.eu/hu/notice/-/detail/123456-2026',
                'performance_country':'HUN','performance_country_evidence':'Hungary','publication_date_precision':'day'},**overrides}


def web_ted_payload(records,candidates=None):
    return {'status':'success','records':records,'candidates':candidates or [],
            'metadata':{'search_window':{'start':'2026-10-26T12:00:00+01:00','end':'2026-10-27T12:00:00+01:00'},
                        'searched_queries':['fictional test']},'warnings':[]}


def test_ted_web_import_evidence_and_unverified_candidates():
    payload=web_ted_payload([web_ted_record(),web_ted_record(id='bad',url='https://example.org/tender')],
                            [{'title':'Aggregátor LAN','notice_type':'competition','url':'https://example.org/aggregator'}])
    rows,details,candidates=t.import_ted_web(payload)
    assert len(rows)==1 and rows[0]['source']=='TED'
    assert details['status']=='partial' and details['metadata']['collection_method']=='claude_web'
    assert details['metadata']['coverage']=='search_index_only'
    assert len(candidates)==2 and all(r['source']=='TED_JELOLT' for r in candidates)
    assert all(r['source_metadata']['verification']=='unverified' for r in candidates)
    assert len(payload['candidates'])==1  # Do not mutate the input envelope.


@pytest.mark.parametrize('overrides',[
    {'publication_date':'2026-10-23'},
    {'url':'https://ted.europa.eu/hu/notice/-/detail/999999-2026'},
    {'url':'https://ted.europa.eu.example.org/hu/notice/-/detail/123456-2026'},
    {'source_metadata':{'verification':'official_notice','evidence_url':'https://ted.europa.eu/hu/notice/-/detail/123456-2026'}},
])
def test_ted_web_missing_or_mismatched_evidence_is_report_only(overrides):
    rows,details,candidates=t.import_ted_web(web_ted_payload([web_ted_record(**overrides)]))
    assert not rows and len(candidates)==1


def test_ted_web_pipeline_to_report(tmp_path,monkeypatch):
    source=tmp_path/'ted_web.json'
    source.write_text(json.dumps(web_ted_payload([web_ted_record()],
        [{'id':'aggregator','title':'ELLENŐRIZETLEN-LAN','notice_type':'competition','deadline':'2099-11-03','url':'https://example.org'}])),encoding='utf-8')
    target=tmp_path/'input.json'
    def forbidden(*args,**kwargs):raise AssertionError('Webkeresési import nem nyithat hálózati kapcsolatot')
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    monkeypatch.setattr(sys,'argv',['tender_tools','--ted-web-input',str(source),'--start','2026-10-26','--end','2026-10-27','--out',str(target)])
    t.main()
    data=json.loads(target.read_text(encoding='utf-8'))
    assert data['ted_status']=='partial' and data['sources']['TED_JELOLT']['report_only']
    assessments=tmp_path/'assessments.json'
    assessments.write_text(json.dumps({r['record_key']:{'decision':'kiemelt','score':95,'reason':'Fiktív teszt'} for r in data['records']}),encoding='utf-8')
    out=tmp_path/'report'
    subprocess.run([sys.executable,'scripts/create_report.py','--input',str(target),'--assessments',str(assessments),'--outdir',str(out)],check=True,capture_output=True)
    email=(out/'outlook.html').read_text(encoding='utf-8')
    rendered=(out/'riport.html').read_text(encoding='utf-8')
    assert 'Fiktív LAN' in email and 'ELLENŐRIZETLEN-LAN' not in email
    assert 'ELLENŐRIZETLEN-LAN' in rendered and 'Webes keresés' in rendered


def test_ted_web_prompt_cli_does_not_collect(tmp_path,monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('A prompt készítése nem végez adatgyűjtést')
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    path=tmp_path/'prompt.md'
    monkeypatch.setattr(sys,'argv',['tender_tools','--ted-web-prompt',str(path)])
    t.main()
    assert path.exists()


def test_all_ted_sectors_retained_with_report_decisions(tmp_path,monkeypatch):
    import re

    cases=[
        ('LAN_KIEMELT','competition','kiemelt',95,'accepted'),
        ('ROUTING_VIZSGALANDO','competition','ellenőrzendő',60,'review'),
        ('IRODAI_BUTOR','competition','nem releváns',10,'rejected'),
        ('TUZFAL_EREDMENY','contract award','kiemelt',90,'rejected'),
        ('LAN_MODOSITAS','contract modification','kiemelt',90,'rejected'),
        ('LEJART_SWITCH','competition','kiemelt',90,'rejected'),
        ('NEM_ERTEKELT','competition',None,None,'unrated')]
    records=[]
    for index,(title,notice,decision,score,state) in enumerate(cases,1):
        row=web_ted_record(id=f'{800000+index}-2026',title=title,notice_type=notice)
        row['url']=f'https://ted.europa.eu/hu/notice/-/detail/{row["id"]}'
        row['source_metadata']['evidence_url']=row['url']
        if title=='LEJART_SWITCH':row['submission_deadline']='2000-01-01'
        records.append(row)
    source=tmp_path/'ted.json'
    source.write_text(json.dumps(web_ted_payload(records,[{
        'id':'unverified','title':'NEM_IGAZOLT_LAN','notice_type':'competition',
        'url':'https://example.org/fictional'}])),encoding='utf-8')
    collected=tmp_path/'input.json'
    monkeypatch.setattr(sys,'argv',['tender_tools','--ted-web-input',str(source),'--start','2026-10-26','--end','2026-10-27','--out',str(collected)])
    t.main()
    data=json.loads(collected.read_text(encoding='utf-8'))
    assert len(data['records'])==8
    assert len([r for r in data['records'] if r['source']=='TED'])==7
    by_title={r['title']:r for r in data['records']}
    assessments={by_title[title]['record_key']:{'decision':decision,'score':score,'reason':'Fiktív szakmai értékelés'}
                 for title,notice,decision,score,state in cases if decision}
    assessments[by_title['NEM_IGAZOLT_LAN']['record_key']]={'decision':'kiemelt','score':95,'reason':'Szakmailag kapcsolódó, nem igazolt jelölt'}
    ratings=tmp_path/'ratings.json'
    ratings.write_text(json.dumps(assessments),encoding='utf-8')
    target=tmp_path/'report'
    monkeypatch.setattr(sys,'argv',['create_report','--input',str(collected),'--assessments',str(ratings),'--outdir',str(target)])
    report.main()
    rendered=(target/'riport.html').read_text(encoding='utf-8')
    email=(target/'outlook.html').read_text(encoding='utf-8')
    output=json.loads((target/'report.json').read_text(encoding='utf-8'))
    assert len(output['records'])==8
    rows=re.findall(r'<tr class="decision-([a-z]+)">(.*?)</tr>',rendered,re.S)
    assert len(rows)==8
    for title,notice,decision,score,state in cases:
        found=[(color,row) for color,row in rows if title in row]
        assert len(found)==1 and found[0][0]==state
        assert (title in email)==(state in ('accepted','review'))
    candidate=[row for color,row in rows if 'NEM_IGAZOLT_LAN' in row]
    assert len(candidate)==1 and 'ellenőrizetlen forrás' in candidate[0]
    assert 'NEM_IGAZOLT_LAN' not in email
    award=next(row for color,row in rows if 'TUZFAL_EREDMENY' in row)
    assert '<td>90</td>' in award and 'Emailből kizárva:' in award
    assert 'Elfogadva – emailbe kerül' in rendered and 'Ellenőrzendő – emailbe kerül' in rendered


def test_default_file_workflow_does_not_open_network(tmp_path,monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('Fájlimport közben nem nyitható hálózati kapcsolat')
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    target=tmp_path/'input.json'
    monkeypatch.setattr(sys,'argv',['tender_tools','--source-file','EKR=tests/fixtures/sample_ekr.csv','--out',str(target)])
    t.main()
    result=json.loads(target.read_text(encoding='utf-8'))
    assert result['ekr_status']=='success' and result['ted_status']=='not_attempted'
    assert len(result['records'])==4


def test_screenshot_cells_in_metadata_reach_idpr_email():
    records,details=t.import_source('IDPR',{'status':'partial','records':[
        {'title':'Fiktív LAN','notice_type':'Versenyújranyitás','source_metadata':{
            'Ajánlatkérő nevében eljár':'Fiktív Központi Beszerző','Becsült érték':'48 000 000','Pénznem':'HUF','Státusz':''}},
        {'title':'Fiktív tűzfalak','notice_type':'Versenyújranyitás','source_metadata':{'extracted_fields':{
            'buyer_on_behalf':'Fiktív Központi Beszerző','value':22500000,'currency':'HUF','value_kind':'becsült érték'}}}
    ]})
    assert [r['procurement_value'] for r in records]==['48000000','22500000']
    assert all(r['buyer_on_behalf']=='Fiktív Központi Beszerző' for r in records)
    assert all(r['value_kind']=='becsült érték' and r['procedure_status']=='' for r in records)
    rendered=report.table(records,False)
    assert '48 000 000,00 HUF' in rendered and '22 500 000,00 HUF' in rendered
    assert rendered.count('Fiktív Központi Beszerző')==2
    assert '>Aktív<' not in rendered
    assert all(r['source_metadata'] for r in records)


def test_explicit_source_status_and_values_are_preserved():
    r=record(source='IDPR',value='0 HUF',buyer_on_behalf='Forrás szerinti szervezet',procedure_status='Bírálat alatt',
             source_metadata={'buyer_on_behalf':'Másik szervezet','value':'48000000','Státusz':'Másik státusz'})
    assert r['buyer_on_behalf']=='Forrás szerinti szervezet' and r['procurement_value']=='0'
    rendered=report.table([r],False)
    assert 'Bírálat alatt' in rendered and 'Másik szervezet' not in rendered
    assert '0,00 HUF' in rendered
    assert parse_money(0,'HUF')==('0','HUF')


def test_metadata_notes_do_not_become_source_values():
    r=record(source='IDPR',value='',source_metadata={'extraction_notes':'Becsült érték: talán 48000000',
                                                   'columns':{'Becsült érték':'Nem olvasható','Státusz':''}})
    assert r['procurement_value'] is None and r['procedure_status']==''
    assert '48 000 000' not in report.table([r],False)
