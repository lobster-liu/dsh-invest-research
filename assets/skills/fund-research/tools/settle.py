#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
settle.py —— 决策结算（把过去的决策与已发生的行情对齐）

存在理由
--------
决策做完就散落在各自的 run 目录里，没人回头看它对不对。
结算把「决策日 + 结论标签」和「之后实际发生了什么」对齐，产出：
  - 原始收益（窗口末相对窗口初）
  - 超额收益 alpha（原始收益 − 基准同期收益）
  - 结算状态（SETTLED / PENDING / SETTLE_FAILED）

口径（与 decision_score.py 对齐，数字才可复核）
----------------------------------------------
  - **入场**：决策日**之后第一个收盘日**。决策日当天收盘后才发布的信息
    （当日净值、当日公告）不应计入，因此不能从决策日收盘起算。
  - **出场**：入场后第 `holding_days` 个收盘日。
  - **基准**：同一区间上的基准序列；基准必须覆盖入出场两端，
    否则结算失败（不拿半个区间的基准凑一个 alpha）。
  - **窗口未走完** → PENDING，不是 SETTLED。**不得用未走完的涨跌冒充结论验证。**

输入（全部只读）：
  --ledger       决策日志 ledger.jsonl
  --series       价格/净值序列 JSON：{"<code>": {"序列": [[日期, 值], ...]}}
                 或 {"<code>": [[日期, 值], ...]}
  --benchmark    基准序列 JSON：{"序列": [[日期, 值], ...]} 或 [[日期, 值], ...]
  --holding-days 持有窗口（交易日），默认 20
  --out          输出 settlements.json

输出：settlements.json，元素形如
  {"code","as_of","label","状态","原始收益","基准收益","超额收益",
   "入场日","出场日","持有交易日数","原因"}
