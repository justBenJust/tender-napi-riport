"""Email period line, automatic historical assessments, version stamp and removed legacy options."""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import create_report as report
import tender_tools as tools
from processing import enrich


def rec(**kwargs):
    return enrich({'source': 'TED', 'id': kwargs.pop('id', '1-2026'), 'buyer': 'Fiktív', 'title': 'LAN',
                   'notice_type': 'competition', 'submission_deadline': '2099-01-01', **kwargs})


@pytest.mark.parametrize(('window', 'expected'), [
    ({'start': '2026-10-31', 'end': '2026-11-02'}, '2026.10.31. – 2026.11.02. (3 nap)'),
    ({'start': '2026-11-02', 'end': '2026-11-02'}, '2026.11.02. (1 nap)'),
    ({}, ''), (None, '')])
def test_period_text(window, expected):
    assert report.period_text(window) == expected


def test_email_shows_period():
    mail = report.render_email([rec()], {'TED': {'status': 'success'}}, {'start': '2026-10-31', 'end': '2026-11-02'})
    assert '<b>Időszak:</b> 2026.10.31. – 2026.11.02. (3 nap)' in mail
    assert mail.index('Időszak:') < mail.index('TED-en:')


def test_results_and_modifications_are_assessed_automatically():
    award = rec(id='2-2026', notice_type='result (can-standard)')
    modif = rec(id='3-2026', notice_type='cont-modif (can-modif)')
    active = rec(id='4-2026')
    assert report.apply_assessments([award, modif, active], {}) == []
    for r in (award, modif):
        assert r['assessment']['decision'] == 'történeti' and r['assessment']['score'] is None
        assert r['assessment']['method'] == 'auto_historical' and r['review'] == 'automatikus'
    assert active['assessment']['decision'] == 'nem értékelt'


def test_explicit_claude_assessment_of_a_result_still_wins():
    award = rec(id='2-2026', notice_type='result (can-standard)')
    report.apply_assessments([award], {award['record_key']: {'decision': 'kiemelt', 'score': 90, 'reason': 'Tűzfal'}})
    assert award['assessment']['score'] == 90 and award['assessment']['method'] == 'claude'


def test_report_marks_historical_and_stamps_version(tmp_path, monkeypatch):
    records = [rec(id='2-2026', notice_type='result (can-standard)', title='EREDMENY TUZFAL'), rec(id='4-2026', title='AKTIV LAN')]
    source = tmp_path / 'in.json'
    source.write_text(json.dumps({'records': records, 'sources': {'TED': {'status': 'success'}},
                                  'search_window': {'start': '2026-11-02', 'end': '2026-11-02', 'days': 1}}), encoding='utf-8')
    ratings = tmp_path / 'a.json'
    ratings.write_text(json.dumps({'TED:4-2026': {'decision': 'kiemelt', 'score': 90, 'reason': 'LAN'}}), encoding='utf-8')
    monkeypatch.setattr(report, 'get_budapest_today', lambda: dt.date(2026, 11, 2))
    monkeypatch.setattr(sys, 'argv', ['create_report', '--input', str(source), '--assessments', str(ratings),
                                      '--outdir', str(tmp_path / 'r')])
    report.main()
    riport = (tmp_path / 'r/riport.html').read_text(encoding='utf-8')
    mail = (tmp_path / 'r/outlook.html').read_text(encoding='utf-8')
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    assert 'Történeti – nem kerül az emailbe' in riport and 'történeti (automatikus) 1' in riport
    assert f'Skill-verzió: {version}' in riport
    assert json.loads((tmp_path / 'r/report.json').read_text(encoding='utf-8'))['skill_version'] == version
    assert 'AKTIV LAN' in mail and 'EREDMENY TUZFAL' not in mail and 'Időszak:' in mail
    assert 'rekordkorlát' not in riport


def test_legacy_ekr_option_is_removed(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['tender_tools', '--ekr', 'x.csv'])
    with pytest.raises(SystemExit):
        tools.main()


def test_version_file_is_packaged(tmp_path):
    from build_skill import build
    from zipfile import ZipFile
    with ZipFile(build(tmp_path / 'skill.zip')) as archive:
        assert archive.read('tender-napi-riport/VERSION') == (ROOT / 'VERSION').read_bytes()
