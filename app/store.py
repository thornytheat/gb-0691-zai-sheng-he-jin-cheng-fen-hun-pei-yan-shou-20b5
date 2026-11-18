import sqlite3, json, os, time
from decimal import Decimal
from pathlib import Path
from app.errors import DomainError
def now(): return time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
def connection():
    path=Path(os.environ.get('APP_DB','data/runs.sqlite3'));path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path);db.row_factory=sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, payload TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, decision TEXT NOT NULL DEFAULT "待复核")')
    db.execute('CREATE TABLE IF NOT EXISTS taps(batch TEXT NOT NULL, element TEXT NOT NULL, tap_mass_kg TEXT NOT NULL, tap_assay_pct TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(batch,element))')
    db.execute('CREATE TABLE IF NOT EXISTS tap_quarantine(id INTEGER PRIMARY KEY AUTOINCREMENT, line_no INTEGER, batch TEXT, element TEXT, raw TEXT, code TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(line_no,batch,element,code,raw))')
    db.execute('CREATE TABLE IF NOT EXISTS yields(batch TEXT NOT NULL, element TEXT NOT NULL, yield_pct TEXT NOT NULL, input_kg TEXT NOT NULL, tapped_kg TEXT NOT NULL, run_id TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(batch,element))')
    return db
def save(result):
    with connection() as db:
        ident=result['manifest']['run_id'];row=db.execute('SELECT payload,revision,decision FROM runs WHERE id=?',(ident,)).fetchone()
        if row: return {**json.loads(row['payload']), 'revision':row['revision'], 'decision':row['decision'], 'reused':True}
        db.execute('INSERT INTO runs(id,payload) VALUES (?,?)',(ident,json.dumps(result,ensure_ascii=False)))
    return {**result,'revision':1,'decision':'待复核','reused':False}
def get_run(ident):
    with connection() as db: row=db.execute('SELECT payload,revision,decision FROM runs WHERE id=?',(ident,)).fetchone()
    if row is None: raise DomainError('NOT_FOUND','批次不存在',404)
    return {**json.loads(row['payload']),'revision':row['revision'],'decision':row['decision']}
def latest():
    with connection() as db: row=db.execute('SELECT payload,revision,decision FROM runs ORDER BY rowid DESC LIMIT 1').fetchone()
    return {**json.loads(row['payload']),'revision':row['revision'],'decision':row['decision']} if row else None
def history():
    with connection() as db: return [dict(r) for r in db.execute('SELECT id,revision,decision FROM runs ORDER BY rowid DESC')]
def review(ident, revision, decision):
    if decision not in ('通过','退回'): raise DomainError('DECISION','复核动作无效')
    with connection() as db:
        changed=db.execute('UPDATE runs SET revision=revision+1,decision=? WHERE id=? AND revision=?',(decision,ident,revision)).rowcount
        if not changed: raise DomainError('VERSION','版本已变化，请重新载入',409)
    return {'revision':revision+1,'decision':decision}
def all_payloads():
    with connection() as db: return [dict(r) for r in db.execute('SELECT id,payload FROM runs ORDER BY rowid')]
def save_taps(records):
    inserted=0;duplicated=0;conflicts=[]
    with connection() as db:
        for r in records:
            row=db.execute('SELECT tap_mass_kg,tap_assay_pct FROM taps WHERE batch=? AND element=?',(r['batch'],r['element'])).fetchone()
            if row is None:
                db.execute('INSERT INTO taps(batch,element,tap_mass_kg,tap_assay_pct,created_at) VALUES (?,?,?,?,?)',(r['batch'],r['element'],r['tap_mass_kg'],r['tap_assay_pct'],now()));inserted+=1
            elif Decimal(row['tap_mass_kg'])==Decimal(r['tap_mass_kg']) and Decimal(row['tap_assay_pct'])==Decimal(r['tap_assay_pct']): duplicated+=1
            else: conflicts.append({**r,'原因码':'CONFLICT','原因':'与已入库出炉记录数值冲突，保留原记录'})
    return inserted,duplicated,conflicts
def all_taps():
    with connection() as db: return [dict(r) for r in db.execute('SELECT batch,element,tap_mass_kg,tap_assay_pct,created_at FROM taps ORDER BY batch,element')]
def save_tap_quarantine(rows):
    with connection() as db:
        for r in rows:
            db.execute('INSERT OR IGNORE INTO tap_quarantine(line_no,batch,element,raw,code,detail,created_at) VALUES (?,?,?,?,?,?,?)',(r.get('行号') or 0,r.get('batch') or '',r.get('element') or '',r.get('raw') or '',r['原因码'],r['原因'],now()))
def all_tap_quarantine():
    with connection() as db: return [dict(r) for r in db.execute('SELECT line_no,batch,element,raw,code,detail,created_at FROM tap_quarantine ORDER BY id')]
def upsert_yields(rows):
    inserted=0;skipped=0;conflicts=[]
    with connection() as db:
        for r in rows:
            row=db.execute('SELECT yield_pct,input_kg,tapped_kg FROM yields WHERE batch=? AND element=?',(r['batch'],r['element'])).fetchone()
            if row is None:
                db.execute('INSERT INTO yields(batch,element,yield_pct,input_kg,tapped_kg,run_id,created_at) VALUES (?,?,?,?,?,?,?)',(r['batch'],r['element'],r['yield_pct'],r['input_kg'],r['tapped_kg'],r['run_id'],now()));inserted+=1
            elif all(Decimal(row[k])==Decimal(r[k]) for k in ('yield_pct','input_kg','tapped_kg')): skipped+=1
            else: conflicts.append({**r,'原因码':'YIELD_CONFLICT','原因':'与已结算收得率冲突，保留原记录'})
    return inserted,skipped,conflicts
def all_yields():
    with connection() as db: return [dict(r) for r in db.execute('SELECT batch,element,yield_pct,input_kg,tapped_kg,run_id,created_at FROM yields ORDER BY batch,element')]
