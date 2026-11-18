from decimal import Decimal
from app.domain import TARGETS
from app.numeric import number, fmt
from app.config import DEFAULT_YIELD, YIELD_WINDOW, YIELD_MIN_SAMPLES, YIELD_OUTLIER_PP

ELEMENTS = ('Cu', 'Zn')

def median(values):
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2: return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2

def yield_of(input_kg, tapped_kg):
    return tapped_kg / input_kg * 100

def reconcile(batches, mixtures, conflicts, taps, yields):
    """每炉每元素对照：已核（有收得率）或待核（说明原因）。返回(对照行, 新结算收得率)。"""
    rows = []
    fresh = []
    tap_by = {}
    for t in taps: tap_by.setdefault(t['batch'], {})[t['element']] = t
    known = {(y['batch'], y['element']): y for y in yields}
    for batch in batches:
        tapped = tap_by.get(batch, {})
        for element in ELEMENTS:
            key = (batch, element)
            info = mixtures.get(key)
            tap = tapped.get(element)
            base = {'炉次': batch, '元素': element, '状态': '待核', '说明': '', '投入基准_kg': '—', '投入下界_kg': '—',
                    '投入上界_kg': '—', '出炉_kg': '—', '实测含量_pct': '—', '实测元素_kg': '—', '收得率_pct': '—', '依据批次': '—'}
            if key in known:
                y = known[key]
                if info is not None:
                    low, high = number(info['元素下界_kg']), number(info['元素上界_kg'])
                    base.update({'投入下界_kg': str(low), '投入上界_kg': str(high), '投入基准_kg': str((low + high) / 2)})
                else:
                    base['投入基准_kg'] = y['input_kg']
                rows.append({**base, '状态': '已核', '说明': '收得率已结算',
                             '实测元素_kg': y['tapped_kg'], '收得率_pct': y['yield_pct'], '依据批次': y['run_id'][:8],
                             '出炉_kg': tap['tap_mass_kg'] if tap else '—', '实测含量_pct': tap['tap_assay_pct'] if tap else '—'})
                continue
            if batch in conflicts:
                rows.append({**base, '说明': '投入冲突：不同批次文件对该炉投入不一致'})
                continue
            if info is None:
                rows.append({**base, '说明': '投入不明：该炉无对应来料混配记录'})
                continue
            low, high, dry = (number(info['元素下界_kg']), number(info['元素上界_kg']), number(info['干重_kg']))
            base.update({'投入下界_kg': str(low), '投入上界_kg': str(high), '投入基准_kg': str((low + high) / 2)})
            if tap is None:
                if tapped:
                    rows.append({**base, '说明': '计量不全：缺' + element + '出炉实测'})
                else:
                    rows.append({**base, '说明': '出炉未到：该炉无出炉实测记录'})
                continue
            base.update({'出炉_kg': tap['tap_mass_kg'], '实测含量_pct': tap['tap_assay_pct']})
            if len(tapped) < len(ELEMENTS):
                missing = '、'.join(e for e in ELEMENTS if e not in tapped)
                rows.append({**base, '说明': '计量不全：缺' + missing + '出炉实测'})
                continue
            input_kg = (low + high) / 2
            tapped_kg = number(tap['tap_mass_kg']) * number(tap['tap_assay_pct']) / 100
            pct = yield_of(input_kg, tapped_kg)
            fresh.append({'batch': batch, 'element': element, 'yield_pct': fmt(pct), 'input_kg': str(input_kg),
                          'tapped_kg': fmt(tapped_kg), 'run_id': info['run_id']})
            rows.append({**base, '状态': '已核', '说明': '收得率已结算', '实测元素_kg': fmt(tapped_kg),
                         '收得率_pct': fmt(pct), '依据批次': info['run_id'][:8]})
    return rows, fresh

def basis_for(element, yields, window=YIELD_WINDOW, min_samples=YIELD_MIN_SAMPLES, outlier_pp=YIELD_OUTLIER_PP):
    """依据收得率：最近window次已核炉次中位数并剔除异常炉；样本不足回退默认经验值。"""
    points = [(y['batch'], number(y['yield_pct'])) for y in yields if y['element'] == element]
    points = points[-window:]
    limit = number(outlier_pp)
    if len(points) < min_samples:
        return {'yield_pct': str(number(DEFAULT_YIELD[element])), '来源': '默认经验值',
                '说明': '默认经验值（已核炉次不足%d炉，当前%d炉）' % (min_samples, len(points)), '样本': len(points), '剔除': []}
    med = median([p[1] for p in points])
    kept = [p for p in points if abs(p[1] - med) <= limit]
    dropped = [b for b, v in points if abs(v - med) > limit]
    value = median([p[1] for p in kept])
    note = '最近%d次已核炉次中位数（样本%d炉' % (len(points), len(kept))
    note += '，剔除异常炉次：' + '、'.join(dropped) + '）' if dropped else '，无异常）'
    return {'yield_pct': fmt(value), '来源': '实测中位数', '说明': note, '样本': len(kept), '剔除': dropped}

def compensate(yields, plan_kg, window=YIELD_WINDOW, min_samples=YIELD_MIN_SAMPLES, outlier_pp=YIELD_OUTLIER_PP):
    """下一炉元素补偿：需投元素=计划出炉×目标含量÷收得率；补偿量=需投−目标。"""
    rows = []
    for element in ELEMENTS:
        basis = basis_for(element, yields, window, min_samples, outlier_pp)
        y = number(basis['yield_pct'])
        target = (TARGETS[element][0] + TARGETS[element][1]) / 2
        factor = 100 / y
        row = {'元素': element, '依据收得率_pct': basis['yield_pct'], '补偿系数': fmt(factor),
               '计划出炉_kg': str(plan_kg) if plan_kg is not None else '—', '目标含量_pct': str(target),
               '目标元素_kg': '—', '需投元素_kg': '—', '补偿量_kg': '—', '依据来源': basis['来源'], '依据说明': basis['说明']}
        if plan_kg is not None:
            goal = number(plan_kg) * target / 100
            need = goal * factor
            row.update({'目标元素_kg': fmt(goal), '需投元素_kg': fmt(need), '补偿量_kg': fmt(need - goal)})
        rows.append(row)
    return rows
