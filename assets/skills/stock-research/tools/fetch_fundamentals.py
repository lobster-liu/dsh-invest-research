#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
fetch_fundamentals.py — 财务基本面取数器（akshare 通道）

补齐 fetch_data.py（HTTP 兜底）覆盖不到的财务数据，直接命中 2026-10-15 两轮实测的数据缺口：
  - 财务分析指标：ROE / 每股净资产 / 资产负债率 / 毛利率 / 净利率 / 流动比率 / 速动比率（22 期 × 86 列）
  - 财务摘要：归母净利 / 营收 / 同比 / 扣非 / 经营现金流（80 指标 × 88 报告期）
  - 估值长历史：PE(TTM) / PB 近一年日序列 → 真分位（百度估值接口）
  - 银行监管指标（不良率/拨备覆盖率/资本充足率）：akshare 1.19.x 已移除该接口，
    改由 fetch_data.py 的 HTTP 通道（东财 datacenter）补取

实测可用接口（akshare 1.19.1，2026-10-16）：
  ak.stock_financial_analysis_indicator(symbol=code, start_year='2021')   ✅ 22×86
  ak.stock_financial_abstract(symbol=code)                                ✅ 80×88
  ak.stock_zh_valuation_baidu(symbol, indicator, period)                  ✅ 366×2

用法：
  python fetch_fundamentals.py --code 600048 --out runs/<runid>/fundamentals.json
  python fetch_fundamentals.py --code 600048 --no-bank      # 跳过银行股判定

铁律（与 fetch_data.py 相同）：
  - 取不到填 null，禁止估算；每条带 {指标, 值, 单位, 口径, 来源, 数据日期, 取数时间, stale, 备注}
  - 部分接口失败不影响其余（逐接口 try/except，失败的记入「失败接口」）
  - akshare 不可用时退出码 1，不得用 HTTP 顶替（那是 fetch_data.py 的职责）

