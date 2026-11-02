"""One report window (calendar days, Europe/Budapest) applies to every source."""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import create_report as report
import ted_api
import tender_tools as tools

TODAY = dt.date(2026, 11, 2)


@pytest.mark.parametrize(('args', 'expected'), [
    ({}, (TODAY, TODAY)),
    ({'days': 1}, (TODAY, TODAY)),
    ({'days': 3}, (dt.date(2026, 10, 31), TODAY)),
    ({'start': '2026-10-28'}, (dt.date(2026, 10, 28), TODAY)),
    ({'start': '2026-10-28', 'end': '2026-10-30'}, (dt.date(2026, 10, 28), dt.date(2026, 10, 30))),
])
def test_report_window(args, expected):
    assert tools.report_window(TODAY, **args) == expected


@pytest.mark.parametrize('args', [{'days': 0}, {'days': 2, 'start': '2026-10-01'}, {'start': '2026-11-03'}])
def test_invalid_window(args):
    with pytest.raises(ValueError):
        tools.report_window(TODAY, **args)


def test_window_status_prefers_email_arrival():
    start, end = dt.date(2026, 10, 30), dt.date(2026, 10, 30)
    assert tools.window_status({'publication_date': '2026-10-30'}, start, end) == 'in'
    assert tools.window_status({'publication_date': '2026-10-20'}, start, end) == 'out'
    assert tools.window_status({'title': 'x'}, start, end) == 'unknown'
    # An old tender announced by an email that arrived inside the window belongs to the window.
    mail = {'publication_date': '2026-10-20', 'source_metadata': {'email': {'received_at': '2026-10-30T08:15:00+01:00'}}}
    assert tools.window_status(mail, start, end) == 'in'


def test_same_days_reach_ted_api_and_every_source(tmp_path, monkeypatch):
    seen = {}

    def fake_fetch(start, end, opener=None):
        seen['window'] = (start, end)
        return {'status': 'success', 'metadata': {'collection_method': 'ted_api'}, 'records': [], 'warnings': []}
    monkeypatch.setattr(ted_api, 'fetch', fake_fetch)
    monkeypatch.setattr(tools, 'get_budapest_today', lambda: TODAY)
    export = tmp_path / 'ekr.csv'
    export.write_text('Ajánlatkérő;Tárgy;Közzététel dátuma;Hirdetmény típusa;Ajánlattételi határidő\n'
                      'Fiktív;FRISS LAN;2026-11-01;Ajánlati felhívás;2099-01-01\n'
                      'Fiktív;REGI LAN;2026-10-20;Ajánlati felhívás;2099-01-01\n'
                      'Fiktív;DATUM NELKUL;;Ajánlati felhívás;2099-01-01\n', encoding='utf-8')
    target = tmp_path / 'input.json'
    monkeypatch.setattr(sys, 'argv', ['tender_tools', '--ted-api', '--days', '3', '--source-file', f'EKR={export}',
                                      '--out', str(target)])
    tools.main()
    data = json.loads(target.read_text(encoding='utf-8'))
    assert seen['window'] == (dt.date(2026, 10, 31), TODAY)
    assert data['search_window']['days'] == 3 and data['search_window']['start'] == '2026-10-31'
    status = {r['title']: r['window_status'] for r in data['records']}
    assert status == {'FRISS LAN': 'in', 'REGI LAN': 'out', 'DATUM NELKUL': 'unknown'}
    assert any('1 tétel a riport időszakán' in w for w in data['warnings'])

    ratings = tmp_path / 'a.json'
    ratings.write_text(json.dumps({r['record_key']: {'decision': 'kiemelt', 'score': 90, 'reason': 'LAN'}
                                   for r in data['records']}), encoding='utf-8')
    monkeypatch.setattr(report, 'get_budapest_today', lambda: TODAY)
    monkeypatch.setattr(sys, 'argv', ['create_report', '--input', str(target), '--assessments', str(ratings),
                                      '--outdir', str(tmp_path / 'r')])
    report.main()
    mail = (tmp_path / 'r/outlook.html').read_text(encoding='utf-8')
    riport = (tmp_path / 'r/riport.html').read_text(encoding='utf-8')
    assert 'FRISS LAN' in mail and 'DATUM NELKUL' in mail and 'REGI LAN' not in mail
    assert 'REGI LAN' in riport and 'a riport időszakán kívül jelent meg' in riport
    assert 'Időszak: 2026-10-31 – 2026-11-02 (3 nap, minden forrásra)' in riport


def test_web_prompt_gets_the_same_days(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, 'get_budapest_today', lambda: TODAY)
    path = tmp_path / 'prompt.md'
    monkeypatch.setattr(sys, 'argv', ['tender_tools', '--ted-web-prompt', str(path), '--days', '2'])
    tools.main()
    prompt = path.read_text(encoding='utf-8')
    assert '2026-11-01T00:00:00+01:00' in prompt and '2026-11-02T23:59:59+01:00' in prompt
