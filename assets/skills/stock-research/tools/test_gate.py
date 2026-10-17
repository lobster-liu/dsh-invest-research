#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
test_gate.py — 脱敏门禁行为自检(stock-research + fund-research 安装验证用)

断言四件事(全部通过才 exit 0):
  A. 真泄漏必拦        (持仓/成本/资金/盈亏/账户 5 类)
  B. 公开条款必放      (政策数字、财报科目、否定式声明、半角负数)
  C. 混合陷阱必拦      ("豁免词 + 真泄漏"同句不得互相掩护)
  D. 基金公开披露必放  (净值/收益/规模/份额/持有人/持仓占比/跟踪误差 — fund-research)

用法: python test_gate.py   (与本文件同目录存在 sanitize_check.py)
退出码: 0 = 全过; 1 = 有失败(门禁行为不可信, 修好前勿用于正式流水线)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    import sanitize_check as sc
except Exception as e:
    print('[FAIL] cannot import sanitize_check:', e)
    sys.exit(1)


def blocking_hits(line):
    return [h for h in sc.scan_text(line, 'probe')
            if h['severity'] in ('CRITICAL', 'HIGH')]


MUST_BLOCK = [
    '我持仓 12000 股，成本价 8.35 元，投入资金 10 万元，浮盈 2.3 万。',
    '我的成本价 8.35，不加单位也应该抓住。',
    '本人持有 5000 股该标的。',
    '目前浮盈 15 万元。',
    '资金账号 888123456 已绑定。',
    '本次政策显示再贷款额度扩大。同时我持仓 12000 股，成本价 8.35 元。',
    '货币资金 8888.88 亿元。同时我持仓 12000 股，成本价 8.35 元。',
    '目前浮盈（15 万元）我忘了说。',
    '公司披露归母净利润 7.77 亿元，而我投入资金 10 万元。',
    # 公司层面豁免不得掩护第一人称盈亏（fund-research 场景）
    '我盈利 12.5 万元。',
    '个人盈利 3.5 万元。',
    '我的仓位盈利 12.5 万元。',
]
MUST_PASS = [
    '单户上限100万元，本金年化1个百分点贴息，资金总规模不设上限，2026-10-01起实施。',
    '货币资金 8888.88 亿元，综合融资成本 2.50%，合同负债 5000.00 亿元，归母净利润 7.77 亿元。',
    '上年同期为亏损(-28.11 亿元)，正值表示亏损收窄。',
    '新增有息负债平均成本 2.44%（同比 -27bp）。',
    '本报告不涉及任何资金规模，未记录个人持仓与成本价。',
    '财政贴息降低购房者实际利率成本（约为现行利率的1/3）。',
    # D. 基金公开披露口径（fund-research 报告会出现的合法表述）
    '单位净值 0.7989 元，累计净值 0.7989，净值增长率 2.69%，净值分位 21.31%。',
    '近1年收益 -20.09%，成立以来收益 -20.11%，今年以来 -38.08%，年化收益 -21.50%。',
    '基金规模 4.76 亿元（2026-06-30），总份额 4.16 亿份，机构持有比例 0.03%。',
    '股票占净比 94.82%，债券占净比 0%，现金占净比 9.70%，持仓占比 9.06%。',
    '年化跟踪误差 8.18%，同类排名 6/4505，同类平均 2.22%，超额收益 -12.23%。',
    '基金经理马浩然任职时长 361 天，管理规模 108.48 亿，任期收益 -19.06%。',
    '期间申购 3.39 亿份，期间赎回 3.24 亿份，份额变动:总份额 4.16 亿份。',
    '重仓股中国卫星 PE(TTM) 88 倍，PB 5.71 倍，总市值 602 亿元。',
    '公司盈利 12.5 亿元，行业盈利同比转正，预计盈利改善。',
]

def main():
    fails = []
    for i, line in enumerate(MUST_BLOCK, 1):
        if not blocking_hits(line):
            fails.append(f'A{i} LEAK-MISSED  {line[:42]}')
    for i, line in enumerate(MUST_PASS, 1):
        hits = blocking_hits(line)
        if hits:
            fails.append(f'B{i} FALSE-BLOCK  {line[:42]}  <- {hits[0]["rule"]}')
    print(f'gate self-test: {len(MUST_BLOCK) + len(MUST_PASS)} scenarios, '
          f'{len(fails)} failed')
    for f in fails:
        print('  FAIL', f)
    if fails:
        print('❌ 门禁行为不可信 — 修复 sanitize_check.py 前不得用于正式流水线')
        return 1
    print('✅ 门禁行为正确: 真泄漏全拦、公开条款全放、混合陷阱全拦、基金公开披露全放')
    return 0


if __name__ == '__main__':
    sys.exit(main())
