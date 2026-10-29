#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
行情数据取数器 —— 数据员(Data)角色的唯一取数入口

设计原则（对齐多智能体分工约定）：
  1. **只输出结构化 JSON**，字段固定：{指标, 值, 单位, 口径, 来源, 数据日期, 取数时间}
  2. **取不到填 null，禁止估算**。绝不编造、绝不插值、绝不用"大约"。
  3. **自动标注 stale**：行情 > 1 交易日、月度数据 > 45 天 → stale=true
  4. **双通道**：akshare 优先，失败则降级到东方财富 HTTP 公开接口

用法：
  python fetch_data.py --code 600000 --out runs/<runid>/data.json
  python fetch_data.py --code 600000 --sector --out ...     # 板块层面

退出码：
  0 = 成功（无论有多少 null，都能写出合法 JSON）
  1 = 致命错误（无法写出文件）
  2 = 用法错误
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 时点纪律底座（与 fund-research 共用；本目录为两 skill 的共享工具目录）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from pit import AsOf, build_as_of, parse_date
except Exception:  # pragma: no cover - 底座缺失时降级为「不截断」，不阻断取数
    AsOf = None
    build_as_of = None
    parse_date = None

# 陈旧阈值：行情 1 交易日，月度 45 天
STALE_QUOTE_DAYS = 3      # 1 交易日 + 周末容差
STALE_MONTHLY_DAYS = 45

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _rec(metric, value, unit, caliber, source, data_date, stale=None, note=''):
    """构造一条标准记录。stale 为 None 时按数据日期自动判定。"""
    if stale is None:
        stale = _calc_stale(data_date, caliber)
    return {
        '指标': metric,
        '值': value,
        '单位': unit,
        '口径': caliber,
        '来源': source,
        '数据日期': data_date,
        '取数时间': _now(),
        'stale': stale,
        '备注': note,
    }


def _rec_pit(metric, value, unit, caliber, source, data_date, asof=None,
             disclose_type=None, note='', stale=None):
    """构造一条带**披露日期**的标准记录（时点纪律版）。

    与 `_rec` 的区别：
      1. 多出 `披露日期` 字段 —— 公众首次可读之日；取不到写「未取得」，
         绝不用数据日期冒充（重述就靠这个字段暴露）。
      2. 披露日期晚于基准日的记录，强制 `stale=true` 并在备注注明「基准日后披露」——
         `stale` 原本只说明「标签有多旧」，不说明「内容在基准日是否可见」，
         这里补上后视维度。
    """
    rec = _rec(metric, value, unit, caliber, source, data_date, stale=stale, note=note)
    if asof is None or not getattr(asof, 'is_set', False):
        rec['披露日期'] = '未取得'
        return rec

    from pit import disclosure_date
    disclosed = disclosure_date(data_date, disclose_type)
    rec['披露日期'] = disclosed
    visible = asof.visible(data_date, disclose_type)
    if not visible:
        rec['stale'] = True
        extra = '；基准日后披露，基准日不可见'
        rec['备注'] = (rec['备注'] + extra) if rec['备注'] else extra.lstrip('；')
    if disclosed != '未取得':
        tag = '；披露日期 %s（推算）' % disclosed
        rec['备注'] = (rec['备注'] + tag) if rec['备注'] else tag.lstrip('；')
    return rec


def _calc_stale(data_date, caliber):
    """按口径判定数据是否陈旧。无法解析日期 → 保守判为 True。"""
    if not data_date:
        return True
    try:
        d = datetime.strptime(str(data_date)[:10], '%Y-%m-%d')
    except Exception:
        return True
    age = (datetime.now() - d).days
    limit = STALE_MONTHLY_DAYS if caliber in ('月度', '累计', '季报', '年报') else STALE_QUOTE_DAYS
    return age > limit


def _http_json(url, timeout=15, retries=3):
    """直连 HTTP 兜底通道。带重试——行情接口偶发断连是常态，一次失败不应判死。"""
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8', errors='replace'))
        except Exception as e:
            last = e
            if i < retries - 1:
                time.sleep(1.5 * (i + 1))
    raise last


# ---------------------------------------------------------------------------
# 通道一：akshare
# ---------------------------------------------------------------------------

def _try_akshare():
    try:
        import akshare  # noqa: F401
        return True
    except Exception:
        return False


