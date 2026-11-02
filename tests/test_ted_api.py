"""TED Search API client with a fake opener; the live API is not called in tests."""
import datetime as dt
import io
import json
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ted_api
import tender_tools as tools
import create_report as report

NOTICE = {
    'publication-number': '749185-2026', 'publication-date': '2026-10-29+01:00',
    'notice-type': 'cn-standard', 'form-type': 'competition', 'procedure-type': 'open',
    'buyer-name': {'hun': ['Fiktív Egyetem']},
    'notice-title': {'hun': 'Magyarország – Hálózati eszközök – Switch beszerzés', 'eng': 'Hungary – Network'},
    'place-of-performance': ['HU333', 'HUN', 'HU333', 'HUN'],
    'deadline-receipt-tender-date-lot': ['2026-12-01+01:00', '2026-11-30+01:00'],
    'classification-cpv': ['32420000', '32420000'],
    'estimated-value-lot': ['1000000.00', '2500000.00'], 'estimated-value-cur-lot': ['HUF', 'HUF'],
    'links': {'html': {'HUN': 'https://ted.europa.eu/hu/notice/-/detail/749185-2026'}},
}


class FakeOpener:
    def __init__(self, pages):
        self.pages, self.bodies = list(pages), []

    def __call__(self, request, timeout=None):
        self.bodies.append(json.loads(request.data))
        page = self.pages.pop(0)
        if isinstance(page, Exception):
            raise page
        return io.BytesIO(json.dumps(page).encode('utf-8'))


def test_query_and_record_mapping():
    opener = FakeOpener([{'notices': [NOTICE], 'totalNoticeCount': 1, 'iterationNextToken': None}])
    envelope = ted_api.fetch(dt.date(2026, 10, 29), dt.date(2026, 10, 30), opener)
    assert opener.bodies[0]['query'] == ('place-of-performance IN (HUN) AND publication-date>=20261029 '
                                         'AND publication-date<=20261030')
    assert envelope['status'] == 'success' and envelope['metadata']['fetched'] == 1
    r = envelope['records'][0]
    assert r['id'] == '749185-2026' and r['buyer'] == 'Fiktív Egyetem'
    assert r['title'].endswith('Switch beszerzés') and r['publication_date'] == '2026-10-29'
    assert r['submission_deadline'] == '2026-11-30' and r['source_metadata']['lot_deadlines'] == ['2026-11-30', '2026-12-01']
    assert (r['value'], r['currency'], r['value_kind']) == ('3500000.00', 'HUF', 'becsült érték (2 rész összege)')
    assert r['cpv'] == '32420000' and r['performance_place'] == 'HU333, HUN'
    rows, _ = tools.import_source('TED', envelope)
    assert rows[0]['classification'] == 'active' and rows[0]['record_key'] == 'TED:749185-2026'


def test_form_types_are_classified():
    for form, code, expected in [('result', 'can-standard', 'award'), ('cont-modif', 'can-modif', 'modification'),
                                 ('planning', 'pin-only', 'preliminary'), ('change', 'corr', 'unknown')]:
        rows, _ = tools.import_source('TED', {'status': 'success', 'records': [
            ted_api.to_record({**NOTICE, 'form-type': form, 'notice-type': code})]})
        assert rows[0]['classification'] == expected


def test_mixed_currencies_are_not_summed():
    r = ted_api.to_record({**NOTICE, 'estimated-value-cur-lot': ['HUF', 'EUR']})
    assert r['value'] == '' and r['currency'] == ''


def test_pagination_follows_iteration_token():
    opener = FakeOpener([{'notices': [NOTICE], 'totalNoticeCount': 2, 'iterationNextToken': 'next'},
                         {'notices': [{**NOTICE, 'publication-number': '749186-2026'}], 'totalNoticeCount': 2,
                          'iterationNextToken': 'more'}])
    envelope = ted_api.fetch(dt.date(2026, 10, 29), dt.date(2026, 10, 30), opener)
    assert len(envelope['records']) == 2 and opener.bodies[1]['iterationNextToken'] == 'next'


def test_network_failure_is_failed_not_zero_results():
    opener = FakeOpener([urllib.error.URLError('Tunnel connection failed: 403 Forbidden')])
    envelope = ted_api.fetch(dt.date(2026, 10, 29), dt.date(2026, 10, 30), opener)
    assert envelope['status'] == 'failed' and envelope['records'] == []
    assert 'api.ted.europa.eu' in envelope['warnings'][0]


def test_cli_ted_api_to_report(tmp_path, monkeypatch):
    monkeypatch.setattr(ted_api, 'post', lambda body, opener=None: {'notices': [NOTICE], 'totalNoticeCount': 1})
    target = tmp_path / 'input.json'
    monkeypatch.setattr(sys, 'argv', ['tender_tools', '--ted-api', '--start', '2026-10-29', '--end', '2026-10-30',
                                      '--out', str(target)])
    tools.main()
    data = json.loads(target.read_text(encoding='utf-8'))
    assert data['ted_status'] == 'success' and data['ted_metadata']['collection_method'] == 'ted_api'
    ratings = tmp_path / 'a.json'
    ratings.write_text(json.dumps({'TED:749185-2026': {'decision': 'kiemelt', 'score': 90, 'reason': 'Switch'}}), encoding='utf-8')
    monkeypatch.setattr(report, 'get_budapest_today', lambda: dt.date(2026, 11, 2))
    monkeypatch.setattr(sys, 'argv', ['create_report', '--input', str(target), '--assessments', str(ratings),
                                      '--outdir', str(tmp_path / 'r')])
    report.main()
    riport = (tmp_path / 'r/riport.html').read_text(encoding='utf-8')
    assert 'hivatalos TED Search API' in riport and 'Időszak: 2026-10-29 – 2026-10-30' in riport
    assert 'Switch beszerzés' in (tmp_path / 'r/outlook.html').read_text(encoding='utf-8')


def test_cli_ted_api_failure_keeps_other_sources(tmp_path, monkeypatch):
    def blocked(body, opener=None):
        raise urllib.error.URLError('blocked')
    monkeypatch.setattr(ted_api, 'post', blocked)
    source = tmp_path / 'ekr.csv'
    source.write_text('Ajánlatkérő;Tárgy\nFiktív;LAN\n', encoding='utf-8')
    target = tmp_path / 'input.json'
    monkeypatch.setattr(sys, 'argv', ['tender_tools', '--ted-api', '--source-file', f'EKR={source}', '--out', str(target)])
    tools.main()
    data = json.loads(target.read_text(encoding='utf-8'))
    assert data['ted_status'] == 'failed' and data['ekr_status'] == 'success'
    assert any('TED API nem érhető el' in w for w in data['warnings'])
