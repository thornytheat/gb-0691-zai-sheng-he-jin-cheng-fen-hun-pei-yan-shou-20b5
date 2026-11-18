import pytest
from decimal import Decimal
from app.modules.m8_yield import rules

FEED_HEAD = 'lot,batch,mass,unit,moisture,element,assay,basis,revision'
TAP_HEAD = 'batch,element,tap_mass,unit,tap_assay'

def feed(batch, cu='10', zn='5'):
    return FEED_HEAD + '\nL1,%s,100,kg,0,Cu,%s,dry,1\nL1,%s,100,kg,0,Zn,%s,dry,1' % (batch, cu, batch, zn)

def tap(batch, mass='100', cu='9.8', zn='4.7'):
    return TAP_HEAD + '\n%s,Cu,%s,kg,%s\n%s,Zn,%s,kg,%s' % (batch, mass, cu, batch, mass, zn)

def run_feed(client, batch, **kw):
    return client.post('/api/run', json={'csv': feed(batch, **kw)}).get_json()

def tap_batch(client, batch, **kw):
    return client.post('/api/m8/tap', json={'csv': tap(batch, **kw)})

def m8(client, **kw):
    return client.post('/api/m8', json=kw).get_json()

def row(view, batch, element):
    return next(r for r in view['rows'] if r['炉次'] == batch and r['元素'] == element)

def comp(view, element):
    return next(c for c in view['compensation'] if c['元素'] == element)

def test_median_odd_even():
    assert rules.median([Decimal('96'), Decimal('100'), Decimal('98')]) == Decimal('98')
    assert rules.median([Decimal('96'), Decimal('98')]) == Decimal('97')

def test_tap_recorded_and_yield_settled(client):
    run = client.post('/api/run', json={}).get_json()
    assert tap_batch(client, 'F-1108', mass='2800', cu='9.58', zn='4.56').get_json()['recorded'] == 2
    view = m8(client)
    cu = row(view, 'F-1108', 'Cu')
    assert cu['状态'] == '已核' and cu['依据批次'] == run['manifest']['run_id'][:8]
    mixture = next(r for r in run['mixture'] if r['元素'] == 'Cu')
    basis = (Decimal(mixture['元素下界_kg']) + Decimal(mixture['元素上界_kg'])) / 2
    from app.numeric import fmt
    assert cu['收得率_pct'] == fmt(Decimal('2800') * Decimal('9.58') / 100 / basis * 100)
    assert row(view, 'F-1108', 'Zn')['状态'] == '已核'

def test_rerun_never_double_counts(client):
    client.post('/api/run', json={})
    text = tap('F-1108', mass='2800', cu='9.58', zn='4.56')
    assert client.post('/api/m8/tap', json={'csv': text}).get_json()['recorded'] == 2
    again = client.post('/api/m8/tap', json={'csv': text}).get_json()
    assert again['recorded'] == 0 and again['duplicated'] == 2
    first, second = m8(client), m8(client)
    assert first['rows'] == second['rows']
    assert sum(r['状态'] == '已核' for r in first['rows']) == 2

def test_resume_after_interrupted_submit(client):
    client.post('/api/run', json={})
    full = tap('F-1108', mass='2800', cu='9.58', zn='4.56')
    head_only = '\n'.join(full.split('\n')[:2])
    assert client.post('/api/m8/tap', json={'csv': head_only}).get_json()['recorded'] == 1
    resume = client.post('/api/m8/tap', json={'csv': full}).get_json()
    assert resume['recorded'] == 1 and resume['duplicated'] == 1
    assert row(m8(client), 'F-1108', 'Zn')['状态'] == '已核'

def test_pending_when_tap_missing(client):
    client.post('/api/run', json={})
    cu = row(m8(client), 'F-1108', 'Cu')
    assert cu['状态'] == '待核' and '出炉未到' in cu['说明']

def test_pending_when_assay_incomplete(client):
    client.post('/api/run', json={})
    client.post('/api/m8/tap', json={'csv': TAP_HEAD + '\nF-1108,Cu,2800,kg,9.58'})
    view = m8(client)
    cu, zn = row(view, 'F-1108', 'Cu'), row(view, 'F-1108', 'Zn')
    assert cu['状态'] == zn['状态'] == '待核' and '计量不全' in cu['说明'] and '计量不全' in zn['说明']
    assert all(c['依据来源'] == '默认经验值' for c in view['compensation'])

def test_estimate_never_counts_as_acceptance(client):
    client.post('/api/run', json={})
    view = m8(client)
    assert all(r['状态'] == '待核' for r in view['rows'])
    assert all(c['依据来源'] == '默认经验值' for c in view['compensation'])
    assert '默认经验值' in comp(view, 'Cu')['依据说明']

