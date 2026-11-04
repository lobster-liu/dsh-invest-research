#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
fund_cost.py — 基金销售费用「净成本」的口径校验（2026 新规）

规则原文与证据分级见 `assets/skills/_shared/references/fee-rules-2026.md`：
  · 规范层（原文级）：证监会公告〔2025〕22号，2025-12-31 发布，2026-01-01 施行
  · 执行层（转述级，无文号）：配套《通知》下发至机构，2027-01-01 起
    认（申）购费停收、销售服务费先收后返、存量不返还

本模块只做一件事：把「渠道 × 申购时点 × 口径」三维输入校验成可落盘的净成本。
不合规就抛 `CostCaliberError` —— 宁可报错，不可算出一个看起来正常的数。
它**不查费率、不联网、不猜数据**：金额由调用方从公告/合同/披露字段取，本模块只判口径。

费用种类只接两类，理由：
  · 认（申）购费 —— 第七条（直销不得收取）/ 2027 过渡（停收，无返还机制）
  · 销售服务费 —— 第十一条上限 + 2027 过渡（先收后返，净成本 0 但现金流不为 0）
管理费/托管费已从净值中扣除，不重复计入；赎回费全额计入基金财产，不进 A/C 净成本对比。

已知边界（fee-rules-2026.md §7）：持有期决定「先收后返」是否适用——**直销腿不问持有期**，2027-01-01 及
以后一律要求「应退 = 实收」；**代销腿必须给 `holding_days`**：持有 ≤365 天的部分「全部确认为应支付」、
不返还（净成本 = 实收），持有 >365 天的部分才把 2027-01-01 起计提的费用全额返还。该分支的原文依据是
**单例合同公告**（路博迈中国动力 2026-07-06，另有同向个案），不是《通知》原文，所以：只能按「合同已声明
这一形态」建模，不得当成全部代销基金的默认行为。
"""
from datetime import datetime, timedelta

#: 规范层生效日（〔2025〕22号第二十九条）
REGULATION_EFFECTIVE = '2026-01-01'
#: 执行层生效日（配套《通知》，转述级，无文号）
NOTICE_EFFECTIVE = '2027-01-01'
#: 渠道：直销 = 基金管理人及其销售子公司；代销 = 其他销售机构
CHANNELS = ('直销', '代销')
#: 可校验的费用种类
FEE_KINDS = ('认申购费', '销售服务费')
#: 规则/费率未核到时的结论短语（E7）：禁止估算
UNVERIFIED = '费用不可精确复算'
#: 代销腿「先收后返」的持有期分界（连续持有天数，含当日）——合同分支，见 §2 第 3 条
REFUND_MIN_HOLDING_DAYS = 365
_EPS = 1e-9


class CostCaliberError(ValueError):
    """费用口径不可用（对应 fee-rules-2026.md §5 的 E1–E7）。"""

    def __init__(self, code, message):
        super(CostCaliberError, self).__init__('[%s] %s' % (code, message))
        self.code = code


def _date(value):
    try:
        return datetime.strptime(str(value)[:10], '%Y-%m-%d')
    except (TypeError, ValueError):
        raise CostCaliberError('E7', '日期不可解析：%r（须 YYYY-MM-DD）' % (value,))


def _amount(value, what):
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise CostCaliberError('E7', '%s 缺少数值：%r' % (what, value))
    if f < 0:
        raise CostCaliberError('E7', '%s 不得为负：%r' % (what, value))
    return f


def _iso(d):
    return d.strftime('%Y-%m-%d')


def _days(value):
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        raise CostCaliberError('E7', '持有期缺少数值：%r（须按天计）' % (value,))
    if n < 0:
        raise CostCaliberError('E7', '持有期不得为负：%r' % (value,))
    return n


def in_transition(on_date):
    """是否进入执行层区间（>= 2027-01-01）。"""
    return _date(on_date) >= _date(NOTICE_EFFECTIVE)


def split_holding_period(start, end):
    """持有期按 2027-01-01 切分 → [(起, 止, 日历天数)]；未跨期时返回单段。

    跨 2027-01-01 的持有期必须分段：前段按存量（不返还），后段按先收后返。
    """
    s, e = _date(start), _date(end)
    if e < s:
        raise CostCaliberError('E7', '持有期结束早于开始：%s→%s' % (start, end))
    notice = _date(NOTICE_EFFECTIVE)
    if s >= notice or e < notice:
        return [(_iso(s), _iso(e), (e - s).days)]
    pre_end = notice - timedelta(days=1)
    return [(_iso(s), _iso(pre_end), (pre_end - s).days),
            (_iso(notice), _iso(e), (e - notice).days)]


def fee_version_key(fund_code, effective_date):
    """费率版本键 = (基金代码, 费率变更生效日)。

    同一只基金在 2026 年内可能有两个费率版本；拿「最新费率」回算历史持有成本是错的。
    """
    code = str(fund_code or '').strip()
    if not code:
        raise CostCaliberError('E7', '基金代码为空，无法建立费率版本键')
    return (code, _iso(_date(effective_date)))


def validate_fee_leg(channel, trade_date, fee_kind, received, refundable=None, holding_days=None):
    """校验一条费用腿 → {渠道, 费用种类, 发生日, 实收, 应退, 净成本, 口径}。

    `received` / `refundable` 是以金额计的实际收取与应返（同币种、同期间）。
    销售服务费在 2027-01-01 及以后**必须同时给出应退**（E2）；
    **代销腿还必须给 `holding_days`**（赎回时的连续持有天数）：
      · ≤365 天：所计提的销售服务费「全部确认为应支付」，应退必须为 0（否则 E3），净成本 = 实收；
      · >365 天：2027-01-01 起计提的部分全额返还，应退必须 = 实收（否则 E3），净成本 = 0。
    直销腿不问持有期，2027 起一律要求应退 = 实收（E3）。2027 之前给出应退即违反「存量不返还」（E7）。
    """
    if channel not in CHANNELS:
        raise CostCaliberError('E7', '渠道必须是 %s 之一，收到 %r' % ('/'.join(CHANNELS), channel))
    if fee_kind not in FEE_KINDS:
        raise CostCaliberError('E7', '费用种类必须是 %s 之一，收到 %r'
                               % ('/'.join(FEE_KINDS), fee_kind))
    d = _date(trade_date)
    rec = _amount(received, '实收')

    if fee_kind == '认申购费':
        if channel == '直销' and d >= _date(NOTICE_EFFECTIVE) and rec > _EPS:
            raise CostCaliberError(
                'E1', '直销腿 %s 收取认（申）购费 %.6f：2027-01-01 起不得继续收取'
                % (_iso(d), rec))
        if refundable is not None and _amount(refundable, '应退') > _EPS:
            raise CostCaliberError('E7', '认（申）购费没有返还机制，应退必须为 0 或不填')
        return {'渠道': channel, '费用种类': fee_kind, '发生日': _iso(d),
                '实收': rec, '应退': 0.0, '净成本': rec,
                '口径': '实收（2027 起直销腿为 0；代销腿受第八条上限约束）'}

    # 销售服务费
    if refundable is None:
        if d >= _date(NOTICE_EFFECTIVE):
            raise CostCaliberError('E2', '销售服务费 %s 只给实收、未给应退：2027 起两列必须同时给'
                                   % _iso(d))
        ref = 0.0          # 2027 年前的存量本身没有应退
    else:
        ref = _amount(refundable, '应退')
    if d >= _date(NOTICE_EFFECTIVE):
        tol = max(_EPS, abs(rec) * 1e-9)
        if channel == '代销':
            if holding_days is None:
                raise CostCaliberError(
                    'E7', '%s 代销腿销售服务费缺持有期（holding_days）：≤365 天不返还、>365 天返还，'
                          '缺了分支不可判' % _iso(d))
            hd = _days(holding_days)
            if hd <= REFUND_MIN_HOLDING_DAYS:
                if ref > tol:
                    raise CostCaliberError(
                        'E3', '%s 代销腿持有 %d 天（≤%d）：所计提的销售服务费全部确认为应支付，'
                              '应退必须为 0，收到 %.6f' % (_iso(d), hd, REFUND_MIN_HOLDING_DAYS, ref))
                return {'渠道': channel, '费用种类': fee_kind, '发生日': _iso(d),
                        '实收': rec, '应退': 0.0, '净成本': rec,
                        '口径': '代销持有 ≤%d 天：全部确认为应支付，不返还（净成本 = 实收；合同分支）'
                                % REFUND_MIN_HOLDING_DAYS}
            if abs(ref - rec) > tol:
                raise CostCaliberError(
                    'E3', '%s 代销腿持有 %d 天（>%d）：2027-01-01 起继续计提的部分应全额返还，'
                          '应退 %.6f ≠ 实收 %.6f' % (_iso(d), hd, REFUND_MIN_HOLDING_DAYS, ref, rec))
            return {'渠道': channel, '费用种类': fee_kind, '发生日': _iso(d),
                    '实收': rec, '应退': ref, '净成本': 0.0,
                    '口径': '先收后返（代销持有 >%d 天）：净成本 0，现金流不为 0（两列并存）'
                            % REFUND_MIN_HOLDING_DAYS}
        if abs(ref - rec) > tol:      # 直销：不问持有期
            raise CostCaliberError(
                'E3', '%s 销售服务费应退 %.6f ≠ 实收 %.6f：执行层要求全额返还（直销腿不问持有期）'
                % (_iso(d), ref, rec))
        return {'渠道': channel, '费用种类': fee_kind, '发生日': _iso(d),
                '实收': rec, '应退': ref, '净成本': 0.0,
                '口径': '先收后返：净成本 0，现金流不为 0（两列并存）'}
    if ref > _EPS:
        raise CostCaliberError('E7', '%s 销售服务费不应有应退 %.6f：2027-01-01 前计提的存量不返还'
                               % (_iso(d), ref))
    return {'渠道': channel, '费用种类': fee_kind, '发生日': _iso(d),
            '实收': rec, '应退': 0.0, '净成本': rec,
            '口径': '实收（存量，不返还）'}


def validate_holding_window(start, end, legs):
    """持有期跨 2027-01-01 时必须已分段（E4）→ 返回分段列表。

    `legs` 为 `validate_fee_leg` 的结果（或任何含「发生日」的字典）。
    """
    segments = split_holding_period(start, end)
    if len(segments) == 1:
        return segments
    notice = _date(NOTICE_EFFECTIVE)
    if not any(_date((leg or {}).get('发生日')) >= notice for leg in legs or []):
        raise CostCaliberError('E4', '持有期 %s→%s 跨 2027-01-01，必须分段：缺 2027 年后的费用腿'
                               % (start, end))
    return segments


def net_cost(legs):
    """各腿净成本之和（管理费/托管费/赎回费不在内，见模块说明）。"""
    return sum(_amount((leg or {}).get('净成本'), '净成本') for leg in legs or [])


def unverified_note(reason=None):
    """E7 的降级结论：宁写「费用不可精确复算」，不估算。"""
    tail = ('：%s' % reason) if reason else ''
    return UNVERIFIED + tail
