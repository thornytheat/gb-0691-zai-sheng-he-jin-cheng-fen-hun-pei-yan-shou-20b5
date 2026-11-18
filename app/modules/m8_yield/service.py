import csv, io, json
from app.config import TAP_HEADERS, LIMIT
from app.domain import mass_kg
from app.errors import DomainError
from app.numeric import number
from app.store import (all_payloads, all_tap_quarantine, all_taps, all_yields,
                       save_tap_quarantine, save_taps, upsert_yields)
from app.modules.m8_yield import rules

def parse_taps(text):
    """解析出炉实测CSV：校验结构与数值，文件内去重，冲突行隔离。"""
    if not isinstance(text, str) or not text.strip():
        raise DomainError('EMPTY', '出炉CSV为空')
    reader = csv.reader(io.StringIO(text.lstrip('\ufeff'), newline=''), strict=True)
    try: head = next(reader, None)
    except csv.Error: raise DomainError('STRUCTURE', '表头损坏')
    if head is None: raise DomainError('BLANK', '文件仅有空行')
    head = [x.strip() for x in head]
    if set(head) != set(TAP_HEADERS) or len(head) != len(TAP_HEADERS):
        raise DomainError('HEADER', '出炉字段缺失或重复，须为' + ','.join(TAP_HEADERS))
    records, isolated, seen, masses = [], [], {}, {}
    duplicated = 0
    try:
        for cells in reader:
            if not cells or all(not x.strip() for x in cells): continue
            if cells == head: continue
            if len(records) + len(isolated) >= LIMIT: raise DomainError('LIMIT', '文件超过一万行')
            raw = '|'.join(cells)
            if len(cells) != len(head):
                isolated.append({'行号': reader.line_num, 'raw': raw, '原因码': 'COLUMNS', '原因': '列数不符'})
                continue
            row = dict(zip(head, [x.strip() for x in cells]))
            row['行号'] = reader.line_num
            try:
                if not row['batch']: raise DomainError('MISSING', '炉次为空')
                if row['element'] not in rules.ELEMENTS: raise DomainError('ELEMENT', '未知元素')
                mass = mass_kg(row['tap_mass'], row['unit'])
                assay = row['tap_assay']
                if assay.startswith('<'): raise DomainError('ASSAY', '出炉实测须为确定值，检出限值不可用于结算')
                value = number(assay)
                if not 0 < value <= 100: raise DomainError('RANGE', '出炉含量超出范围')
                key = (row['batch'], row['element'])
                fingerprint = (mass, value)
                if key in seen:
                    if seen[key] == fingerprint: duplicated += 1
                    else: isolated.append({**row, 'raw': raw, '原因码': 'CONFLICT', '原因': '同一炉次元素数值不一致'})
                    continue
                if row['batch'] in masses and masses[row['batch']] != mass:
                    isolated.append({**row, 'raw': raw, '原因码': 'CONFLICT', '原因': '同一炉次出炉重量不一致'})
                    continue
                seen[key] = fingerprint
                masses.setdefault(row['batch'], mass)
                records.append({'batch': row['batch'], 'element': row['element'],
                                'tap_mass_kg': str(mass), 'tap_assay_pct': str(value), '行号': row['行号'], 'raw': raw})
            except DomainError as e:
                isolated.append({**row, 'raw': raw, '原因码': e.code, '原因': e.message})
    except csv.Error: raise DomainError('STRUCTURE', '引号未闭合或记录截断')
    if not records and not isolated: raise DomainError('HEADER_ONLY', '文件没有出炉记录')
    return records, isolated, duplicated

def submit_tap(text):
    """出炉实测入库：同炉同元素同值幂等跳过，异值隔离保留原记录。"""
    records, isolated, duplicated = parse_taps(text)
    inserted, skipped, conflicts = save_taps(records)
    quarantine = isolated + conflicts
    if quarantine: save_tap_quarantine(quarantine)
    return {'recorded': inserted, 'duplicated': duplicated + skipped,
            'isolated': [{'行号': r.get('行号'), 'batch': r.get('batch'), 'element': r.get('element'),
                          '原因码': r['原因码'], '原因': r['原因']} for r in quarantine]}

def mixture_map(current):
    """跨全部历史批次重建炉次投入；同炉投入不一致的批次标记冲突。"""
    sources = [(r['id'], json.loads(r['payload'])) for r in all_payloads()]
    if current is not None:
        ident = current['manifest']['run_id']
        sources = [s for s in sources if s[0] != ident] + [(ident, current)]
    mixtures, conflicts = {}, set()
    for run_id, payload in sources:
        for row in payload.get('mixture', []):
            key = (row['炉次'], row['元素'])
            value = (row['元素下界_kg'], row['元素上界_kg'], row['干重_kg'])
            if key in mixtures and mixtures[key]['value'] != value:
                conflicts.add(row['炉次'])
                continue
            mixtures.setdefault(key, {'value': value, 'run_id': run_id, **row})
    return mixtures, conflicts

def plan_mass(yields, taps, mixtures):
    """下一炉计划出炉量：最近已核炉出炉重量；无已核炉时退用最近炉次投入干重。"""
    if yields:
        latest = max(y['batch'] for y in yields)
        for tap in taps:
            if tap['batch'] == latest: return tap['tap_mass_kg']
    batches = sorted({k[0] for k in mixtures}, reverse=True)
    for batch in batches:
        for element in rules.ELEMENTS:
            info = mixtures.get((batch, element))
            if info is not None: return info['干重_kg']
    return None

def compute(current):
    """炉次对照与补偿视图：结算可算炉次（幂等），汇总依据并给出下一炉补偿。"""
    taps = all_taps()
    mixtures, conflicts = mixture_map(current)
    yields = all_yields()
    batches = sorted({k[0] for k in mixtures} | {t['batch'] for t in taps} | {y['batch'] for y in yields})
    rows, fresh = rules.reconcile(batches, mixtures, conflicts, taps, yields)
    if fresh:
        _, _, yield_conflicts = upsert_yields(fresh)
        if yield_conflicts: save_tap_quarantine(yield_conflicts)
        yields = all_yields()
    compensation = rules.compensate(yields, plan_mass(yields, taps, mixtures))
    by_batch = {}
    for r in rows: by_batch.setdefault(r['炉次'], set()).add(r['状态'])
    confirmed = sum(1 for states in by_batch.values() if states == {'已核'})
    pending = sum(1 for states in by_batch.values() if '待核' in states)
    quarantine = [{'行号': q['line_no'], 'lot': (q['batch'] or '—') + '/' + (q['element'] or '—'),
                   '原因码': q['code'], '原因': q['detail']} for q in all_tap_quarantine()]
    metrics = [['已核炉次', confirmed, '炉'], ['待核炉次', pending, '炉'], ['本次结算', len(fresh), '项'],
               ['Cu依据收得率', next(c['依据收得率_pct'] for c in compensation if c['元素'] == 'Cu'), '%'],
               ['Zn依据收得率', next(c['依据收得率_pct'] for c in compensation if c['元素'] == 'Zn'), '%'],
               ['出炉隔离', len(quarantine), '条']]
    return {'stage': 8, 'name': '烧损补偿', 'rows': rows, 'compensation': compensation,
            'quarantine': quarantine, 'metrics': metrics}