def test_pending_when_input_unknown(client):
    client.post('/api/run', json={})
    tap_batch(client, 'F-9999')
    assert '投入不明' in row(m8(client), 'F-9999', 'Cu')['说明']

def test_median_basis_from_recent_furnaces(client):
    for batch, cu in [('F-01', '9.6'), ('F-02', '9.8'), ('F-03', '10')]:
        run_feed(client, batch)
        tap_batch(client, batch, cu=cu, zn='4.7')
    view = m8(client)
    cu = comp(view, 'Cu')
    assert cu['依据来源'] == '实测中位数' and cu['依据收得率_pct'] == '98.0000'
    assert '最近3次已核炉次中位数' in cu['依据说明']

def test_outlier_furnace_excluded(client):
    for batch, cu in [('F-01', '9.8'), ('F-02', '9.8'), ('F-03', '9.8'), ('F-04', '8')]:
        run_feed(client, batch)
        tap_batch(client, batch, cu=cu)
    view = m8(client)
    cu = comp(view, 'Cu')
    assert cu['依据收得率_pct'] == '98.0000' and '剔除异常炉次：F-04' in cu['依据说明']
    assert row(view, 'F-04', 'Cu')['状态'] == '已核'

def test_compensation_values(client):
    for batch in ('F-01', 'F-02', 'F-03'):
        run_feed(client, batch)
        tap_batch(client, batch, cu='9.8', zn='4.7')
    view = m8(client)
    cu, zn = comp(view, 'Cu'), comp(view, 'Zn')
    assert cu['计划出炉_kg'] == '100' and cu['目标含量_pct'] == '10.0'
    assert cu['补偿系数'] == '1.0204' and cu['需投元素_kg'] == '10.2041' and cu['补偿量_kg'] == '0.2041'
    assert zn['依据收得率_pct'] == '94.0000' and zn['补偿量_kg'] == '0.3191'

def test_default_yield_when_samples_insufficient(client):
    run_feed(client, 'F-01')
    tap_batch(client, 'F-01')
    view = m8(client)
    assert comp(view, 'Cu')['依据收得率_pct'] == '98' and comp(view, 'Cu')['依据来源'] == '默认经验值'
    assert comp(view, 'Zn')['依据收得率_pct'] == '94'

def test_conflict_keeps_original_record(client):
    client.post('/api/run', json={})
    tap_batch(client, 'F-1108', mass='2800', cu='9.58', zn='4.56')
    bad = client.post('/api/m8/tap', json={'csv': tap('F-1108', mass='2800', cu='9.99', zn='4.56')}).get_json()
    assert bad['recorded'] == 0 and any(i['原因码'] == 'CONFLICT' for i in bad['isolated'])
    assert row(m8(client), 'F-1108', 'Cu')['实测含量_pct'] == '9.58'

def test_invalid_tap_rows_isolated_and_deduped(client):
    client.post('/api/run', json={})
    text = TAP_HEAD + '\nF-1108,Cu,2800,kg,<0.1\nF-1108,Fe,2800,kg,9\nF-1108,Zn,2800,kg'
    for _ in range(2):
        bad = client.post('/api/m8/tap', json={'csv': text}).get_json()
        assert {i['原因码'] for i in bad['isolated']} == {'ASSAY', 'ELEMENT', 'COLUMNS'}
    view = m8(client)
    assert len(view['quarantine']) == 3

def test_page_shows_basis_and_compensation(client):
    client.post('/api/run', json={})
    tap_batch(client, 'F-1108', mass='2800', cu='9.58', zn='4.56')
    page = client.get('/work/8').data.decode()
    assert '烧损补偿' in page and '依据说明' in page and '默认经验值' in page and '补偿量_kg' in page

def test_export_contains_basis_and_compensation(client):
    run = client.post('/api/run', json={}).get_json()
    tap_batch(client, 'F-1108', mass='2800', cu='9.58', zn='4.56')
    text = client.get('/api/m8/evidence.csv?run_id=' + run['manifest']['run_id']).data.decode('utf-8-sig')
    assert '依据说明' in text and '补偿' in text and '对照' in text and run['manifest']['run_id'] in text

def test_module_endpoint_and_page_bounds(client):
    assert client.post('/api/m8', json={}).status_code == 200
    assert client.get('/work/8').status_code == 200
    assert client.get('/work/9').status_code == 404

def test_empty_tap_rejected(client):
    assert client.post('/api/m8/tap', json={'csv': ''}).status_code == 422
    assert client.post('/api/m8/tap', json={}).status_code == 422
