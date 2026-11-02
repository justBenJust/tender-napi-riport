"""Every Outlook email reaches the report; non-tender emails get 0 points and stay out of the sales email."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import create_report as report
import tender_tools as tools
from processing import classify, enrich
from test_outlook_input import FIXTURES, collect, make_report


def outlook_envelope(count=1, messages_read=None):
    return {'status': 'success',
            'metadata': {'collection_channel': 'outlook_connector', 'messages_read': count if messages_read is None else messages_read},
            'records': [{'id': '', 'title': f'FIKTÍV hírlevél {i}', 'notice_type': 'nem tender',
                         'source_metadata': {'collection_channel': 'outlook_connector', 'email_item_index': 1,
                                             'not_tender_reason': 'Hírlevél',
                                             'email': {'message_id': f'fiktiv-hirlevel-{i}', 'subject': f'FIKTÍV hírlevél {i}'}}}
                        for i in range(count)],
            'warnings': []}


def test_not_tender_classification():
    assert classify('nem tender') == 'not_tender'
    assert classify('Nem tender') == 'not_tender'


def test_not_tender_gets_zero_without_assessment_and_rejects_other_scores():
    r = enrich({'source': 'OUTLOOK', 'title': 'Hírlevél', 'notice_type': 'nem tender',
                'source_metadata': {'email': {'message_id': 'x'}}})
    assert report.apply_assessments([r], {}) == []
    assert r['assessment']['score'] == 0 and r['assessment']['decision'] == 'nem releváns'
    issues = report.apply_assessments([r], {r['record_key']: {'decision': 'ellenőrzendő', 'score': 50, 'reason': 'x'}})
    assert r['assessment']['score'] == 0 and any('csak 0' in i for i in issues)
    report.apply_assessments([r], {r['record_key']: {'decision': 'nem releváns', 'score': 0, 'reason': 'Saját indok'}})
    assert r['assessment']['reason'] == 'Saját indok'


def test_all_emails_reach_report_and_non_tenders_stay_out_of_email(tmp_path, monkeypatch):
    outlook = tmp_path / 'outlook.json'
    outlook.write_text(json.dumps(outlook_envelope(2), ensure_ascii=False), encoding='utf-8')
    source = tmp_path / 'input.json'
    data = collect(monkeypatch, source, '--source-input', f'IDPR={FIXTURES / "idpr_outlook.json"}',
                   '--source-input', f'OUTLOOK={outlook}')
    assert data['sources']['OUTLOOK']['report_only'] and data['sources']['OUTLOOK']['status'] == 'success'
    idpr_key = next(r['record_key'] for r in data['records'] if r['source'] == 'IDPR')
    ratings = tmp_path / 'assessments.json'
    ratings.write_text(json.dumps({idpr_key: {'decision': 'kiemelt', 'score': 90, 'reason': 'Hálózati eszközök'}}), encoding='utf-8')
    riport, mail = make_report(monkeypatch, source, tmp_path / 'report', ratings)
    assert riport.count('Nem tender – nem kerül az emailbe') == 2
    assert 'FIKTÍV hírlevél 0' in riport and 'ebből nem tender levél 2' in riport
    assert 'hírlevél' not in mail and 'OUTLOOK' not in mail
    assert 'Vállalati hálózati eszközök beszerzése' in mail


def test_missing_emails_are_flagged():
    records, details = tools.import_source('OUTLOOK', outlook_envelope(1, messages_read=3))
    tools.check_email_coverage(records, details)
    assert details['status'] == 'partial'
    assert any('3 elolvasott levélből 1' in w for w in details['warnings'])
