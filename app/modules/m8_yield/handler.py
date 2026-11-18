import csv, io
from flask import Blueprint, Response, jsonify, request
from app.errors import DomainError
from app.pipeline import calculate
from app.store import get_run, latest, save
from app.modules.m8_yield import service
bp = Blueprint('m8', __name__)

def current_run():
    ident = request.args.get('run_id')
    if ident: return get_run(ident)
    payload = request.get_json(silent=True) or {}
    if payload.get('csv'): return calculate(payload['csv'])
    return latest() or save(calculate())

@bp.route('/api/m8', methods=['POST'])
def module_8():
    return jsonify(service.compute(current_run()))

@bp.route('/api/m8/tap', methods=['POST'])
def tap():
    payload = request.get_json(silent=True) or {}
    return jsonify(service.submit_tap(payload.get('csv')))

@bp.route('/api/m8/evidence.csv')
def evidence():
    run = current_run()
    view = service.compute(run)
    rows = [{'阶段': '对照', **r} for r in view['rows']]
    rows += [{'阶段': '补偿', **r} for r in view['compensation']]
    rows += [{'阶段': '隔离', **r} for r in view['quarantine']]
    out = io.StringIO(newline='')
    fields = list(dict.fromkeys(['阶段', 'run_id', '规则版本'] + [k for r in rows for k in r]))
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({'run_id': run['manifest']['run_id'], '规则版本': run['manifest']['rule_version'], **row})
    return Response('\ufeff' + out.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=yield-evidence.csv'})
