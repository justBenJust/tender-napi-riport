"""Validate samples and confirm the Skill archive excludes this directory."""
import collections
import json
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
PROJECT=ROOT.parent
sys.path.insert(0,str(PROJECT/'scripts'))
from ekr_connector import import_ekr
from tender_tools import extract_docx
from build_skill import build
from openpyxl import load_workbook

expected={'active':5,'preliminary':1,'consultation':1,'award':1,'modification':1,'unknown':1}
checked=collections.Counter()
for path in sorted((ROOT/'01_csv').glob('*.csv'))+sorted((ROOT/'02_excel').glob('*.xlsx')):
    rows,warnings=import_ekr(path)
    assert len(rows)==10,(path,len(rows))
    assert dict(collections.Counter(r['classification'] for r in rows))==expected,path
    assert rows[0]['buyer']=='TESZT Nemzeti Adó- és Vámhivatal'
    assert rows[0]['deadline_time']=='10:00'
    assert not rows[9]['submission_deadline'] and not rows[9]['deadline']
    checked[path.suffix]+=1
for path in sorted((ROOT/'05_hianyos_es_biztonsagi').glob('*.csv'))+sorted((ROOT/'05_hianyos_es_biztonsagi').glob('*.xlsx')):
    rows,_=import_ekr(path)
    assert len(rows)==3 and not rows[0]['url'] and not rows[2]['deadline']
    checked[path.suffix]+=1
for path in ROOT.rglob('*.xlsx'):
    book=load_workbook(path,data_only=False)
    assert len(book.worksheets)==1
    assert all(cell.data_type!='f' for sheet in book for row in sheet for cell in row)
    book.close()
with tempfile.TemporaryDirectory() as temporary:
    directory=Path(temporary)
    for index,path in enumerate(sorted(ROOT.rglob('*.docx'))):
        with ZipFile(path) as archive:
            assert archive.testzip() is None
            for name in archive.namelist():
                if name.endswith(('.xml','.rels')):ET.fromstring(archive.read(name))
        manifest=extract_docx(path,directory/str(index))
        expected_images=6 if path.name.startswith('Vegyes') else 1 if 'hianyos' in path.name else 3
        assert len(manifest['images'])==expected_images,(path,manifest)
        assert not manifest['warnings'],(path,manifest['warnings'])
        checked['.docx']+=1
    fresh=build(directory/'skill.zip')
    for archive_path in (fresh,PROJECT/'dist/tender-napi-riport.zip'):
        with ZipFile(archive_path) as archive:
            assert not any('claude_tesztanyagok' in name or name.endswith(('.csv','.xlsx','.docx','.png')) for name in archive.namelist()),archive_path
            assert len([name for name in archive.namelist() if name.endswith('.py')])==4
summary={**dict(checked),'watchlist_xlsx':len(list((ROOT/'06_vart_beszerzesek').glob('*.xlsx'))),
         'png':len(list((ROOT/'04_kepforrasok').glob('*.png'))),'zip_exclusion':'verified_current_and_fresh_build'}
print(json.dumps(summary,ensure_ascii=True,indent=2))
(ROOT/'_eszkozok/ellenorzes.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
