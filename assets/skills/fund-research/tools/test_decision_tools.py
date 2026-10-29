#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
test_decision_tools.py — 时点纪律与决策闭环工具的离线自检

覆盖三个新增能力面：
  1. **时点纪律（pit.py）** —— 披露日期推算、可见性判定、序列截断；
  2. **结论标签（rating.py）** —— 词表唯一性、锚定解析、REVIEW 哨兵；
  3. **决策闭环（decision_log.py / settle.py / decision_score.py）** ——
     日志只增追加与幂等、结算口径（入出场、alpha、PENDING/FAILED）、
     按标签聚合的命中率（方向性标签才计）。

全部离线：fixture 内联，不发一次网络请求；临时文件写在工作区内。

与直觉不一致处按实现断言（边界已固定，改实现须同步改这里）：
  1. 披露日期用**监管最晚披露时限**（季报 25 日 / 半年报 60 日 / 年报 90 日），
     是保守上界——宁可认为数据更晚可见，也不误判为基准日已可见。
  2. `_percentile` 口径是「严格小于当前值的样本占比」，故 [1..5] 当前=5 → 80.0。
  3. 结算的**入场取决策日之后第一个收盘日**：决策日当天收盘后才发布的信息不计入。
  4. `等待验证` / `数据不足` / `REVIEW` **不宣称方向**，不计命中率。

用法: python test_decision_tools.py
退出码: 0 = 全部通过；1 = 有失败
"""
import io
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# 时点底座在 stock-research/tools 下
sys.path.insert(0, os.path.join(HERE, '..', '..', 'stock-research', 'tools'))

try:
    import pit
    import rating
    import decision_log
    import settle
    import decision_score
except Exception as e:  # noqa: BLE001
    print('[FAIL] cannot import modules:', e)
    sys.exit(1)

TOTAL = 0
FAILS = []


def check(name, ok, got=None):
    global TOTAL
    TOTAL += 1
    print('%s %s' % ('PASS' if ok else 'FAIL', name))
    if not ok:
        FAILS.append('%s -> got %r' % (name, got))


def eq(name, got, want):
    check(name, got == want, got)


def _resolve_work_dir():
    """挑一个**插件包之外**的可写目录放夹具，避免污染发布包。

    顺序：`FR_TEST_TMPDIR` → 系统临时目录 → 插件根的上一级 → 脚本所在目录。
    任何候选都要**实际试写一次**才算数：DSH 沙箱会拦截平台临时目录的写入
    （创建目录即 `PermissionError`），不试写就会拿到一个不可用的目录。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    # 插件包根 = 含 package.json(name=dsh-invest-research) 且有 assets/ 的那一级
    pkg_root, probe = None, here
    for _ in range(6):
        try:
            pj = os.path.join(probe, 'package.json')
            if os.path.isdir(os.path.join(probe, 'assets')) and os.path.isfile(pj):
                import json as _json
                with io.open(pj, encoding='utf-8') as fh:
                    if _json.load(fh).get('name') == 'dsh-invest-research':
                        pkg_root = probe
                        break
        except Exception:
            pass
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent

    candidates = []
    if os.environ.get('FR_TEST_TMPDIR'):
        candidates.append(os.environ['FR_TEST_TMPDIR'])
    try:
        import tempfile
        candidates.append(tempfile.gettempdir())
    except Exception:
        pass
    if pkg_root:
        candidates.append(os.path.dirname(pkg_root))   # 插件包外侧，仍可清理
    candidates.append(here)                            # 最后兜底：至少能跑

    for base in candidates:
        target = os.path.join(os.path.abspath(base), '.tmp-decision-test')
        try:
            os.makedirs(target, exist_ok=True)
            probe_file = os.path.join(target, '.write-probe')
            with io.open(probe_file, 'w', encoding='utf-8') as fh:
                fh.write('ok')
            os.remove(probe_file)
            return target
        except Exception:
            continue
    raise SystemExit('[FAIL] 找不到可写目录放测试夹具（试过：%s）' % candidates)


