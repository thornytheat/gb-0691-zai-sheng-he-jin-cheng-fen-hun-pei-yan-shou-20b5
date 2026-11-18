from pathlib import Path
RULE_VERSION = "2026.11.18.2"
TITLE = '再生合金成分混配与验收'
SHORT = 'alloy-blend'
MODULES = ['来料接收', '成分归一', '配方约束', '混配试算', '不确定区间', '验收对照', '复配批次', '烧损补偿']
HEADERS = ['lot', 'batch', 'mass', 'unit', 'moisture', 'element', 'assay', 'basis', 'revision']
SAMPLE = Path(__file__).resolve().parent.parent / "sample_data" / "operations.csv"
LIMIT = 10000
TAP_HEADERS = ['batch', 'element', 'tap_mass', 'unit', 'tap_assay']
TAP_SAMPLE = Path(__file__).resolve().parent.parent / "sample_data" / "tap.csv"
M8_RULE = "2026.11.18.1"
DEFAULT_YIELD = {'Cu': '98', 'Zn': '94'}
YIELD_WINDOW = 5
YIELD_MIN_SAMPLES = 3
YIELD_OUTLIER_PP = '5'