"""

import argparse
import io
import json
import os
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from rating import REVIEW
except Exception:  # pragma: no cover
    REVIEW = 'REVIEW'

SETTLED = 'SETTLED'
PENDING = 'PENDING'
SETTLE_FAILED = 'SETTLE_FAILED'


def _parse_date(v):
    if v is None:
        return None
    text = str(v).strip()
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y%m%d'):
        try:
            return datetime.strptime(text[:10], fmt)
        except ValueError:
            continue
    return None


def load_json(path):
    if not path or not os.path.exists(path):
        return None
    try:
        with io.open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return None


def load_jsonl(path):
    records = []
    if not path or not os.path.exists(path):
        return records
    with io.open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    records.append(obj)
            except Exception:
                continue
    return records


def normalize_series(obj):
    """把各种形状的序列输入统一成 ``[(datetime, float), ...]``（按日期升序）。"""
    if obj is None:
        return []
    rows = obj
    if isinstance(obj, dict):
        for key in ('序列', 'series', 'nav', '净值序列'):
            if key in obj:
                rows = obj[key]
                break
        else:
            rows = []
    if isinstance(rows, dict):
        rows = rows.get('序列') or []
    out = []
    for row in rows or []:
        if isinstance(row, (list, tuple)) and len(row) >= 2:
            d = _parse_date(row[0])
            try:
                v = float(row[1])
            except (TypeError, ValueError):
                continue
            if d is not None:
                out.append((d, v))
        elif isinstance(row, dict):
            d = _parse_date(row.get('日期') or row.get('date'))
            raw = row.get('值') if row.get('值') is not None else row.get('value')
            try:
                v = float(raw)
            except (TypeError, ValueError):
                continue
            if d is not None:
                out.append((d, v))
    out.sort(key=lambda x: x[0])
    # 去重（同日保留最后一条）
    dedup, seen = [], set()
    for d, v in out:
        if d in seen:
            dedup[-1] = (d, v)
        else:
            seen.add(d)
            dedup.append((d, v))
    return dedup


def extract_map(obj):
    """把输入整理成 ``{code: series}``。"""
    if not isinstance(obj, dict):
        return {}
    if '序列' in obj or 'series' in obj:
        return {}
    out = {}
    for key, val in obj.items():
        if key.startswith('_'):
            continue
        out[str(key)] = normalize_series(val)
    return out


def settle_one(decision, series, bench_series, holding_days):
    """结算一条决策。返回一条结算记录。"""
    code = str(decision.get('code') or '')
    as_of = str(decision.get('as_of') or '')
    label = decision.get('label')
    if not isinstance(label, str) or not label:
        label = REVIEW

    def pending(reason):
        return {'code': code, 'as_of': as_of, 'label': label, '状态': PENDING,
                '原始收益': None, '基准收益': None, '超额收益': None,
                '入场日': None, '出场日': None, '持有交易日数': None, '原因': reason}

    def failed(reason):
        rec = pending(reason)
        rec['状态'] = SETTLE_FAILED
        return rec

    if not series:
        return failed('无可用价格/净值序列')
    decision_date = _parse_date(as_of)
    if decision_date is None:
        return failed('决策日无法解析：%s' % as_of)

    # 入场：决策日之后第一个收盘日
    after = [(d, v) for d, v in series if d > decision_date]
    if len(after) <= holding_days:
        return pending('持有窗口未走完（需 %d 个交易日，现有 %d 个）'
                       % (holding_days + 1, len(after)))
    entry_date, entry_price = after[0]
    exit_date, exit_price = after[holding_days]
    if not entry_price:
        return failed('入场价无效')

    raw = (exit_price - entry_price) / entry_price

    # 基准：必须覆盖入出场两端
    bench_return = None
    if bench_series:
        before = [(d, v) for d, v in bench_series if d <= entry_date]
        if not before:
            return failed('基准序列在入场日之前无数据')
        bench_entry = before[-1][1]
        up_to_exit = [(d, v) for d, v in bench_series if d <= exit_date]
        if not up_to_exit or up_to_exit[-1][0] < exit_date:
            return failed('基准序列未覆盖出场日')
        bench_exit = up_to_exit[-1][1]
        if not bench_entry:
            return failed('基准入场值无效')
        bench_return = (bench_exit - bench_entry) / bench_entry
        alpha = raw - bench_return
    else:
        alpha = None

    return {
        'code': code, 'as_of': as_of, 'label': label, '状态': SETTLED,
        '原始收益': round(raw, 6),
        '基准收益': (round(bench_return, 6) if bench_return is not None else None),
        '超额收益': (round(alpha, 6) if alpha is not None else None),
        '入场日': entry_date.strftime('%Y-%m-%d'),
        '出场日': exit_date.strftime('%Y-%m-%d'),
        '持有交易日数': holding_days,
        '原因': '',
    }


def settle_all(decisions, series_map, bench_series, holding_days):
    """结算全部决策。返回 (结算记录列表, 按代码统计)。"""
    records = []
    for dec in decisions:
        code = str(dec.get('code') or '')
        series = series_map.get(code) or []
        records.append(settle_one(dec, series, bench_series, holding_days))
    by_code = {}
    for rec in records:
        by_code.setdefault(rec['code'], {'SETTLED': 0, 'PENDING': 0, 'SETTLE_FAILED': 0})
        by_code[rec['code']][rec['状态']] += 1
    return records, by_code


def main():
    ap = argparse.ArgumentParser(description='决策结算')
    ap.add_argument('--ledger', required=True, help='决策日志 ledger.jsonl')
    ap.add_argument('--series', required=True, help='价格/净值序列 JSON')
    ap.add_argument('--benchmark', default=None, help='基准序列 JSON')
    ap.add_argument('--holding-days', type=int, default=20, help='持有窗口（交易日）')
    ap.add_argument('--out', required=True, help='输出 settlements.json 路径')
    args = ap.parse_args()

    decisions = load_jsonl(args.ledger)
    if not decisions:
        print('[WARN] 决策日志为空或不可读：%s' % args.ledger, file=sys.stderr)

    series_obj = load_json(args.series)
    series_map = extract_map(series_obj)
    if not series_map and series_obj is not None:
        # 单标的形态：直接当作该 code 的序列
        for dec in decisions:
            series_map.setdefault(str(dec.get('code') or ''), normalize_series(series_obj))

    bench = normalize_series(load_json(args.benchmark))

    records, by_code = settle_all(decisions, series_map, bench, args.holding_days)

    payload = {
        '持有窗口': args.holding_days,
        '结算数': len(records),
        '按代码': by_code,
        '结算': records,
        '口径与局限': [
            '入场取决策日之后第一个收盘日（决策日当天收盘后才发布的信息不计入）',
            '出场取入场后第 %d 个交易日' % args.holding_days,
            '窗口未走完记 PENDING，结算失败记 SETTLE_FAILED，两者均不计入命中率',
            '超额收益 = 原始收益 − 基准同期收益；基准未覆盖入出场两端则结算失败',
            '本表评估决策质量，不模拟持仓，不产生买卖建议',
        ],
    }
    directory = os.path.dirname(os.path.abspath(args.out))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with io.open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    counts = {'SETTLED': 0, 'PENDING': 0, 'SETTLE_FAILED': 0}
    for rec in records:
        counts[rec['状态']] = counts.get(rec['状态'], 0) + 1
    print(json.dumps({'输出': args.out, '结算数': len(records),
                      '已结算': counts.get('SETTLED', 0),
                      '未到期': counts.get('PENDING', 0),
                      '结算失败': counts.get('SETTLE_FAILED', 0)},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
