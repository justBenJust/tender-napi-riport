import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import tender_tools as t
import ekr_connector as ekr
import create_report as rp
from create_report import table


class Check(unittest.TestCase):
    def test_ekr_csv(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'EKR_lista.csv'
            f.write_text('Ajánlatkérő;Tárgy;Ajánlattételi határidő;Becsült érték;Pénznem;Hivatkozás\nNAV;Cisco switchek;2026.11.08.;10000000;HUF;https://example.org/123\n',encoding='utf-8')
            rows,w=ekr.import_ekr(f)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['deadline'],'2026-11-08')
            self.assertEqual(rows[0]['value_kind'],'becsült érték')
    def test_xlsx_import(self):
        from openpyxl import Workbook
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'EKR_2026.xlsx'
            workbook=Workbook();sheet=workbook.active
            sheet.append(['Ajánlatkérő','Tárgy']);sheet.append(['NAV','Switch beszerzés'])
            workbook.save(f)
            records,w=ekr.import_ekr(f)
            self.assertEqual(records[0]['title'],'Switch beszerzés')
    def test_dedup_and_both_sources(self):
        base={'source':'EKR','id':'x','buyer':'NAV','title':'Teszt','deadline':''}
        ted={**base,'source':'TED'}
        self.assertEqual(len(t.dedup([base,base,ted])),2)
    def test_score_and_safe_html(self):
        r={'source':'TED','id':'1','buyer':'NAV','title':'<script>alert(1)</script>','deadline':'', 'value':'', 'url':'javascript:alert(1)'}
        rp.apply_assessments([r],{'TED:1':{'decision':'kiemelt','score':90,'reason':'Relevant'}})
        self.assertEqual(r['assessment']['score'],90)
        s=table([r],False)
        self.assertNotIn('<script>',s)
        self.assertNotIn('javascript:',s)
    def test_no_fake_rating(self):
        r={'source':'TED','id':'1','buyer':'','title':'t','deadline':''}
        rp.apply_assessments([r],{})
        self.assertIsNone(r['assessment']['score'])
        self.assertEqual(r['assessment']['decision'],'nem értékelt')
    def test_excel_formula_csv(self):
        self.assertEqual(rp.safe_excel('=WEBSERVICE("abc")')[0],"'")

if __name__=='__main__':unittest.main()
