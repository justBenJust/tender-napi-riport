"""Official TED Search API (v3) client: Hungarian place of performance, by publication date.

The only network access in the skill. It needs api.ted.europa.eu on the code execution
domain allowlist; any failure is reported as a failed source, never as zero notices.
"""
import json
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation

from processing import parse_date, safe_url

API_URL = 'https://api.ted.europa.eu/v3/notices/search'
FIELDS = ['publication-number', 'notice-title', 'buyer-name', 'publication-date', 'notice-type', 'form-type',
          'procedure-type', 'place-of-performance', 'deadline-receipt-tender-date-lot', 'classification-cpv',
          'estimated-value-lot', 'estimated-value-cur-lot', 'description-lot']
PAGE_SIZE = 250
MAX_PAGES = 20


def build_query(start, end):
    return (f'place-of-performance IN (HUN) AND publication-date>={start:%Y%m%d} '
            f'AND publication-date<={end:%Y%m%d}')


def post(body, opener=urllib.request.urlopen):
    request = urllib.request.Request(API_URL, data=json.dumps(body).encode('utf-8'), method='POST',
                                     headers={'Content-Type': 'application/json', 'Accept': 'application/json',
                                              'User-Agent': 'tender-napi-riport/1.0'})
    with opener(request, timeout=60) as response:
        return json.loads(response.read().decode('utf-8'))


def text(value, joiner='; '):
    """Pick the Hungarian (else English, else first) language variant of a multilingual field."""
    if isinstance(value, dict):
        value = value.get('hun') or value.get('eng') or next(iter(value.values()), '')
    if isinstance(value, list):
        return joiner.join(dict.fromkeys(str(v).strip() for v in value if str(v).strip()))
    return str(value or '').strip()


def unique(values):
    return list(dict.fromkeys(str(v) for v in values or [] if v not in (None, '')))


def lot_value(notice):
    """Sum lot estimates only when every lot is in the same currency."""
    amounts, currencies = notice.get('estimated-value-lot') or [], unique(notice.get('estimated-value-cur-lot'))
    if not amounts or len(currencies) > 1:
        return '', '', ''
    try:
        total = sum(Decimal(str(a)) for a in amounts)
    except InvalidOperation:
        return '', '', ''
    kind = 'becsült érték' if len(amounts) == 1 else f'becsült érték ({len(amounts)} rész összege)'
    return str(total), (currencies[0] if currencies else ''), kind


def to_record(notice):
    number = str(notice.get('publication-number') or '')
    deadlines = sorted(unique(parse_date(d) for d in notice.get('deadline-receipt-tender-date-lot') or []))
    value, currency, kind = lot_value(notice)
    html = (notice.get('links') or {}).get('html') or {}
    url = safe_url(html.get('HUN') or html.get('ENG')) or f'https://ted.europa.eu/hu/notice/-/detail/{number}'
    form, code = notice.get('form-type') or '', notice.get('notice-type') or ''
    return {
        'id': number,
        'buyer': text(notice.get('buyer-name')),
        'title': text(notice.get('notice-title')),
        'description': text(notice.get('description-lot'), ' | ')[:2000],
        'publication_date': parse_date(notice.get('publication-date')),
        # classify() recognises the TED form types: competition, planning, result, cont-modif.
        'notice_type': f'{form} ({code})' if form and code else form or code,
        'procedure_type': notice.get('procedure-type') or '',
        'submission_deadline': deadlines[0] if deadlines else '',
        'value': value, 'currency': currency, 'value_kind': kind,
        'cpv': ', '.join(unique(notice.get('classification-cpv'))),
        'performance_place': ', '.join(unique(notice.get('place-of-performance'))),
        'url': url,
        'source_metadata': {'verification': 'official_api', 'performance_country': 'HUN',
                            'notice_type_code': code, 'form_type': form,
                            'lot_deadlines': deadlines if len(deadlines) > 1 else []},
    }


def fetch(start, end, opener=urllib.request.urlopen):
    """Return a normalized source envelope; network or API errors become status 'failed'."""
    query = build_query(start, end)
    metadata = {'collection_method': 'ted_api', 'coverage': 'api_full', 'api': API_URL, 'query': query,
                'search_window': {'start': start.isoformat(), 'end': end.isoformat(), 'timezone': 'Europe/Budapest',
                                  'precision': 'publication_day'}}
    notices, warnings, token, total = [], [], None, None
    try:
        for _ in range(MAX_PAGES):
            body = {'query': query, 'fields': FIELDS, 'limit': PAGE_SIZE, 'paginationMode': 'ITERATION'}
            if token:
                body['iterationNextToken'] = token
            page = post(body, opener)
            total = page.get('totalNoticeCount', total)
            notices += page.get('notices') or []
            if page.get('timedOut'):
                warnings.append('A TED API időtúllépést jelzett; a lista részleges lehet.')
            token = page.get('iterationNextToken')
            if not token or not page.get('notices') or (total is not None and len(notices) >= total):
                break
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, 'reason', exc)
        if isinstance(exc, urllib.error.HTTPError):
            reason = f'HTTP {exc.code}'
        hint = ' Ellenőrizd, hogy az api.ted.europa.eu engedélyezett domain-e a kódfuttatásban.'
        return {'status': 'failed', 'metadata': metadata, 'records': [],
                'warnings': [f'TED API nem érhető el: {reason}.{hint}']}
    metadata.update(total_notice_count=total, fetched=len(notices))
    if total is not None and len(notices) < total:
        warnings.append(f'A TED API {total} hirdetményt jelzett, ebből {len(notices)} került letöltésre.')
    return {'status': 'partial' if warnings else 'success', 'metadata': metadata,
            'records': [to_record(n) for n in notices if n.get('publication-number')], 'warnings': warnings}