WORK = _resolve_work_dir()


# ---------- 1. 时点纪律：披露日期推算 ----------
eq('disclosure_date 季报 +25 日',
   pit.disclosure_date('2026-03-31', '季报'), '2026-04-25')
eq('disclosure_date 半年报 +60 日',
   pit.disclosure_date('2026-06-30', '半年报'), '2026-08-29')
eq('disclosure_date 年报 +90 日',
   pit.disclosure_date('2025-12-31', '年报'), '2026-03-31')
eq('disclosure_date 报告期解析不了 -> 未取得',
   pit.disclosure_date('不是日期', '季报'), '未取得')
eq('disclosure_date 缺披露类型走默认 25 日',
   pit.disclosure_date('2026-03-31'), '2026-04-25')

# ---------- 2. 时点纪律：可见性判定 ----------
a630 = pit.AsOf('2026-06-30')
eq('visible 一季报（4 月已披露）在 6-30 可见',
   a630.visible('2026-03-31', '季报'), True)
eq('visible 半年报（8 月才披露）在 6-30 不可见',
   a630.visible('2026-06-30', '半年报'), False)
eq('visible 报告期晚于基准日 -> 不可见',
   a630.visible('2026-09-30', '季报'), False)
eq('visible 报告期解析不了 -> 保守判不可见',
   a630.visible(None, '季报'), False)
eq('visible 未设基准日 -> 一律可见（不改变旧行为）',
   pit.AsOf(None).visible('2026-09-30', '季报'), True)
eq('visible 自定义滞后天数生效（滞后 0 天 -> 当日即披露）',
   a630.visible('2026-06-30', '季报', lag_days=0), True)
eq('visible 自定义滞后天数生效（滞后 1 天 -> 次日才披露，仍不可见）',
   a630.visible('2026-06-30', '季报', lag_days=1), False)

# ---------- 3. 时点纪律：序列截断 ----------
eq('truncate dict 行按基准日截断',
   a630.truncate([{'日期': '2026-06-29'}, {'日期': '2026-07-01'}])[0],
   [{'日期': '2026-06-29'}])
eq('truncate dict 行剔除计数',
   a630.truncate([{'日期': '2026-06-29'}, {'日期': '2026-07-01'}])[1], 1)
eq('truncate 元组行（date_key=0）按基准日截断',
   a630.truncate([('2026-06-29', 1.0), ('2026-07-01', 1.1)], date_key=0)[0],
   [('2026-06-29', 1.0)])
eq('truncate 未设基准日 -> 不截断',
   pit.AsOf(None).truncate([('2026-07-01', 1.1)], date_key=0)[1], 0)

# ---------- 4. 结论标签：词表与解析 ----------
eq('rating.LABELS 是 5 档且顺序固定',
   rating.LABELS,
   ('优先研究', '可以关注', '等待验证', '暂不优先', '数据不足'))
eq('rating.REVIEW 哨兵',
   rating.REVIEW, 'REVIEW')
eq('方向性标签只有 3 个',
   rating.DIRECTIONAL_LABELS, ('优先研究', '可以关注', '暂不优先'))
check('等待验证/数据不足 不宣称方向',
      not rating.is_directional('等待验证') and not rating.is_directional('数据不足'))
check('REVIEW 不宣称方向', not rating.is_directional(rating.REVIEW))

eq('parse 加粗标签',
   rating.parse_label('**结论标签：等待验证**'), '等待验证')
eq('parse 半角冒号',
   rating.parse_label('结论标签: 可以关注'), '可以关注')
eq('parse 全角冒号（NFKC 归一化）',
   rating.parse_label('结论标签：优先研究'), '优先研究')
eq('parse 破折号分隔',
   rating.parse_label('- 结论标签 — 数据不足'), '数据不足')
eq('parse 无标签 -> REVIEW 哨兵（不得退化成中性标签）',
   rating.parse_label('正文提到可以关注，但不是结论'), rating.REVIEW)
