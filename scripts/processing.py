"""Shared factual normalization. No AI inference and no network operations."""
import datetime as dt
import hashlib
import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def normalized_key(x):
  # Repair common UTF-8 bytes decoded as a Western encoding, only if reversible.
  x=str(x or '')
  for codec in ('cp1252','latin1'):
    if any(mark in x for mark in ('Ã','Å','Ä')):
      try:x=x.encode(codec).decode('utf-8')
      except (UnicodeError,LookupError):pass
  text = unicodedata.normalize('NFKD',str(x or '')).encode('ascii','ignore').decode('ascii').lower()
  return re.sub(r'[^a-z0-9]+',' ',text).strip()


def safe_url(value):
    value = str(value or '').strip()
    try:
        parsed = urlsplit(value)
        if parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password and not any(ord(c) < 33 for c in value):
            return value
    except ValueError:
        pass
    return ''


def parse_date(value):
    value = str(value or '').strip()
    if not value:
        return ''
    try:
        if re.fullmatch(r'\d+(?:\.0)?', value) and 25000 < float(value) < 100000:
            return (dt.datetime(1899, 12, 30) + dt.timedelta(days=float(value))).date().isoformat()
        # Hungarian dates are usually written with spaces: "2026. 11. 12. 10:00".
        match = re.search(r'(?<!\d)(\d{4})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{1,2})(?!\d)', value)
        if match:
            return dt.date(*map(int, match.groups())).isoformat()
        match = re.fullmatch(r'(\d{1,2})\s*[./]\s*(\d{1,2})\s*[./]\s*(\d{4})\.?', value)
        if match:
            d, m, y = map(int, match.groups())
            return dt.date(y, m, d).isoformat()
    except (ValueError, OverflowError):
        pass
    return ''


def parse_money(value, currency=''):
    text = str(value if value is not None else '').strip()
    found = re.search(r'\b(HUF|EUR|USD|GBP|Ft)\b', text, re.I)
    curr = str(currency or (found.group() if found else '')).upper()
    if curr == 'FT':
        curr = 'HUF'
    if not re.fullmatch(r'[A-Z]{3}', curr):
        curr = ''
    number = re.sub(r'\b(HUF|EUR|USD|GBP|Ft)\b', '', text, flags=re.I)
    number = re.sub(r'[\s\u00a0\u202f]', '', number)
    if ',' in number and '.' in number:
        decimal = ',' if number.rfind(',') > number.rfind('.') else '.'
        number = number.replace('.' if decimal == ',' else ',', '').replace(decimal, '.')
    # Money has at most two decimals, so exactly three digits after a lone separator are thousands.
    elif ',' in number:
        number = number.replace(',', '') if re.fullmatch(r'\d{1,3}(?:,\d{3})+',number) else number.replace(',', '.')
    elif re.fullmatch(r'\d{1,3}(?:\.\d{3})+', number):
        number = number.replace('.', '')
    try:
        amount = Decimal(number)
        if amount.is_finite() and amount >= 0:
            return str(amount), curr
    except InvalidOperation:
        pass
    return None, curr


def classify(notice_type, status=''):
    """Result/modification evidence takes precedence over planning or competition."""
    value = normalized_key(str(notice_type or '') + ' ' + str(status or ''))
    # "Előzetes vitarendezés" is a legal remedy, not a preliminary notice.
    value = value.replace('elozetes vitarendez', 'vitarendez')
    rules = [
        ('not_tender', ('nem tender', 'not tender')),
        ('modification', ('szerzodesmodositas', 'szerzodes modositas', 'contract modification', 'cont modif')),
        ('award', ('eredmeny', 'contract award', 'award', 'result', 'lezart', 'befejezett', 'szerzodes oda')), 
        ('consultation', ('piaci konzultacio', 'market consultation', 'consultation')),
        ('preliminary', ('elozetes', 'indikat', 'planning', 'prior information', 'pin only', 'pin time')),
        ('active', ('competition', 'ajanlati felhivas', 'ajanlatteteli felhivas', 'reszveteli felhivas', 'eljarast megindito', 'contract notice', 'cn standard', 'versenyujranyitas', 'verseny ujranyitas', 'kozvetlen megrendeles')),
    ]
    for category, phrases in rules:
        if any(phrase in value for phrase in phrases):
            return category
    return 'unknown'