退出码：0 = 至少 1 条数据；1 = 全部失败 / akshare 不可用；2 = 用法错误
"""
import argparse
import json
import os
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _rec(metric, value, unit, caliber, source, data_date, note=''):
    stale = False
    if data_date:
        try:
            d = datetime.strptime(str(data_date)[:10], '%Y-%m-%d')
            # 财报季节奏：季报最迟 ~4 个月，年报 ~4 个月；100 天阈值偏严但安全
            stale = (datetime.now() - d).days > 100
        except Exception:
            stale = True
    return {'指标': metric, '值': value, '单位': unit, '口径': caliber,
            '来源': source, '数据日期': data_date, '取数时间': _now(),
            'stale': stale, '备注': note}


def _safe_num(v):
    try:
        f = float(v)
        if f != f or abs(f) == float('inf'):  # NaN / inf
            return None
        return round(f, 4)
    except Exception:
        return None


def _try(fn, name, failed):
    try:
        fn()
    except Exception as e:
        failed.append(f'{name}: {type(e).__name__}: {str(e)[:160]}')


def main():
    ap = argparse.ArgumentParser(description='财务基本面取数器（akshare 通道）')
    ap.add_argument('--code', required=True, help='A 股代码，如 600048')
    ap.add_argument('--out', required=True, help='输出 JSON 路径')
    ap.add_argument('--no-bank', action='store_true', help='跳过银行指标探测（非银行股可加速）')
    args = ap.parse_args()
    code = args.code.strip()
    if not (code.isdigit() and len(code) == 6):
        print(f'[FATAL] code 必须是 6 位数字，收到: {code}', file=sys.stderr)
        return 2

    try:
        import akshare as ak
    except Exception as e:
        print(f'[FATAL] akshare 不可用: {e}\n'
              f'  请用 equity-pipeline\\venv-ak 的 python 运行本脚本，\n'
              f'  或按 README 的「akshare 离线安装」节先装好依赖。',
              file=sys.stderr)
        return 1

    import pandas as pd
    records = []
    failed = []
    payload = {'标的': code, '取数时间': _now(), 'akshare版本': getattr(ak, '__version__', '?'),
                '通道': 'akshare', '数据': [], '失败接口': []}

    # ---- 1. 财务分析指标（通用，22 期 × 86 列）----
    def f_indicators():
        df = ak.stock_financial_analysis_indicator(symbol=code, start_year='2021')
        if df is None or df.empty:
            return
        want = {
            '净资产收益率(%)': ('净资产收益率(ROE)', '%', '报告期'),
            '主营业务利润率(%)': ('主营业务利润率', '%', '报告期'),
            '资产负债率(%)': ('资产负债率', '%', '时点'),
            '每股净资产_调整前(元)': ('每股净资产', '元', '时点'),
            '每股收益_调整后(元)': ('每股收益', '元', '累计'),
            '流动比率': ('流动比率', '倍', '时点'),
            '速动比率': ('速动比率', '倍', '时点'),
            '每股经营性现金流(元)': ('每股经营性现金流', '元', '报告期'),
        }
        for _, row in df.tail(4).iterrows():
            date = str(row.get('日期', ''))[:10]
            for col, (name, unit, cal) in want.items():
                if col in df.columns:
                    v = _safe_num(row[col])
                    if v is not None:
                        records.append(_rec(f'{name}({date})', v, unit, cal,
                                            'akshare.stock_financial_analysis_indicator', date))
    _try(f_indicators, 'stock_financial_analysis_indicator', failed)

    # ---- 2. 财务摘要（归母净利 / 营收 / 同比，80 指标 × 88 报告期）----
    def f_abstract():
        df = ak.stock_financial_abstract(symbol=code)
        if df is None or df.empty:
            return
        key_rows = ['归母净利润', '营业总收入', '营业总收入同比增长', '归母净利润同比增长',
                    '扣非净利润', '经营现金流量净额', '资产负债率', '净资产收益率(ROE)',
                    '销售净利率', '毛利率']
        date_cols = [c for c in df.columns if str(c).isdigit() and len(str(c)) == 8]
        date_cols = sorted(date_cols)[-2:]
        for _, row in df.iterrows():
            ind = str(row.get('指标', ''))
            if ind in key_rows:
                for dc in date_cols:
                    d = f'{str(dc)[:4]}-{str(dc)[4:6]}-{str(dc)[6:]}'
                    v = _safe_num(row[dc])
                    if v is not None:
                        if '同比' in ind:
                            unit, val, cal = '%', v, '累计同比'
                        elif abs(v) > 1e8:
                            unit, val, cal = '亿元', round(v / 1e8, 4), '累计'
                        elif abs(v) > 1e4:
                            unit, val, cal = '万元', round(v / 1e4, 2), '累计'
                        else:
                            unit, val, cal = '元', v, '累计'
                        records.append(_rec(f'{ind}({d})', val, unit, cal,
                                            'akshare.stock_financial_abstract', d))
                        break  # 每行只取最新一期，避免记录爆炸
    _try(f_abstract, 'stock_financial_abstract', failed)

    # ---- 3. 估值长历史（PE/PB 近一年日序列 → 真分位）----
    def f_valuation_percentile():
        for indicator, label in [('市盈率(TTM)', 'PE(TTM)'), ('市净率', 'PB')]:
            try:
                df = ak.stock_zh_valuation_baidu(symbol=code, indicator=indicator, period='近一年')
                if df is None or df.empty or 'value' not in df.columns:
                    continue
                s = df['value'].dropna()
                if len(s) < 30:
                    continue
                cur = float(s.iloc[-1])
                pct = round(float((s < cur).sum()) / len(s) * 100, 2)
                d0 = str(df['date'].iloc[0])[:10]
                d1 = str(df['date'].iloc[-1])[:10]
                records.append(_rec(f'{label}近一年分位', pct, '%', '区间',
                                    'akshare.stock_zh_valuation_baidu', d1,
                                    note=f'样本 {len(s)} 日，{d0}→{d1}，当前 {cur}'))
            except Exception as e:
                failed.append(f'stock_zh_valuation_baidu({label}): {type(e).__name__}')
    _try(f_valuation_percentile, 'stock_zh_valuation_baidu', failed)

    # ---- 4. 银行监管指标（不良率 / 拨备覆盖率 / 资本充足率）----
    # akshare 1.19.x 移除了 stock_bank_indicator_sina；这些银保监会监管指标
    # 由 fetch_data.py 的 HTTP 通道（东财 datacenter）负责，本脚本不越界。
    if not args.no_bank and code.startswith('6') and code in (
        '600000','600015','600016','600036','601009','601166','601288','601318',
        '601328','601398','601628','601818','601939','601988','601998','000001'):
        failed.append('银行监管指标(不良率/拨备/资本充足率): '
                      'akshare 1.19.x 无此接口，请用 fetch_data.py HTTP 通道补取')

    # ---- 输出 ----
    payload['记录数'] = len(records)
    payload['失败接口'] = failed
    payload['数据'] = records
    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    summary = {'标的': code, '记录数': len(records), '失败接口': failed,
               'akshare版本': payload['akshare版本']}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not records:
        print('[FATAL] 全部接口失败，不得估算填补', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