def fetch_quote_akshare(code):
    """A股实时行情快照（akshare）。"""
    import akshare as ak
    df = ak.stock_zh_a_spot_em()
    row = df[df['代码'] == code]
    if row.empty:
        return []
    r = row.iloc[0]
    out = []
    m = [
        ('最新价', '最新价', '元', '时点'),
        ('涨跌幅', '涨跌幅', '%', '时点'),
        ('成交量', '成交量', '手', '时点'),
        ('成交额', '成交额', '元', '时点'),
        ('市盈率-动态', '市盈率(动态)', '倍', '时点'),
        ('市净率', '市净率', '倍', '时点'),
        ('总市值', '总市值', '元', '时点'),
        ('流通市值', '流通市值', '元', '时点'),
    ]
    for col, name, unit, cal in m:
        if col in row.columns:
            v = r[col]
            v = None if v in ('', '-', None) else (float(v) if _is_num(v) else str(v))
            out.append(_rec(name, v, unit, cal, 'akshare.stock_zh_a_spot_em',
                            datetime.now().strftime('%Y-%m-%d'), note='实时快照'))
    return out


def fetch_history_akshare(code, days=800, asof=None):
    """历史行情，用于估值分位与回撤测算。返回 (records, dataframe_or_None)。

    时点纪律：给定 `asof` 时，窗口终点是**基准日**而不是当下；
    取回后再按日期二次截断（akshare 的 end_date 过滤对缺失交易日不总是可靠）。
    """
    import akshare as ak
    anchor = getattr(asof, 'as_of', None) or datetime.now().date()
    end = anchor.strftime('%Y%m%d')
    start = (anchor - timedelta(days=int(days * 1.6))).strftime('%Y%m%d')
    df = ak.stock_zh_a_hist(symbol=code, period='daily',
                            start_date=start, end_date=end, adjust='qfq')
    if df is None or df.empty:
        return [], None
    # 二次截断：确保不会有任何一行晚于基准日
    df, dropped = _truncate_df(df, asof)
    if df is None or df.empty:
        return [], None
    last = df.iloc[-1]
    out = [
        _rec('历史区间起始', str(df.iloc[0]['日期'])[:10], '日期', '区间',
             'akshare.stock_zh_a_hist', str(df.iloc[0]['日期'])[:10]),
        _rec('历史区间结束', str(last['日期'])[:10], '日期', '区间',
             'akshare.stock_zh_a_hist', str(last['日期'])[:10]),
        _rec('样本交易日数', int(len(df)), '天', '区间',
             'akshare.stock_zh_a_hist', str(last['日期'])[:10]),
        _rec('区间最高价', float(df['最高'].max()), '元', '区间',
             'akshare.stock_zh_a_hist', str(last['日期'])[:10]),
        _rec('区间最低价', float(df['最低'].min()), '元', '区间',
             'akshare.stock_zh_a_hist', str(last['日期'])[:10]),
    ]
    if dropped:
        out.append(_rec('基准日后剔除行数', dropped, '行', '区间',
                        'pit:truncate', str(last['日期'])[:10],
                        note=f'晚于基准日 {getattr(asof, "iso", "")} 的行情行已剔除'))
    return out, df


def _is_num(v):
    try:
        float(v)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 通道二：东方财富 HTTP 兜底（零依赖）
# ---------------------------------------------------------------------------

def fetch_quote_http(code):
    """东方财富实时行情兜底。沪深判断：6/9 开头为沪市(1)，否则深市(0)。"""
    market = '1' if code[:1] in ('6', '9') else '0'
    url = ('https://push2.eastmoney.com/api/qt/stock/get'
           f'?secid={market}.{code}'
           '&fields=f43,f44,f45,f46,f47,f48,f57,f58,f60,f162,f167,f168,f170')
    d = _http_json(url).get('data') or {}
    if not d:
        return []
    # 东财价格类字段为整数，需按 f59 小数位还原；此处取常用两位
    def p(v, div=100):
        return None if v in (None, '-', 0, '') else round(float(v) / div, 4)

    mapping = [
        ('最新价', d.get('f43'), '元', '时点', 100),
        ('最高价', d.get('f44'), '元', '时点', 100),
        ('最低价', d.get('f45'), '元', '时点', 100),
        ('今开', d.get('f46'), '元', '时点', 100),
        ('成交量', d.get('f47'), '手', '时点', 1),
        ('成交额', d.get('f48'), '元', '时点', 1),
        ('市盈率(动态)', d.get('f162'), '倍', '时点', 100),
        ('市净率', d.get('f167'), '倍', '时点', 100),
        ('总市值', d.get('f116') or d.get('f84'), '元', '时点', 1),
    ]
    today = datetime.now().strftime('%Y-%m-%d')
    out = []
    for name, v, unit, cal, div in mapping:
        if v in (None, '-', ''):
            out.append(_rec(name, None, unit, cal, 'eastmoney.http', today,
                            note='字段缺失'))
        else:
            out.append(_rec(name, p(v, div), unit, cal, 'eastmoney.http', today))
    return out


