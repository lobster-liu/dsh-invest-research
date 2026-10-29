#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
pit.py —— 时点（point-in-time）纪律的共用底座

存在理由
--------
本插件此前只做了「披露滞后标注」（报告期 vs 检索于、stale 标记），
**没有做时点纪律**：所有历史序列一律取到「当下」，
所有财报一律取「最新版」，因此一份声称基准日为 2026-06-30 的报告，
只要用了这些工具产出的数据，就会静默地把 7—10 月的行情、后来重述的财报、
以及基准日之后才披露的持仓算进结论。这是典型的**前视偏差（look-ahead bias）**。

本模块提供四件套：
  1. `AsOf` —— 基准日上下文（as-of date + 披露滞后规则）；
  2. `disclosure_date()` —— 由「报告期 + 披露类型」推算**最早公开日**；
  3. `is_visible()` —— 判断某条数据在基准日是否**已公开**（可见性判定）；
  4. `truncate_series()` —— 把序列截断到基准日。

设计原则（对齐上游 TradingAgents 的 PIT 机制）：
  - **披露日期与数据日期必须分列**：数据日期是统计截止，披露日期是公众首次可读之日。
    两者混为一谈，重述就不可见。
  - **取不到披露日期就写「未取得」，不得用「报告期 + 推算天数」冒充实际披露日期**；
    推算值只能进备注并标明「推算」。
  - **推算披露日用「报告期 + 监管最晚披露时限」而非「典型披露日」**：
    监管要求是「不晚于」，实际披露通常更早，所以用最晚时限算出的日期是**保守**的，
    即宁可认为数据更晚可见，也不误判为基准日已可见。这是刻意的保守方向。
