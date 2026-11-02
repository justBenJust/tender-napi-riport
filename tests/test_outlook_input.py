"""Hand-transcribed fictional email input; no live Claude connector or AI extraction."""
import copy
import datetime as dt
import json
from pathlib import Path
import socket
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import tender_tools as tools
import ekr_connector
import create_report as report

FIXTURES = Path(__file__).parent / 'fixtures'


def email_input():
    return json.loads((FIXTURES / 'idpr_outlook.json').read_text(encoding='utf-8'))


def collect(monkeypatch, target, *args):
    def no_network(*args, **kwargs):
        raise AssertionError('Outlook JSON import must not open a network connection')
    monkeypatch.setattr(socket.socket, 'connect', no_network)
    # The fictional emails arrived on 30 October; the report window is that single day.
    monkeypatch.setattr(tools, 'get_budapest_today', lambda: dt.date(2026, 10, 30))
    monkeypatch.setattr(sys, 'argv', ['tender_tools', *map(str, args), '--out', str(target)])
    tools.main()
    return json.loads(target.read_text(encoding='utf-8'))


def make_report(monkeypatch, source, target, assessments=None):
    monkeypatch.setattr(report, 'get_budapest_today', lambda: dt.date(2026, 10, 30))
    args = ['create_report', '--input', str(source), '--outdir', str(target)]
    if assessments:
        args += ['--assessments', str(assessments)]
    monkeypatch.setattr(sys, 'argv', args)
    report.main()
    return (target / 'riport.html').read_text(encoding='utf-8'), (target / 'outlook.html').read_text(encoding='utf-8')


def test_idpr_email_json_uses_existing_import_and_report(tmp_path, monkeypatch):
    source = tmp_path / 'input.json'
    data = collect(monkeypatch, source, '--source-input', f'IDPR={FIXTURES / "idpr_outlook.json"}',
                   '--source-file', f'EKR={FIXTURES / "sample_ekr.csv"}')
    assert len(data['records']) == 5 and data['ekr_status'] == 'success'
    assert data['ted_status'] == 'not_attempted'
    assert 'OUTLOOK' not in data['sources']
    idpr = next(row for row in data['records'] if row['source'] == 'IDPR')
    assert idpr['record_key'] == 'IDPR:FIKTIV-IDPR-001'
    assert idpr['classification'] == 'active'
    assert idpr['publication_date'] == ''
    assert idpr['submission_deadline'] == '2026-11-12 10:00'
    assert idpr['performance_deadline'] == '2027-02-28'
    assert idpr['procurement_value'] == '48000000' and idpr['currency'] == 'HUF'
    assert idpr['procedure_status'] == ''
    assert idpr['source_metadata']['email']['received_at'] == '2026-10-30T08:15:00+01:00'
    assert data['sources']['IDPR']['metadata']['collection_channel'] == 'outlook_connector'
    # The fixture was manually transcribed from this message, not extracted by a new parser.
    original = (FIXTURES / 'idpr_email.txt').read_text(encoding='utf-8')
    for field in ('id', 'title', 'buyer', 'buyer_on_behalf', 'submission_deadline', 'performance_deadline', 'value', 'url'):
        assert idpr[field] in original
    ratings = tmp_path / 'ratings.json'
    ratings.write_text(json.dumps({idpr['record_key']: {
        'score': 90, 'decision': 'kiemelt', 'reason': 'Fiktív, kézzel megadott értékelés hálózati beszerzésre.'}}), encoding='utf-8')
    rendered, email = make_report(monkeypatch, source, tmp_path / 'report', ratings)
    assert 'IDPR-en:' in email and idpr['title'] in email
    assert 'Fiktív Központi Beszerző' in email and '48 000 000,00 HUF' in email
    assert '2026.11.12 10:00' in email and 'Másolás Outlookhoz' in email
    assert 'decision-accepted' in rendered
    assert {p.name for p in (tmp_path / 'report').iterdir()} == {'riport.html', 'outlook.html', 'report.json'}


@pytest.mark.parametrize('message', [
    'A Microsoft 365 connector nincs csatlakoztatva.',
    'Az engedélyezett tenderes mappa nem érhető el.',
    'A kijelölt postafiók/mappa nem szűkíthető biztonságosan.'
])
def test_outlook_failure_does_not_block_existing_ekr(tmp_path, monkeypatch, message):
    failed = tmp_path / 'failed.json'
    failed.write_text(json.dumps({'status': 'failed', 'records': [], 'warnings': [message],
                                  'metadata': {'collection_channel': 'outlook_connector'}}), encoding='utf-8')
    source = tmp_path / 'input.json'
    data = collect(monkeypatch, source, '--source-input', f'IDPR={failed}', '--source-file', f'EKR={FIXTURES / "sample_ekr.csv"}')
    assert data['sources']['IDPR']['status'] == 'failed'
    assert data['ekr_status'] == 'success' and len(data['records']) == 4
    rendered, email = make_report(monkeypatch, source, tmp_path / 'report')
    assert message in rendered
    assert 'IDPR: Nem elérhető / sikertelen' in rendered
    assert 'A forrás adatai nem érhetők el.' in email