def fetch_history_http(code, days=800, asof=None):
    """东方财富 K 线兜底。返回 (records, dataframe_or_None)。

    时点纪律：给定 `asof` 时，K 线请求的 end 参数是基准日（而非 20500101 这个
    写死的远期值），并在本地按日期二次截断。
    """
    market = '1' if code[:1] in ('6', '9') else '0'
    anchor = getattr(asof, 'as_of', None) or datetime.now().date()
    end_param = anchor.strftime('%Y%m%d')
    url = ('https://push2his.eastmoney.com/api/qt/stock/kline/get'
           f'?secid={market}.{code}&klt=101&fqt=1'
           f'&lmt={int(days)}&end={end_param}'
           '&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56')
    d = _http_json(url).get('data') or {}
    klines = d.get('klines') or []
    if not klines:
        return [], None
    rows = []
    for line in klines:
        parts = line.split(',')
        rows.append({
            '日期': parts[0],
            '开盘': float(parts[1]),
            '收盘': float(parts[2]),
            '最高': float(parts[3]),
            '最低': float(parts[4]),
            '成交量': float(parts[5]),
        })
    # 按基准日二次截断（接口的 end 参数对缺失交易日不总是可靠）
    rows, dropped_rows = _truncate_rows(rows, asof)
    if not rows:
        return [], None
    try:
        import pandas as pd
        df = pd.DataFrame(rows)
    except Exception:
        df = None
    last = rows[-1]
    out = [
        _rec('历史区间起始', rows[0]['日期'], '日期', '区间', 'eastmoney.http', rows[0]['日期']),
        _rec('历史区间结束', last['日期'], '日期', '区间', 'eastmoney.http', last['日期']),
        _rec('样本交易日数', len(rows), '天', '区间', 'eastmoney.http', last['日期']),
        _rec('区间最高价', max(r['最高'] for r in rows), '元', '区间', 'eastmoney.http', last['日期']),
        _rec('区间最低价', min(r['最低'] for r in rows), '元', '区间', 'eastmoney.http', last['日期']),
    ]
    if dropped_rows:
        out.append(_rec('基准日后剔除行数', dropped_rows, '行', '区间',
                        'pit:truncate', last['日期'],
                        note=f'晚于基准日 {getattr(asof, "iso", "")} 的行情行已剔除'))
    return out, df


# ---------------------------------------------------------------------------
# 衍生指标：估值分位 / 最大回撤（给估值员与风控员）
# ---------------------------------------------------------------------------

def compute_percentile(df, value_col='收盘'):
    """当前价在历史区间中的分位（0-100）。列名兼容中文与英文。"""
    try:
        col = _find_col(df, value_col, ('close', 'Close', 'CLOSE'))
        s = df[col].astype(float)
        cur = float(s.iloc[-1])
        return round(float((s < cur).sum()) / len(s) * 100, 2)
    except Exception:
        return None


def compute_max_drawdown(df, value_col='收盘'):
    """最大回撤（负值，如 -0.45 表示 -45%）与回撤发生区间。列名兼容中英文。"""
    try:
        col = _find_col(df, value_col, ('close', 'Close', 'CLOSE'))
        date_col = _find_col(df, '日期', ('date', 'Date', 'DATE'))
        s = df[col].astype(float)
        peak = s.cummax()
        dd = (s - peak) / peak
        mdd = float(dd.min())
        idx = int(dd.idxmin())
        peak_idx = int(s.loc[:idx].idxmax())
        return {
            '最大回撤': round(mdd, 4),
            '回撤起点日期': str(df.loc[peak_idx, date_col])[:10],
            '回撤谷底日期': str(df.loc[idx, date_col])[:10],
            '回撤起点价': round(float(s.loc[peak_idx]), 4),
            '回撤谷底价': round(float(s.loc[idx]), 4),
            '样本长度': int(len(s)),
            '样本起始日': str(df.loc[0, date_col])[:10],
            '样本结束日': str(df.loc[-1, date_col])[:10],
        }
    except Exception:
        return None


def _find_col(df, prefer, alternatives):
    """按中英文候选名找列。找不到则返回第一个看起来像数值的列。"""
    cols = list(df.columns)
    for name in (prefer,) + tuple(alternatives):
        for c in cols:
            if str(c).strip().lower() == name.lower():
                return c
    raise KeyError(f'no column matching {prefer} / {alternatives}')


# ---------------------------------------------------------------------------
# 时点截断辅助
# ---------------------------------------------------------------------------

