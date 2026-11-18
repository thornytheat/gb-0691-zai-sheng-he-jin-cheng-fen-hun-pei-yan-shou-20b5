# 深度登记 再生合金成分混配与验收

- 规模：中型
- 使用者与工作流：再生金属配料员，合并废料检验批，按配方称重混配并复核各元素上下限。
- 核心规则：元素质量按物料净重×含量汇总；干湿基转换，低于检出限给上下界，不可把未检出当零，配方版本锁定。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 来料接收 | 运行来料接收并复核证据 | `POST /api/m1`；`/work/1` | `app/modules/m1_receiving/rules.py` | `tests/test_m1.py` |
| M2 成分归一 | 运行成分归一并复核证据 | `POST /api/m2`；`/work/2` | `app/modules/m2_assay/rules.py` | `tests/test_m2.py` |
| M3 配方约束 | 运行配方约束并复核证据 | `POST /api/m3`；`/work/3` | `app/modules/m3_recipe/rules.py` | `tests/test_m3.py` |
| M4 混配试算 | 运行混配试算并复核证据 | `POST /api/m4`；`/work/4` | `app/modules/m4_blend/rules.py` | `tests/test_m4.py` |
| M5 不确定区间 | 运行不确定区间并复核证据 | `POST /api/m5`；`/work/5` | `app/modules/m5_uncertainty/rules.py` | `tests/test_m5.py` |
| M6 验收对照 | 运行验收对照并复核证据 | `POST /api/m6`；`/work/6` | `app/modules/m6_acceptance/rules.py` | `tests/test_m6.py` |
| M7 复配批次 | 运行复配批次并复核证据 | `POST /api/m7`；`/work/7` | `app/modules/m7_reblend/rules.py` | `tests/test_m7.py` |
| M8 烧损补偿 | 提交出炉实测，查看炉次对照与下一炉补偿依据 | `POST /api/m8`、`POST /api/m8/tap`；`/work/8` | `app/modules/m8_yield/rules.py` | `tests/test_m8.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现会怎样 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-01 | 旧编码 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m1_receiving/rules.py` | `tests/test_m1.py::test_legacy_encoding` |
| TRAP-06 | 千分位与全角 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m2_assay/rules.py` | `tests/test_m2.py::test_thousands` |
| TRAP-07 | 空值不可当零 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m2_assay/rules.py` | `tests/test_m2.py::test_sentinel_isolation` |
| TRAP-10 | 干重精确守恒 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m4_blend/rules.py` | `tests/test_m4.py::test_decimal_dry_total` |
| TRAP-14 | 同键冲突 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m2_assay/rules.py` | `tests/test_m2.py::test_conflict_preserved` |
| TRAP-15 | 吨与千克 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m2_assay/rules.py` | `tests/test_m2.py::test_units` |
| TRAP-19 | 批号元数据冲突优先 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m3_recipe/rules.py` | `tests/test_m3.py::test_conflicting_lot_mass` |
| TRAP-25 | 配方版本锁定 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m3_recipe/rules.py` | `tests/test_m3.py::test_version_lock` |
| TRAP-26 | 出炉重跑重复计炉 | 重复提交把同一炉算两次 | 同键同值幂等跳过，异值隔离保留原记录 | `app/store.py` | `tests/test_m8.py::test_rerun_never_double_counts` |
| TRAP-27 | 估算冒充验收 | 出炉未到按经验值直接验收 | 实测未到或计量不全保留待核，默认经验值仅作补偿依据并显式标注 | `app/modules/m8_yield/rules.py` | `tests/test_m8.py::test_estimate_never_counts_as_acceptance` |
| TRAP-28 | 异常炉次带偏配方 | 照搬上一炉收得率 | 最近5次已核炉次中位数，偏离超5个百分点剔除并列名 | `app/modules/m8_yield/rules.py` | `tests/test_m8.py::test_outlier_furnace_excluded` |
| TRAP-29 | 中断后无法续跑 | 部分提交后重跑全量重复计数 | 出炉记录持久化，重跑只补缺失记录 | `app/modules/m8_yield/service.py` | `tests/test_m8.py::test_resume_after_interrupted_submit` |

## 对账规则

输入记录 = 采信记录 + 隔离记录 + 相同行重复。重复表头与空行单独记数。业务合计按阶段中的守恒或差值列复核。运行清单有原文SHA256、规则版本与耗时；相同规则版本下同文重复提交复用批次。

## 已知不覆盖

部署为本地单用户工具，不连接外部上游系统。CSV单文件5MB及一万条业务记录上限；不推断未提供的未知数据。
