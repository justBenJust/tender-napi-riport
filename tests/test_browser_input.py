"""Hand-written fictional Claude in Chrome input; no live browser or portal session."""
import json
from pathlib import Path
import socket
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import tender_tools as tools

FIXTURES = Path(__file__).parent / 'fixtures'


def browser_input(**metadata):
    return {
        'status': 'success',
        'metadata': {'collection_channel': 'claude_in_chrome', 'input_kind': 'browser_session', 'pages_read': 1, **metadata},
        'records': [{
            'id': 'FIKTIV-EKR-CHROME-001', 'buyer': 'Fiktív Hálózati Hatóság', 'title': 'Vállalati LAN eszközök',
            'notice_type': 'Ajánlati felhívás', 'procedure_type': 'Nyílt eljárás', 'submission_deadline': '2099-11-20 10:00',
            'url': 'https://example.org/fictional/ekr/001',
            'source_metadata': {'collection_channel': 'claude_in_chrome', 'page_number': 1, 'visible_row': 1}}],
        'warnings': []}


def collect(tmp_path, monkeypatch, payload, *extra):
    def no_network(*args, **kwargs):
        raise AssertionError('Browser JSON import must not open a network connection')
    monkeypatch.setattr(socket.socket, 'connect', no_network)
    source = tmp_path / 'ekr_chrome.json'
    source.write_text(json.dumps(payload), encoding='utf-8')
    target = tmp_path / 'input.json'
    monkeypatch.setattr(sys, 'argv', ['tender_tools', '--source-input', f'EKR={source}', *map(str, extra), '--out', str(target)])
    tools.main()
    return json.loads(target.read_text(encoding='utf-8'))


def test_chrome_ekr_json_uses_existing_import(tmp_path, monkeypatch):
    data = collect(tmp_path, monkeypatch, browser_input(portal_result_count=1))
    ekr = data['sources']['EKR']
    assert ekr['status'] == 'success' and ekr['metadata']['collection_channel'] == 'claude_in_chrome'
    record = next(row for row in data['records'] if row['source'] == 'EKR')
    assert record['record_key'] == 'EKR:FIKTIV-EKR-CHROME-001'
    assert record['classification'] == 'active'


def test_chrome_count_mismatch_marks_partial(tmp_path, monkeypatch):
    data = collect(tmp_path, monkeypatch, browser_input(portal_result_count=3))
    assert data['sources']['EKR']['status'] == 'partial'
    assert any('3 találatot jelzett' in warning for warning in data['warnings'])


def test_chrome_without_count_stays_success_and_count_ignored_for_outlook():
    records, details = tools.import_source('EKR', browser_input())
    tools.check_browser_coverage(records, details)
    assert details['status'] == 'success'
    other = {'status': 'success', 'metadata': {'collection_channel': 'outlook_connector', 'portal_result_count': 9}}
    tools.check_browser_coverage(records, other)
    assert other['status'] == 'success'


def test_chrome_failure_does_not_block_other_sources(tmp_path, monkeypatch):
    failed = {'status': 'failed', 'metadata': {'collection_channel': 'claude_in_chrome'}, 'records': [],
              'warnings': ['Az EKR bejelentkezési oldalt mutat; a felhasználó nem jelentkezett be.']}
    source = tmp_path / 'idpr.json'
    source.write_text(json.dumps(browser_input()), encoding='utf-8')
    data = collect(tmp_path, monkeypatch, failed, '--source-input', f'IDPR={source}')
    assert data['sources']['EKR']['status'] == 'failed'
    assert data['sources']['IDPR']['status'] == 'success'
    assert any('nem jelentkezett be' in warning for warning in data['warnings'])
