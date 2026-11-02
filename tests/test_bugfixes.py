import json
import re
import sys
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import create_report as report
import ekr_connector as ekr
import tender_tools as t
from processing import classify, enrich, opportunity, parse_date, parse_money


@pytest.mark.parametrize(('text','expected'), [
    ('2026. 11. 12.','2026-11-12'), ('2026. 11. 12. 10:00','2026-11-12'),
    ('2026.11.12.','2026-11-12'), ('12. 11. 2026','2026-11-12'), ('123456-2026',''),
])
def test_hungarian_spaced_dates(text, expected):
    assert parse_date(text)==expected


def test_spaced_expired_deadline_is_not_an_opportunity():
    import datetime as dt
    r=enrich({'source':'EKR','id':'x','title':'LAN','notice_type':'Ajánlati felhívás','deadline':'2026. 10. 01. 10:00'})
    assert not opportunity(r,dt.date(2026,11,2))


@pytest.mark.parametrize(('text','expected'), [
    ('250.000 Ft',('250000','HUF')), ('1.500 HUF',('1500','HUF')), ('1,500 EUR',('1500','EUR')),
    ('1,5 EUR',('1.5','EUR')), ('12,50 EUR',('12.50','EUR')), ('1.234.567,80 Ft',('1234567.80','HUF')),
])
def test_single_thousands_separator(text, expected):
    assert parse_money(text)==expected


def test_preliminary_remedy_is_not_preliminary_notice():
    assert classify('Előzetes vitarendezési kérelem')=='unknown'
    assert classify('Előzetes tájékoztató')=='preliminary'


def test_rejected_and_unmatched_assessments_are_reported():
    r=enrich({'source':'EKR','id':'a','title':'LAN','notice_type':'Ajánlati felhívás'})
    issues=report.apply_assessments([r],{
        'EKR:a':{'decision':'ellenőrzendő','score':85,'reason':'x'},
        'EKR:nincs':{'decision':'kiemelt','score':90,'reason':'x'}})
    assert r['assessment']['decision']=='nem értékelt'
    assert any('EKR:a' in i and 'kiemelt' in i for i in issues)
    assert any('EKR:nincs' in i and 'record_key' in i for i in issues)


def test_assessment_issues_reach_cli_output_and_report(tmp_path):
    import os, subprocess
    r=enrich({'source':'EKR','id':'a','title':'LAN','notice_type':'Ajánlati felhívás'})
    (tmp_path/'in.json').write_text(json.dumps({'records':[r],'sources':{'EKR':{'status':'success'}}}),encoding='utf-8')
    (tmp_path/'a.json').write_text(json.dumps({'EKR:a':{'decision':'kiemelt','score':50,'reason':'x'}}),encoding='utf-8')
    root=Path(__file__).resolve().parents[1]
    out=subprocess.run([sys.executable,str(root/'scripts/create_report.py'),'--input',str(tmp_path/'in.json'),
                        '--assessments',str(tmp_path/'a.json'),'--outdir',str(tmp_path/'r')],check=True,capture_output=True,
                       env={**os.environ,'PYTHONIOENCODING':'utf-8'})
    assert json.loads(out.stdout.decode('utf-8'))['assessment_issues']
    assert 'Elutasított értékelés' in (tmp_path/'r/riport.html').read_text(encoding='utf-8')


def test_ekr_email_does_not_label_ambiguous_deadline_as_submission():
    rows,_=ekr.normalize_ekr_sheet([['Ajánlatkérő','Tárgy','Határidő','Hirdetmény típusa'],
                                    ['Fiktív','LAN','2099-11-03','Ajánlati felhívás']],'f.csv')
    rendered=report.table(rows,False,'EKR')
    assert '2099.11.03 (nem igazolt ajánlattételi határidő)' in rendered
    clear,_=ekr.normalize_ekr_sheet([['Ajánlatkérő','Tárgy','Ajánlattételi határidő'],['Fiktív','LAN','2099-11-03 10:00']],'f.csv')
    assert re.search(r'>2099\.11\.03 10:00<',report.table(clear,False,'EKR'))


@pytest.mark.parametrize(('name','heading'), [
    ('IDPR','IDPR-en'), ('EKR','EKR-en'), ('ARIBA','ARIBA-n'), ('FLUENTA','FLUENTA-n'), ('UNIVERZAL','Univerzálon')])
def test_email_heading_suffix(name, heading):
    assert report.source_heading(name)==heading


def test_ted_skip_reason_reaches_report(tmp_path, monkeypatch):
    source=tmp_path/'ekr.csv'
    source.write_text('Ajánlatkérő;Tárgy\nFiktív;LAN\n',encoding='utf-8')
    target=tmp_path/'input.json'
    monkeypatch.setattr(sys,'argv',['tender_tools','--source-file',f'EKR={source}',
                                  '--ted-skipped','felhasználó kérésére kihagyva','--out',str(target)])
    t.main()
    data=json.loads(target.read_text(encoding='utf-8'))
    assert data['sources']['TED']['status']=='not_attempted'
    monkeypatch.setattr(sys,'argv',['create_report','--input',str(target),'--outdir',str(tmp_path/'r')])
    report.main()
    assert 'Nem történt lekérés (TED-webkeresés: felhasználó kérésére kihagyva)' in (tmp_path/'r/riport.html').read_text(encoding='utf-8')


def test_failed_ted_web_has_no_coverage_warning():
    _,details,_=t.import_ted_web({'status':'failed','records':[],'warnings':['Nincs webes eszköz']})
    assert details['status']=='failed'
    assert not any('lefedettsége' in w for w in details['warnings'])


def test_xlsx_without_dimension_element(tmp_path):
    workbook=Workbook();sheet=workbook.active
    sheet.append(['Ajánlatkérő','Tárgy']);sheet.append(['Fiktív','Router'])
    plain=tmp_path/'plain.xlsx';workbook.save(plain)
    stripped=tmp_path/'nodim.xlsx'
    with zipfile.ZipFile(plain) as src, zipfile.ZipFile(stripped,'w') as dst:
        for item in src.infolist():
            data=src.read(item.filename)
            if item.filename.startswith('xl/worksheets/sheet'):
                data=re.sub(rb'<dimension[^>]*/>',b'',data)
            dst.writestr(item,data)
    rows,_=ekr.import_ekr(stripped)
    assert rows[0]['title']=='Router'