eq('parse 空文本 -> REVIEW',
   rating.parse_label(''), rating.REVIEW)
eq('parse 非法标签值 -> REVIEW',
   rating.parse_label('**结论标签：胡说八道**'), rating.REVIEW)
eq('parse 标签尺度说明行不算结论',
   rating.parse_label('结论标签尺度：优先研究、可以关注、等待验证'), rating.REVIEW)
eq('parse_label_from_record 优先读 label 字段',
   rating.parse_label_from_record({'label': '暂不优先'}), '暂不优先')
eq('parse_label_from_record 缺 label 且无正文 -> REVIEW',
   rating.parse_label_from_record({'run_id': 'x'}), rating.REVIEW)

# ---------- 5. 决策日志：只增追加 / 幂等 / 校验 ----------
LEDGER = os.path.join(WORK, 'ledger.jsonl')
if os.path.exists(LEDGER):
    os.remove(LEDGER)

rec_ok = {'run_id': 'r1', 'code': '011839', 'as_of': '2026-06-30', 'label': '优先研究',
          'vocabulary_version': 'v1'}
rec_bad = {'run_id': 'r2', 'code': '011839'}

eq('append 正常记录', decision_log.append_record(LEDGER, rec_ok), (True, 'appended'))
eq('append 同 run_id 幂等（不重复写）',
   decision_log.append_record(LEDGER, dict(rec_ok)), (False, 'duplicate:run_id=r1'))
check('append 缺字段被拒',
      decision_log.append_record(LEDGER, rec_bad)[0] is False
      and 'invalid' in decision_log.append_record(LEDGER, rec_bad)[1])
eq('append 写了两条后日志有两行',
   len(decision_log.load_ledger(LEDGER)[0]), 1)

# 幂等：再追加一条不同 run_id
decision_log.append_record(LEDGER, {'run_id': 'r3', 'code': '012733',
                                    'as_of': '2026-06-30', 'label': '等待验证'})
eq('日志累计两条', len(decision_log.load_ledger(LEDGER)[0]), 2)
eq('verify 无问题', decision_log.verify(*decision_log.load_ledger(LEDGER)), [])

# 损坏行不阻断读取，但要被报告
with io.open(LEDGER, 'a', encoding='utf-8') as fh:
    fh.write('not json at all\n')
loaded, broken = decision_log.load_ledger(LEDGER)
eq('损坏行被跳过但不丢历史', len(loaded), 2)
eq('损坏行计数', broken, 1)
check('verify 报告损坏行',
      any('损坏' in p or '无法解析' in p for p in decision_log.verify(loaded, broken)))

