#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
test_annualization.py — 年化频率 / 夏普口径契约（标准 §3.2）

不变量：
  1. 年频率 = 样本期实际交易日总数 ÷ 样本年数（实算），不得硬编 252 / 244；
     算不出来才回退 242，并把来源标成「回退默认」。
  2. 夏普 = mean(r_t − rf_t) / s(r_t − rf_t) × sqrt(年频率)，rf 按几何方式日化；
     不是「年化收益 − 无风险利率」的算术相减。
  3. 口径 note 必须同时写出数值与来源，否则读报告的人无法复核。

全部离线（纯函数 + 内联 fixture），用法:
    python test_annualization.py
退出码: 0 = 全部通过；1 = 有失败
"""
import math
import os
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import fetch_fund as ff
except Exception as e:  # pragma: no cover
    print('[FAIL] cannot import fetch_fund:', e)
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


def near(name, got, want, tol=1e-12):
    check(name, got is not None and abs(got - want) <= tol, got)


def series(days, step, start='2025-01-01'):
    """从 start 起，step 个日历日一个点，共 days 个点（值按日固定漂移）。"""
    base = datetime.strptime(start, '%Y-%m-%d')
    return [((base + timedelta(days=i * step)).strftime('%Y-%m-%d'), 1.0 + i * 0.001)
            for i in range(days)]


# ---------- 1. 实算 ----------
S242 = series(242, 365.0 / 241)   # 242 个日频点，覆盖 365 个日历日 ≈ 一年
f242, src242 = ff._annualization_factor(S242)
check('242 点覆盖一年 -> 年频率落在 241–243', 241.0 <= f242 <= 243.0, f242)
eq('242 点覆盖一年 -> 来源=实算', src242, '实算')
check('_annualization_note 写出数值与来源',
      ('年频率=' in ff._annualization_note(f242, src242)) and ('实算' in ff._annualization_note(f242, src242)),
      ff._annualization_note(f242, src242))

# 三年日频（730 点 / 1095 天）-> 约 243.5，不是 244
f3y, _ = ff._annualization_factor(series(730, 1095.0 / 729))
check('730 点 / 3 年 -> 年频率约 243.5（与硬编 244 不同）', 241.0 <= f3y <= 245.0 and f3y != 244.0, f3y)

# ---------- 2. 回退 ----------
fbad, sbad = ff._annualization_factor([('d%03d' % i, 1.0) for i in range(245)])
eq('伪日期不可解析 -> 年频率=242 / 回退默认', (fbad, sbad), (242.0, '回退默认'))
eq('单点 -> 回退默认', ff._annualization_factor([('2026-01-01', 1.0)]), (242.0, '回退默认'))
eq('空序列 -> 回退默认', ff._annualization_factor([]), (242.0, '回退默认'))
eq('同日重复 -> 年数 0 -> 回退默认',
   ff._annualization_factor([('2026-01-01', 1.0), ('2026-01-01', 1.1)]), (242.0, '回退默认'))
eq('None 值被跳过（只剩 1 个有效点）-> 回退默认',
   ff._annualization_factor([('2026-01-01', 1.0), ('2026-01-02', None)]), (242.0, '回退默认'))
eq('月频样本（12 点/3 年）不当年化频率 -> 回退默认',
   ff._annualization_factor([((datetime(2023, 1, 1) + timedelta(days=91 * i)).strftime('%Y-%m-%d'), 1.0 + i)
                             for i in range(12)]), (242.0, '回退默认'))

# ---------- 3. 年化收益 / 波动率都用同一个年频率 ----------
S2X = [('2025-01-01', 1.0)] + [((datetime(2025, 1, 1) + timedelta(days=i)).strftime('%Y-%m-%d'), 2.0)
                               for i in range(1, 245)]
near('_annualized(244 日翻倍, 年频率=244) -> 1.0', ff._annualized(S2X, 244, factor=244.0), 1.0)
near('_annualized 缺省年频率=242 -> 2**(242/244)-1',
     ff._annualized(S2X, 244), 2 ** (242.0 / 244) - 1, 1e-15)
near('_volatility 用传入年频率（factor=256 时放大 sqrt(256/242)）',
     (ff._volatility(S2X, 244, factor=256.0) or 0) / (ff._volatility(S2X, 244) or 1),
     math.sqrt(256.0 / 242.0), 1e-12)

# ---------- 4. 夏普：超额收益口径 ----------
base = datetime(2025, 1, 1)
vals = [1.0]
for i in range(1, 253):                       # 252 个日收益，确定性波动
    vals.append(vals[-1] * (1.0 + 0.004 * math.sin(i * 1.7) + 0.0003))
SHP = [((base + timedelta(days=i)).strftime('%Y-%m-%d'), v) for i, v in enumerate(vals)]
RF = 2.0
F = ff._annualization_factor(SHP)[0]

r = ff._daily_returns(SHP, int(round(F)))
rf_d = (1 + RF / 100.0) ** (1.0 / F) - 1.0
ex = [x - rf_d for x in r]
mean = sum(ex) / len(ex)
sd = math.sqrt(sum((x - mean) ** 2 for x in ex) / (len(ex) - 1))
want = mean / sd * math.sqrt(F)
near('_sharpe_excess = mean(r−rf)/s(r−rf)×sqrt(年频率)', ff._sharpe_excess(SHP, RF, F), want)

ann1 = ff._annualized(SHP, 244, factor=F)
vol = ff._volatility(SHP, 244, factor=F)
old = (ann1 * 100 - RF) / (vol * 100)
check('算术相减的旧口径与新口径确有差异（>1e-6）', abs(old - want) > 1e-6, (old, want))
eq('常数净值 -> 波动 0 -> 夏普 None',
   ff._sharpe_excess([('2026-01-01', 1.0), ('2026-01-02', 1.0), ('2026-01-03', 1.0)], 2.0, 244.0), None)
eq('rf 缺省 -> 不计算（不用默认值冒充）', ff._sharpe_excess(SHP, None, F), None)
eq('样本不足（2 点）-> None', ff._sharpe_excess([('2026-01-01', 1.0), ('2026-01-02', 1.1)], 2.0, 244.0), None)

# ---------- 5. 跟踪误差同上 ----------
FD = [(base + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(40)]
FUND = [(d, 1.0 + i * 0.005) for i, d in enumerate(FD)]
BENCH = [(d, 100.0 + i * 0.25 * (1 + 0.3 * math.sin(i))) for i, d in enumerate(FD)]
cb = ff.compare_with_benchmark(FUND, BENCH)
te_f, te_src = ff._annualization_factor(FUND)
fv = [a for _, a in FUND]
bv = [b for _, b in BENCH]
check('compare_with_benchmark 输出年频率与来源',
      abs(cb['年频率'] - te_f) < 0.01 and cb['年频率来源'] == te_src,
      (cb.get('年频率'), cb.get('年频率来源')))
near('compare_with_benchmark 年化跟踪误差用实算年频率',
     cb['年化跟踪误差'],
     ff._stdev([(fv[i] / fv[i - 1] - 1) - (bv[i] / bv[i - 1] - 1) for i in range(1, len(fv))])
     * math.sqrt(te_f), 2e-6)

print('\n%d/%d passed' % (TOTAL - len(FAILS), TOTAL))
if FAILS:
    for f in FAILS:
        print('  - ' + f)
    sys.exit(1)