def enrich(record, metadata=None):
    record = dict(record)
    original_metadata = metadata if metadata is not None else record.get('source_metadata', {})
    # Recover explicitly transcribed source cells, never values from narrative notes.
    aliases = {
        'buyer_on_behalf': ('buyer_on_behalf', 'Ajánlatkérő nevében eljár', 'acting_on_behalf'),
        'value': ('value', 'Megrendelés értéke', 'Becsült érték', 'Szerződés értéke', 'Érték', 'estimated_value', 'order_value'),
        'currency': ('currency', 'Pénznem', 'Devizanem'),
        'value_kind': ('value_kind',),
        'framework': ('framework', 'KM', 'Keretmegállapodás'),
        'procedure_type': ('procedure_type', 'Eljárás típusa'),
        'supplier': ('supplier', 'Számlakiállító szállító', 'Szállító'),
        'procedure_status': ('procedure_status', 'Státusz', 'Eljárás állapota'),
    }
    source_cells = []
    if isinstance(original_metadata, dict):
        source_cells = [original_metadata] + [original_metadata[k] for k in ('extracted_fields', 'raw_fields', 'original_fields', 'columns')
                                              if isinstance(original_metadata.get(k), dict)]
    promoted = {}
    for field, names in aliases.items():
        if record.get(field) not in ('', None):continue
        accepted = {normalized_key(name) for name in names}
        for cells in source_cells:
            found = next(((name,value) for name,value in cells.items() if normalized_key(name) in accepted
                          and isinstance(value,(str,int,float)) and not isinstance(value,bool)
                          and value not in ('',None) and normalized_key(value) not in ('nincs megadva','nem olvashato','ismeretlen','n a')),None)
            if found:
                name,value=found;record[field]=value;promoted[field]=str(name);break
    if 'value' in promoted and any(word in normalized_key(promoted['value']) for word in ('becsult','estimated')):
        if record.get('value_kind') in ('',None,'unknown','nem tisztázott'):record['value_kind']='becsült érték'
    if promoted:record['normalization_notes']={**record.get('normalization_notes',{}), 'source_fields_promoted':promoted}
    record.setdefault('procedure_status', '')
    record['classification'] = classify(record.get('notice_type'), record['procedure_status'])
    record.setdefault('submission_deadline', record.get('deadline', ''))
    record.setdefault('performance_deadline', '')
    record['deadline'] = record['submission_deadline'] or record['performance_deadline'] or record.get('deadline', '')
    amount, currency = parse_money(record.get('value'), record.get('currency', ''))
    record['procurement_value'] = amount
    record['currency'] = currency
    record.setdefault('value_kind', 'unknown')
    record.setdefault('publication_date', '')
    record.setdefault('performance_place', '')
    record['cpv_codes'] = re.findall(r'\b\d{8}(?:-\d)?\b', str(record.get('cpv', '')))
    record['url'] = safe_url(record.get('url'))
    record['source_metadata'] = original_metadata
    record.setdefault('review', 'nem értékelt')
    record.setdefault('ai_score', None)
    record.setdefault('ai_reasoning', '')
    if record.get('id'):
        record['record_key'] = f"{record['source']}:{record['id']}"
    elif not record.get('record_key'):
        digest = hashlib.sha256(json.dumps(record['source_metadata'] or record, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:24]
        record['record_key'] = f"{record['source']}:sha256:{digest}"
    record['missing_fields'] = [f for f in ('buyer', 'title', 'publication_date', 'deadline', 'value', 'url') if not record.get(f)]
    return record


def opportunity(record, today=None):
    if record.get('classification') not in ('active', 'preliminary', 'consultation'):
        return False
    deadline = parse_date(record.get('submission_deadline'))
    return not deadline or deadline >= str(today or dt.date.today())


DETAIL_FIELDS = ('business_category', 'expected_match', 'uncertainty', 'recommended_action', 'assumptions')
NOT_TENDER_ASSESSMENT = {'decision': 'nem releváns', 'score': 0, 'reason': 'A levél nem tenderértesítő; nem üzleti lehetőség.',
                         **{field: '' for field in DETAIL_FIELDS}, 'business_category': 'Nem tender', 'method': 'not_tender'}
# Results and modifications can never reach the sales email, so Claude need not assess them.
# No relevance score is invented: an explicit Claude assessment, if given, still wins.
HISTORICAL_ASSESSMENT = {'decision': 'történeti', 'score': None,
                         'reason': 'Eredmény- vagy szerződésmódosítási hirdetmény; nem új üzleti lehetőség, ezért külön Claude-értékelés nélkül.',
                         **{field: '' for field in DETAIL_FIELDS}, 'method': 'auto_historical'}


def assessment_error(value):
    """Explain why an assessment is rejected, so the problem is not silently hidden."""
    if not isinstance(value, dict):
        return 'nem JSON objektum'
    score = value.get('score')
    if type(score) is not int or not 0 <= score <= 100:
        return 'a score 0–100 közötti egész szám legyen'
    expected = 'kiemelt' if score >= 80 else 'ellenőrzendő' if score >= 45 else 'nem releváns'
    if str(value.get('decision', '')).lower() != expected:
        return f'{score} ponthoz a decision értéke „{expected}” legyen'
    if not isinstance(value.get('reason'), str) or not value['reason'].strip():
        return 'hiányzó reason'
    bad = [field for field in DETAIL_FIELDS if field in value and not isinstance(value[field], str)]
    if bad:
        return 'nem szöveges mező: ' + ', '.join(bad)
    return ''


def validate(value):
    if assessment_error(value):
        return None
    decision = str(value['decision']).lower()
    score = value['score']
    return {'decision': decision, 'score': score, 'reason': value['reason'][:2000],
            **{field: value.get(field, '')[:2000] for field in DETAIL_FIELDS}, 'method': 'claude'}


def get_budapest_today():
  try:return dt.datetime.now(ZoneInfo('Europe/Budapest')).date()
  except ZoneInfoNotFoundError:raise RuntimeError('Europe/Budapest időzóna hiányzik; telepítsd a tzdata csomagot')