def _truncate_rows(rows, asof):
    """按基准日截断 dict 行列表。返回 (保留的行, 剔除的行数)。"""
    if asof is None or not getattr(asof, 'is_set', False):
        return rows, 0
    anchor = asof.as_of
    kept, dropped = [], 0
    for row in rows:
        d = parse_date(row.get('日期')) if parse_date else None
        if d is None or d <= anchor:
            kept.append(row)
        else:
            dropped += 1
    return kept, dropped


def _truncate_df(df, asof):
    """按基准日截断 DataFrame。返回 (保留的 df, 剔除的行数)。"""
    if asof is None or not getattr(asof, 'is_set', False):
        return df, 0
    anchor = asof.as_of
    keep_idx, dropped = [], 0
    for idx, row in df.iterrows():
        d = parse_date(row.get('日期')) if parse_date else None
        if d is None or d <= anchor:
            keep_idx.append(idx)
        else:
            dropped += 1
    if dropped and keep_idx:
        df = df.loc[keep_idx]
    return df, dropped


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--code', required=True, help='A股代码，如 600000')
    ap.add_argument('--out', required=True, help='输出 JSON 路径')
    ap.add_argument('--history-days', type=int, default=800)
    ap.add_argument('--as-of', dest='as_of', default=None,
                    help='分析基准日 YYYY-MM-DD：历史序列一律截断到该日，'
                         '基准日之后的行情不得进入任何计算窗口（时点纪律）')
    args = ap.parse_args()

    code = args.code.strip()
    asof = build_as_of(args.as_of) if build_as_of else None
    if args.as_of and (asof is None or not asof.is_set):
        print('[WARN] --as-of 格式无法解析（需 YYYY-MM-DD），本次不做时点截断。',
              file=sys.stderr)
    channels = []
    quote, hist = [], None
    hist_records = []

    if _try_akshare():
        try:
            quote = fetch_quote_akshare(code)
            channels.append('akshare:quote')
        except Exception as e:
            quote = []
            channels.append(f'akshare:quote:FAILED({type(e).__name__})')
        try:
            hist_records, hist = fetch_history_akshare(code, args.history_days, asof)
            channels.append('akshare:history')
        except Exception as e:
            hist_records, hist = [], None
            channels.append(f'akshare:history:FAILED({type(e).__name__})')

    if not quote:
        try:
            quote = fetch_quote_http(code)
            channels.append('http:quote(fallback)')
        except Exception as e:
            channels.append(f'http:quote:FAILED({type(e).__name__})')
    if hist is None:
        try:
            hist_records, hist = fetch_history_http(code, args.history_days, asof)
            channels.append('http:history(fallback)')
        except Exception as e:
            channels.append(f'http:history:FAILED({type(e).__name__})')

    # 衍生指标（仅在有历史数据时计算）
    derived = []
    if hist is not None and len(hist) > 0:
        pct = compute_percentile(hist)
        if pct is not None:
            note = f'基于 {len(hist)} 个交易日收盘价'
            if asof is not None and asof.is_set:
                note += f'；样本区间终点 {str(hist.iloc[-1]["日期"])[:10]}（基准日 {asof.iso}）'
            derived.append(_rec('价格历史分位', pct, '%', '区间',
                                'derived:compute_percentile',
                                str(hist.iloc[-1]['日期'])[:10],
                                note=note))
        mdd = compute_max_drawdown(hist)
        if mdd:
            derived.append(_rec('最大回撤', mdd['最大回撤'], '比率', '区间',
                                'derived:compute_max_drawdown',
                                mdd['回撤谷底日期'],
                                note=f"{mdd['回撤起点日期']}→{mdd['回撤谷底日期']}, "
                                     f"{mdd['回撤起点价']}→{mdd['回撤谷底价']}"))

    records = quote + hist_records + derived
    payload = {
        '标的': code,
        '取数时间': _now(),
        '分析基准日': (asof.iso if asof is not None and asof.is_set
                       else datetime.now().strftime('%Y-%m-%d')),
        '时点截断': bool(asof is not None and asof.is_set),
        '通道': channels,
        '记录数': len(records),
        '空值数': sum(1 for r in records if r['值'] is None),
        'stale数': sum(1 for r in records if r.get('stale')),
        '数据': records,
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # 取数全失败 → 必须让调用方感知，绝不能带着空数据静默继续
    if not records:
        print('[FATAL] 全部通道取数失败，未获得任何数据。'
              '不得用估算填补，请在报告「数据缺口」中如实列出。',
              file=sys.stderr)
        print(json.dumps({k: v for k, v in payload.items() if k != '数据'},
                         ensure_ascii=False, indent=2))
        return 1

    print(json.dumps({k: v for k, v in payload.items() if k != '数据'},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