"""

import re
from datetime import datetime, timedelta

# 披露类型 → 监管最晚披露时限（自然日）
#   季报：季度结束后 15 个工作日 ≈ 21 自然日（保守取 25）
#   半年报：上半年结束后 2 个月 ≈ 60 自然日
#   年报：会计年度结束后 3 个月 ≈ 90 自然日
#   一季报：同季报口径
DISCLOSURE_LAG_DAYS = {
    '季报': 25,
    '一季报': 25,
    '三季报': 25,
    '季报前十大': 25,
    '半年报': 60,
    '中期': 60,
    '年报': 90,
    '年度': 90,
}

# 未标注披露类型时的兜底滞后（按季度处理，保守）
DEFAULT_LAG_DAYS = 25

# '未取得' —— 披露日期取不到时的占位符。
# 刻意不用 None：None 在 JSON 里会变成 null，下游容易把它当成「没有日期限制」。
UNAVAILABLE = '未取得'


def parse_date(value):
    """把各种日期写法解析成 ``datetime.date``；解析不了返回 None。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text or text in (UNAVAILABLE, 'None', 'null'):
        return None
    text = text.replace('/', '-')
    m = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})', text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
        except ValueError:
            return None
    m = re.match(r'^(\d{4})-(\d{1,2})$', text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), 1).date()
        except ValueError:
            return None
    m = re.match(r'^(\d{4})(\d{2})(\d{2})$', text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
        except ValueError:
            return None
    return None


def quarter_end(d):
    """给定日期所属季度的季度末日期。"""
    y = d.year
    q = (d.month - 1) // 3 + 1
    return datetime(y, q * 3, 1).date() + timedelta(days=31)


def disclosure_date(report_period, disclose_type=None, lag_days=None):
    """由「报告期 + 披露类型」推算**最早公开日**（保守上界）。

    参数：
      report_period —— 报告期/统计截止日（各种写法都可）。
      disclose_type —— 季报 / 半年报 / 年报 等；None 走默认滞后。
      lag_days      —— 显式指定滞后天数，优先于 disclose_type。

    返回 ``'YYYY-MM-DD'`` 字符串；report_period 解析不了时返回 ``UNAVAILABLE``。

    注意：返回值是**推算值**，调用方必须标明「推算」，不得当作实际披露日期。
    """
    d = parse_date(report_period)
    if d is None:
        return UNAVAILABLE
    if lag_days is None:
        key = str(disclose_type or '').strip()
        lag_days = DISCLOSURE_LAG_DAYS.get(key, DEFAULT_LAG_DAYS)
    return (d + timedelta(days=int(lag_days))).strftime('%Y-%m-%d')


def days_between(a, b):
    """两个日期之间的天数差（b - a）；任一解析不了返回 None。"""
    da, db = parse_date(a), parse_date(b)
    if da is None or db is None:
        return None
    return (db - da).days


class AsOf:
    """一次运行的时点上下文。

    用法::

        asof = AsOf('2026-06-30')
        asof.visible(report_period='2026-03-31', disclose_type='季报')
        asof.truncate(dates)          # 只保留 <= 基准日
    """

    def __init__(self, as_of=None):
        self.as_of = parse_date(as_of)
        self.raw = as_of

    # -- 基本属性 ---------------------------------------------------------
    @property
    def is_set(self):
        """是否显式指定了基准日。未指定时不做任何截断（保持旧行为）。"""
        return self.as_of is not None

    @property
    def iso(self):
        return self.as_of.strftime('%Y-%m-%d') if self.as_of else None

    # -- 可见性判定 --------------------------------------------------------
    def visible(self, report_period, disclose_type=None, lag_days=None):
        """该报告期的数据在基准日**是否已公开**。

        - 未设基准日 → 一律 True（不改变旧行为）。
        - 报告期晚于基准日 → False（基准日之后才存在的统计期，不可能已公开）。
        - 推算最早公开日晚于基准日 → False。
        - 报告期/披露类型取不到 → **保守判 False**，并由调用方记为数据缺口。
          宁可少一条数据，也不要让一条来路不明的数字进结论。
        """
        if not self.is_set:
            return True
        period = parse_date(report_period)
        if period is None:
            return False
        if period > self.as_of:
            return False
        earliest = disclosure_date(report_period, disclose_type, lag_days)
        earliest_d = parse_date(earliest)
        if earliest_d is None:
            # 披露日期取不到：保守判不可见。
            return False
        return earliest_d <= self.as_of

    def note_for(self, report_period, disclose_type=None, lag_days=None):
        """生成写入记录的披露日期备注（标明推算）。"""
        earliest = disclosure_date(report_period, disclose_type, lag_days)
        if earliest == UNAVAILABLE:
            return '披露日期未取得'
        return '披露日期 %s（推算：报告期 + %d 日）' % (
            earliest,
            lag_days if lag_days is not None
            else DISCLOSURE_LAG_DAYS.get(str(disclose_type or '').strip(), DEFAULT_LAG_DAYS),
        )

    # -- 序列截断 ---------------------------------------------------------
    def truncate(self, rows, date_key='日期'):
        """把序列截断到基准日（保留 <= 基准日的行）。

        rows 可以是 dict 列表、(日期, 数值) 元组列表，或 pandas DataFrame。
        `date_key` 指定日期字段名；传 0 表示「元组的第 0 项是日期」。
        返回 ``(截断后的对象, 被剔除的条数)``。
        """
        if not self.is_set or not rows:
            return rows, 0
        # DataFrame 路径
        if hasattr(rows, 'columns') and hasattr(rows, 'loc'):
            if date_key not in rows.columns:
                return rows, 0
            mask = rows[date_key].map(lambda v: (parse_date(v) is not None
                                                 and parse_date(v) <= self.as_of))
            dropped = int((~mask).sum())
            return rows[mask], dropped
        # dict / 元组列表路径
        kept, dropped = [], 0
        for row in rows:
            if isinstance(row, dict):
                value = row.get(date_key)
            elif isinstance(row, (list, tuple)) and isinstance(date_key, int):
                value = row[date_key] if len(row) > date_key else None
            else:
                value = None
            d = parse_date(value)
            if d is None or d <= self.as_of:
                kept.append(row)
            else:
                dropped += 1
        return kept, dropped


def build_as_of(arg_value):
    """从命令行参数构造 AsOf；未给或格式不对时返回未设定的实例。"""
    if not arg_value:
        return AsOf(None)
    if parse_date(arg_value) is None:
        return AsOf(None)
    return AsOf(arg_value)
