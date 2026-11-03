#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
test_fund_cost.py — 销售费用净成本口径的行为用例（F1–F7）

对应 `assets/skills/_shared/references/fee-rules-2026.md` §5 的降级表：
  F1 直销 2026 年实收 > 0 → 按实收放行
  F2 直销 2027-01-01 及以后认（申）购费实收 > 0 → CostCaliberError（E1）
  F3 2027 后销售服务费 实收 = 应退 → 放行，净成本 0 且两列都在
  F4 2027 后销售服务费只给实收、不给应退 → CostCaliberError（E2）
  F5 持有期跨 2027-01-01 → 必须分段，否则 CostCaliberError（E4）
  F6 费率版本键 = (基金代码, 费率变更生效日)
  F7 规则未核到 → 「费用不可精确复算」，不估算

全部离线。用法: python test_fund_cost.py
退出码: 0 = 全部通过；1 = 有失败
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import fund_cost as fc
except Exception as e:  # pragma: no cover
    print('[FAIL] cannot import fund_cost:', e)
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


def raises(name, code, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except fc.CostCaliberError as e:
        eq(name, e.code, code)
        return
    except Exception as e:  # 类型错也要看见
        check(name, False, 'raised %r' % (e,))
        return
    check(name, False, 'no exception')


# ---------- F1：直销 2026 年实收 > 0 按实收放行 ----------
leg = fc.validate_fee_leg('直销', '2026-05-01', '认申购费', 1.5)
eq('F1 直销 2026 认申购费 净成本=实收 1.5', leg['净成本'], 1.5)
check('F1 2027 后直销才归零，2026 仍是实收', leg['口径'].startswith('实收'), leg['口径'])
leg_d = fc.validate_fee_leg('代销', '2027-06-01', '认申购费', 0.8)
eq('F1b 代销腿 2027 后认申购费仍可收（第八条上限内）', leg_d['净成本'], 0.8)

# ---------- F2：直销 2027 起认（申）购费实收 > 0 ----------
raises('F2 直销 2027-01-01 认申购费实收>0 -> E1', 'E1',
       fc.validate_fee_leg, '直销', '2027-01-01', '认申购费', 0.8)
raises('F2b 直销 2027-06-30 认申购费实收>0 -> E1', 'E1',
       fc.validate_fee_leg, '直销', '2027-06-30', '认申购费', 0.01)
eq('F2c 边界：2026-12-31 直销认申购费 仍放行',
   fc.validate_fee_leg('直销', '2026-12-31', '认申购费', 0.8)['净成本'], 0.8)
eq('F2d 直销 2027 后认申购费实收=0 放行',
   fc.validate_fee_leg('直销', '2027-03-01', '认申购费', 0.0)['净成本'], 0.0)

# ---------- F3：2027 后销售服务费 实收 = 应退 ----------
leg = fc.validate_fee_leg('直销', '2027-06-30', '销售服务费', 0.4, 0.4)
eq('F3 净成本 = 0', leg['净成本'], 0.0)
eq('F3 两列都在（实收/应退）', (leg['实收'], leg['应退']), (0.4, 0.4))
check('F3 口径写清「现金流不为 0」', '不为 0' in leg['口径'], leg['口径'])
eq('F3b 2026 年销售服务费：实收、无应退（存量不返还）',
   fc.validate_fee_leg('代销', '2026-09-30', '销售服务费', 0.3)['净成本'], 0.3)

# ---------- F4：只给一腿 ----------
raises('F4 2027 后销售服务费缺应退 -> E2', 'E2',
       fc.validate_fee_leg, '直销', '2027-06-30', '销售服务费', 0.4)
raises('F4b 应退 ≠ 实收 -> E3', 'E3',
       fc.validate_fee_leg, '直销', '2027-06-30', '销售服务费', 0.4, 0.2)
raises('F4c 2027 前给应退 -> E7（存量不返还）', 'E7',
       fc.validate_fee_leg, '代销', '2026-12-01', '销售服务费', 0.4, 0.4)

# ---------- F5：跨 2027 必须分段 ----------
segs = fc.split_holding_period('2026-06-01', '2027-06-01')
eq('F5 跨 2027 切成两段', [s[2] > 0 for s in segs], [True, True])
eq('F5 分界点：第一段止于 2026-12-31，第二段始于 2027-01-01',
   (segs[0][1], segs[1][0]), ('2026-12-31', '2027-01-01'))
eq('F5b 未跨期只有一段', len(fc.split_holding_period('2026-01-01', '2026-06-01')), 1)
legs_pre = [fc.validate_fee_leg('直销', '2026-09-01', '销售服务费', 0.1)]
raises('F5c 跨期却只有 2026 腿 -> E4', 'E4', fc.validate_holding_window,
       '2026-06-01', '2027-06-01', legs_pre)
legs_both = legs_pre + [fc.validate_fee_leg('直销', '2027-03-01', '销售服务费', 0.1, 0.1)]
eq('F5d 两段都有腿 -> 放行', len(fc.validate_holding_window('2026-06-01', '2027-06-01', legs_both)), 2)
eq('F5e 净成本按腿求和（0.1 + 0）', round(fc.net_cost(legs_both), 10), 0.1)

# ---------- F6：费率版本键 ----------
eq('F6 版本键 = (代码, 生效日)',
   fc.fee_version_key('000001', '2026-03-01'), ('000001', '2026-03-01'))
check('F6b 同一基金不同生效日 -> 不同版本',
      fc.fee_version_key('000001', '2026-03-01') != fc.fee_version_key('000001', '2027-01-01'))
raises('F6c 代码为空 -> E7', 'E7', fc.fee_version_key, '', '2026-03-01')

# ---------- F7：未核到规则不估算 ----------
eq('F7 固定短语', fc.UNVERIFIED, '费用不可精确复算')
eq('F7 带原因', fc.unverified_note('未取到费率变更公告'), '费用不可精确复算：未取到费率变更公告')

# ---------- 输入校验 ----------
raises('负金额 -> E7', 'E7', fc.validate_fee_leg, '直销', '2026-05-01', '认申购费', -1)
raises('渠道非法 -> E7', 'E7', fc.validate_fee_leg, '银行', '2026-05-01', '认申购费', 1)
raises('费种非法 -> E7', 'E7', fc.validate_fee_leg, '直销', '2026-05-01', '管理费', 1)
raises('日期非法 -> E7', 'E7', fc.validate_fee_leg, '直销', '2026/05/01', '认申购费', 1)
eq('in_transition 边界', (fc.in_transition('2026-12-31'), fc.in_transition('2027-01-01')),
   (False, True))

print('\n%d/%d passed' % (TOTAL - len(FAILS), TOTAL))
if FAILS:
    for f in FAILS:
        print('  - ' + f)
    sys.exit(1)