# ---------- 6. 结算：入出场 / alpha / PENDING / FAILED ----------
nav, bench = [], []
for i in range(30):
    d = '2026-%02d-%02d' % (1 + i // 28, 1 + i % 28)
    nav.append([d, round(1.0 * (1.01 ** i), 6)])
    bench.append([d, round(1.0 * (1.002 ** i), 6)])

norm = settle.normalize_series({'序列': nav})
eq('normalize_series 取日期升序', norm[0][0].strftime('%Y-%m-%d'), '2026-01-01')

rec_settled = settle.settle_one(
    {'code': '011839', 'as_of': '2026-01-05', 'label': '优先研究'},
    norm, settle.normalize_series({'序列': bench}), 20)
eq('结算状态 = SETTLED', rec_settled['状态'], 'SETTLED')
check('入场在决策日之后', rec_settled['入场日'] > '2026-01-05')
eq('出场 = 入场后第 20 个交易日', rec_settled['出场日'], '2026-01-26')
check('原始收益为正', rec_settled['原始收益'] > 0)
check('超额 = 原始 - 基准',
      abs(rec_settled['超额收益']
          - (rec_settled['原始收益'] - rec_settled['基准收益'])) < 1e-9)

rec_pending = settle.settle_one(
    {'code': '011839', 'as_of': '2026-01-27', 'label': '等待验证'},
    norm, settle.normalize_series({'序列': bench}), 20)
eq('窗口未走完 -> PENDING', rec_pending['状态'], 'PENDING')
eq('PENDING 不给超额', rec_pending['超额收益'], None)

rec_failed = settle.settle_one(
    {'code': '022222', 'as_of': '2026-01-05', 'label': '可以关注'},
    [], settle.normalize_series({'序列': bench}), 20)
eq('无序列 -> SETTLE_FAILED', rec_failed['状态'], 'SETTLE_FAILED')

rec_nobench = settle.settle_one(
    {'code': '011839', 'as_of': '2026-01-05', 'label': '优先研究'},
    norm, [], 20)
eq('无基准仍可结算原始收益', rec_nobench['状态'], 'SETTLED')
eq('无基准则不给超额', rec_nobench['超额收益'], None)

# ---------- 7. 决策质量统计：命中率只对方向性标签 ----------
decisions = [
    {'run_id': 'a', 'code': 'A', 'as_of': '2026-01-05', 'label': '优先研究',
     'vocabulary_version': 'v1'},
    {'run_id': 'b', 'code': 'A', 'as_of': '2026-02-05', 'label': '可以关注',
     'vocabulary_version': 'v1'},
    {'run_id': 'c', 'code': 'B', 'as_of': '2026-01-05', 'label': '暂不优先',
     'vocabulary_version': 'v1'},
    {'run_id': 'd', 'code': 'B', 'as_of': '2026-03-05', 'label': '等待验证',
     'vocabulary_version': 'v1'},
    {'run_id': 'e', 'code': 'C', 'as_of': '2026-01-05', 'label': 'REVIEW',
     'vocabulary_version': 'v2'},
]
settlements = [
    {'code': 'A', 'as_of': '2026-01-05', '状态': 'SETTLED', '超额收益': '5.0%'},
    {'code': 'A', 'as_of': '2026-02-05', '状态': 'SETTLED', '超额收益': '-2.0%'},
    {'code': 'B', 'as_of': '2026-01-05', '状态': 'PENDING'},
]
cells = decision_score.build_cells(decisions, settlements)
summary = decision_score.summarize(cells)

eq('已结算单元数', summary['resolved'], 2)
eq('未到期单元数', summary['pending'], 3)
eq('结算失败单元数', summary['failed'], 0)
eq('方向性标签有命中率',
   summary['by_label']['优先研究']['hit_rate'], 1.0)
eq('方向性标签平均超额',
   round(summary['by_label']['优先研究']['mean_alpha'], 4), 0.05)
check('不宣称方向的标签不计命中率',
      summary['by_label']['等待验证']['hit_rate'] is None
      and not summary['by_label']['等待验证']['directional'])
check('已结算样本为 0 的标签仍列出样本数',
      '等待验证' in summary['by_label']
      and summary['by_label']['等待验证']['count'] == 0)
eq('REVIEW 单元计入未解析', summary['unscored'], 1)
eq('按词表版本分组不跨版本合并',
   summary['by_vocab'], {'v1': 2})

# 渲染：必须含前视偏差说明、未结算清单、不宣称方向的说明
md = decision_score.render_md(summary)
check('输出含前视偏差说明', '前视偏差说明' in md)
check('输出列出未到期单元', '未到期单元' in md)
check('输出说明不宣称方向', '不宣称方向' in md or '不计命中率' in md)
check('输出声明不构成投资建议', '不构成投资建议' in md)

# ---------- 汇总 ----------
print('\n%d/%d passed' % (TOTAL - len(FAILS), TOTAL))
if FAILS:
    # 失败时保留夹具，方便排查；通过则清理掉，避免在工作区留垃圾。
    print('FAILURES:')
    for f in FAILS:
        print('  - %s' % f)
    print('（夹具保留以便排查：%s）' % WORK)
    sys.exit(1)
try:
    shutil.rmtree(WORK, ignore_errors=True)
except Exception:
    pass
sys.exit(0)