def test_repeated_emails_keep_existing_id_and_hash_dedup():
    payload = email_input()
    known, _ = tools.import_source('IDPR', payload)
    again = copy.deepcopy(payload)
    again['metadata']['collected_at'] = '2026-10-30T12:00:00+01:00'
    repeated, _ = tools.import_source('IDPR', again)
    assert len(tools.dedup(known + repeated)) == 1

    first = copy.deepcopy(payload['records'][0])
    first['id'] = ''
    second = copy.deepcopy(first)
    second['title'] = 'Második, azonosító nélküli beszerzés'
    second['source_metadata']['email_item_index'] = 2
    without_ids = {**payload, 'records': [first, second]}
    rows, _ = tools.import_source('IDPR', without_ids)
    later, _ = tools.import_source('IDPR', {**without_ids, 'metadata': again['metadata']})
    assert all(row['id'] == '' and row['record_key'].startswith('IDPR:sha256:') for row in rows)
    assert len(tools.dedup(rows + later)) == 2


def test_same_source_export_and_mail_combine_without_new_pipeline(tmp_path, monkeypatch):
    export = tmp_path / 'idpr.csv'
    export.write_text('Iktatószám;Ajánlatkérő;Tárgy;Hirdetmény típusa\n'
                      'FIKTIV-IDPR-001;Fiktív intézmény;Vállalati hálózati eszközök beszerzése;Ajánlati felhívás\n', encoding='utf-8')
    manual, _ = ekr_connector.import_ekr(export, source='IDPR')
    payload = email_input()
    emails, _ = tools.import_source('IDPR', payload)
    merged = {**payload, 'records': tools.dedup(emails + manual)}
    merged['metadata']['channels'] = {
        'outlook_connector': {'status': 'partial'}, 'manual_export': {'status': 'success'}}
    path = tmp_path / 'merged.json'
    path.write_text(json.dumps(merged), encoding='utf-8')
    ariba = tmp_path / 'ariba.json'
    ariba.write_text(json.dumps({'status': 'success', 'records': [{
        'id': 'FIKTIV-ARIBA-001', 'title': 'Ariba hálózati tender', 'notice_type': 'competition',
        'source_metadata': {'collection_channel': 'outlook_connector'}}]}), encoding='utf-8')
    data = collect(monkeypatch, tmp_path / 'input.json', '--source-input', f'IDPR={path}', '--source-input', f'ARIBA={ariba}')
    assert len(data['records']) == 2
    assert {row['source'] for row in data['records']} == {'IDPR', 'ARIBA'}
    assert data['sources']['IDPR']['metadata']['channels']['manual_export']['status'] == 'success'
    assert next(row for row in data['records'] if row['source'] == 'IDPR')['source_metadata']['email']['message_id'] == 'fiktiv-email-001'


def test_link_only_email_remains_incomplete_and_out_of_active_email(tmp_path, monkeypatch):
    payload = email_input()
    row = payload['records'][0]
    row.update(id='', buyer='', buyer_on_behalf='', title='Új beszerzési értesítés',
               description='', notice_type='', procedure_type='', submission_deadline='', deadline_time='',
               performance_deadline='', value='', currency='', value_kind='', framework='')
    payload['warnings'].append('A levél csak portállinket tartalmaz; a beszerzés adatai hiányoznak.')
    path = tmp_path / 'link.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    source = tmp_path / 'input.json'
    data = collect(monkeypatch, source, '--source-input', f'IDPR={path}')
    imported = data['records'][0]
    assert imported['classification'] == 'unknown'
    assert imported['publication_date'] == '' and imported['deadline'] == ''
    ratings = tmp_path / 'ratings.json'
    ratings.write_text(json.dumps({imported['record_key']: {
        'score': 50, 'decision': 'ellenőrzendő', 'reason': 'A portállink alapján nem ismert a műszaki tartalom.'}}), encoding='utf-8')
    rendered, email = make_report(monkeypatch, source, tmp_path / 'report', ratings)
    assert row['title'] in rendered and 'decision-rejected' in rendered
    assert row['title'] not in email and '<table ' not in email
