#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
test_fund_tools.py — fund-research 工具离线自检（SKILL.md「验证安装」第 2 步）

离线自测 fetch_fund.py 的纯函数契约：数值/文本解析、陈旧判定、份额类别、基准解析、
代码归一、f10 持仓与行业解析、区间/年化/回撤/分位/基准对比等衍生指标。
fixture 全部内联（不读外部文件）；把 ff._fetch 换成只喂 fixture 的离线桩，
并对 build_payload / main 设绊线（调用即记录）——全程不发一次网络请求。

在线取数冒烟见 SKILL.md 第 1 步（python fetch_fund.py --code <代码> --out ...）。
与直觉不一致处按 fetch_fund 实际实现断言（边界值已固定，改实现时须同步改这里）：
  1. _calc_stale(90 天前, '季度')=False：季度阈值 130 日历日，月度才是 45 天。
  2. infer_share_class('某某ETF')=None：排除缩写末位大写字母（ETF/QDII/FOF）。
  3. _percentile([1..5], 当前=5)=80.0：口径是「严格小于当前值的样本占比」。
  4. resolve_benchmark 中文名走精确匹配（'沪深300' 可，'沪深 300' 不可）。

用法: python test_fund_tools.py
退出码: 0 = 全部通过；1 = 有失败（修好前勿用于正式流水线）
"""
import json
import os
import shutil
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import fetch_fund as ff
except Exception as e:
    print('[FAIL] cannot import fetch_fund:', e)
    sys.exit(1)

TOTAL = 0
FAILS = []
TODAY = datetime.now().strftime('%Y-%m-%d')
_d = lambda days: (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')


def check(name, ok, got=None):
    global TOTAL
    TOTAL += 1
    print('%s %s' % ('PASS' if ok else 'FAIL', name))
    if not ok:
        FAILS.append('%s -> got %r' % (name, got))


def eq(name, got, want):
    check(name, got == want, got)


def near(name, got, want, tol=1e-6):
    check(name, got is not None and abs(got - want) <= tol, got)


# ---------- 1. 基础解析 ----------
eq('_num "9.06%"->9.06 / "1,234.5"->1234.5（去 % 与千分位，不折成小数）',
   (ff._num('9.06%'), ff._num('1,234.5')), (9.06, 1234.5))
eq('_num "--"/""/"暂无"/None -> None',
   tuple(ff._num(v) for v in ('--', '', '暂无', None)), (None, None, None, None))
eq('_text 去标签/去实体/保留正文',
   (ff._text('<a>中国卫星</a>'), ff._text('&nbsp;abc&nbsp;'), ff._text('<td>9.06%</td>')),
   ('中国卫星', 'abc', '9.06%'))

# ---------- 2. 陈旧判定 / 行情时间 / 份额类别 / 基准 / 代码 ----------
eq('_calc_stale 今天·时点与净值日 -> False',
   (ff._calc_stale(TODAY, '时点'), ff._calc_stale(TODAY, '净值日')), (False, False))
eq('_calc_stale 季度阈值：130 天->False / 131 天->True / 200 天->True',
   (ff._calc_stale(_d(130), '季度'), ff._calc_stale(_d(131), '季度'), ff._calc_stale(_d(200), '季度')),
   (False, True, True))
eq('_calc_stale 90 天：季度->False（130 天阈值）/ 月度->True（45 天阈值）',
   (ff._calc_stale(_d(90), '季度'), ff._calc_stale(_d(90), '月度')), (False, True))
eq("_calc_stale 无法解析/''/None -> True（保守判陈旧）",
   tuple(ff._calc_stale(v, '季度') for v in ('2026/10/17', '', None)), (True, True, True))
eq('_qt_time_to_date 14 位/8 位 -> 2026-10-16；None/空 -> 当天',
   (ff._qt_time_to_date('20261016161438'), ff._qt_time_to_date('20261016'),
    ff._qt_time_to_date(None), ff._qt_time_to_date('')),
   ('2026-10-16', '2026-10-16', TODAY, TODAY))
eq('infer_share_class 指数A->A / C类->C / ETF->None（排除缩写末位大写字母）',
   (ff.infer_share_class('平安中证卫星产业指数A'), ff.infer_share_class('某某C类'),
    ff.infer_share_class('某某ETF')), ('A', 'C', None))
eq('resolve_benchmark sh000300 原样 / 沪深300 / 中证500 / 000300',
   (ff.resolve_benchmark('sh000300'), ff.resolve_benchmark('沪深300'),
    ff.resolve_benchmark('中证500'), ff.resolve_benchmark('000300')),
   ('sh000300', 'sh000300', 'sh000905', 'sh000300'))
eq('resolve_benchmark 未知名 -> None（不猜）', ff.resolve_benchmark('中证卫星产业'), None)
eq('stock_symbol 600118/000001 默认市场 + 显式 hint',
   (ff.stock_symbol('600118', None), ff.stock_symbol('000001', None), ff.stock_symbol('600118', 'sh')),
   ('sh600118', 'sz000001', 'sh600118'))
eq('_period_from_label 2季度/中期/年度/空',
   (ff._period_from_label('2026年2季度股票投资明细'), ff._period_from_label('2026年中期投资明细'),
    ff._period_from_label('2025年年度'), ff._period_from_label('')),
   (('2026-06-30', '季报前十大'), ('2026-06-30', '半年报'), ('2025-12-31', '年报'), (None, None)))

# ---------- 3. f10 持仓/行业解析（内联 HTML fixture + 离线桩） ----------
F10_STOCK = (
    'var apidata={ content:"'
    "<div class='box'><label class='left'>2026年2季度股票投资明细</label>"
    "<table><tr><td>1</td><td><a href='/r/1.600118'>中国卫星</a></td><td>600118</td>"
    "<td>9.06%</td><td>1234.5</td><td>5678.90</td></tr>"
    "<tr><td>2</td><td><a href='/r/0.000001'>平安银行</a></td><td>000001</td>"
    "<td>6.50%</td><td>200.0</td><td>300.00</td></tr></table></div>"
    "<div class='box'><label class='left'>2025年年度股票投资明细</label>"
    "<table><tr><td>1</td><td><a href='/r/1.601318'>中国平安</a></td><td>601318</td>"
    "<td>5.00%</td><td>88.0</td><td>99.00</td></tr></table></div>"
    '",arryear:[2026,2025],curyear:2026};')
F10_IND = (
    'var apidata={ content:"'
    "<div class='box'><label class='left'>2026年2季度行业投资明细</label>"
    "<table><tr><td>1</td><td>制造业</td><td>9.06%</td><td>1234.5</td></tr>"
    "<tr><td>2</td><td>金融业</td><td>3.20%</td><td>456.7</td></tr></table></div>"
    '",arryear:[2026],curyear:2026};')

NET = []
TRIP = []
_ORIG_FETCH = ff._fetch
_ORIG_FN = {n: getattr(ff, n) for n in ('build_payload', 'main') if hasattr(ff, n)}


def _offline_fetch(url, **kw):
    """离线桩：只回答 f10 fixture；其它 URL 一律断言失败，保证本脚本不触网。"""
    NET.append(url)
    for key, html in (('type=jjcc', F10_STOCK), ('type=hydb', F10_IND)):
        if key in url:
            return html
    raise AssertionError('offline test touched network: %s' % url)


for _n in _ORIG_FN:
    setattr(ff, _n, lambda *a, _n=_n, **k: TRIP.append(_n))
ff._fetch = _offline_fetch

hold = ff.parse_f10_holdings(ff.fetch_f10('025490', [], 'jjcc'))
ind = ff.parse_f10_industry(ff.fetch_f10('025490', [], 'hydb'))

eq('parse_f10_holdings 期数=2；第1期 报告期/披露类型/条数',
   (len(hold), hold[0]['报告期'], hold[0]['披露类型'], hold[0]['明细条数']),
   (2, '2026-06-30', '季报前十大', 2))
eq('parse_f10_holdings 第1期 两只的 代码/名称/占净值比',
   tuple(tuple(r[k] for k in ('代码', '名称', '占净值比%')) for r in hold[0]['股票']),
   (('600118', '中国卫星', 9.06), ('000001', '平安银行', 6.5)))
eq('parse_f10_holdings 第2期(年报) 报告期/名称/占比',
   (hold[1]['报告期'], hold[1]['股票'][0]['名称'], hold[1]['股票'][0]['占净值比%']),
   ('2025-12-31', '中国平安', 5.0))
eq('parse_f10_industry 期数=1；行业/占净值比',
   (len(ind), tuple((r['行业'], r['占净值比%']) for r in ind[0]['行业'])),
   (1, (('制造业', 9.06), ('金融业', 3.2))))
eq('离线边界：网络层仅被 fixture 借用 2 次', len(NET), 2)
eq('离线边界：build_payload/main 一次都没被调用', TRIP, [])

ff._fetch = _ORIG_FETCH
for _n, _orig in _ORIG_FN.items():
    setattr(ff, _n, _orig)

# ---------- 4. 衍生指标 ----------
S3 = [('2026-01-01', 1.0), ('2026-01-02', 1.1), ('2026-01-03', 1.21)]
eq('_window_return n=2 / n=5 超样本退化 -> 0.21；样本<2 -> None',
   (round(ff._window_return(S3, 2), 6), round(ff._window_return(S3, 5), 6),
    ff._window_return([('2026-01-01', 1.0)], 1)), (0.21, 0.21, None))
eq('_ytd_return 取同年首个净值点 1.5/1.2-1 -> 0.25',
   round(ff._ytd_return([('2025-12-31', 1.0), ('2026-01-05', 1.2), ('2026-01-06', 1.5)]), 6), 0.25)
mdd = ff._max_drawdown([('d1', 1.0), ('d2', 2.0), ('d3', 1.0)])
eq('_max_drawdown 1.0->2.0->1.0 = -0.5，起点 d2 / 谷底 d3',
   (mdd['最大回撤'], mdd['回撤起点日期'], mdd['回撤谷底日期']), (-0.5, 'd2', 'd3'))
eq('_percentile 升序[1..5]当前=5 -> 80.0（严格小于占比）；降序 -> 0.0',
   (ff._percentile([('d%d' % i, i) for i in range(1, 6)]),
    ff._percentile([('d%d' % i, 6 - i) for i in range(1, 6)])), (80.0, 0.0))
near('_annualized 244 日翻倍 -> 1.0',
     ff._annualized([('d%03d' % i, 1.0 if i == 0 else 2.0) for i in range(245)], 244), 1.0)

# ---------- 5. 基准对比（日期对齐，21 个共同交易日） ----------
FD = ['2026-01-%02d' % i for i in range(1, 22)]
FUND = [(d, 1.0 + i * 0.005) for i, d in enumerate(FD)]      # 1.00 -> 1.10 (+10%)
BENCH = [(d, 100.0 + i * 0.25) for i, d in enumerate(FD)]    # 100 -> 105 (+5%)
cb = ff.compare_with_benchmark(FUND, BENCH)
eq('compare_with_benchmark 可用=True / 可比样本数=21', (cb['可用'], cb['可比样本数']), (True, 21))
eq('compare_with_benchmark 区间收益 基金+0.10 / 基准+0.05',
   (cb['基金区间收益'], cb['基准区间收益']), (0.1, 0.05))
near('compare_with_benchmark 区间超额 = +0.05（跑赢）', cb['区间超额收益'], 0.05)
check('compare_with_benchmark 年化跟踪误差 > 0', (cb['年化跟踪误差'] or 0) > 0, cb['年化跟踪误差'])
under = ff.compare_with_benchmark(FUND, [(d, 100.0 + i * 1.0) for i, d in enumerate(FD)])
near('compare_with_benchmark 跑输时超额 = -0.10（符号正确）', under['区间超额收益'], -0.10)
eq('compare_with_benchmark 共同交易日<20 -> 可用=False',
   ff.compare_with_benchmark(FUND[:5], BENCH[:5])['可用'], False)

# ---------- 6. 版本解析（_resolve_version：回落值 / 清单身份 / 插件根标记） ----------
check('VERSION 已对齐当前插件版本（不再滞后 0.3.0）',
      ff.VERSION == ff._VERSION_FALLBACK and ff.VERSION != '0.3.0',
      (ff.VERSION, ff._VERSION_FALLBACK))


def _pkg_version(start=None):
    """插件版本真值：向上找 `.qoder-plugin/plugin.json` →
    带 `assets/` 标记的 `name=='dsh-invest-research'` package.json；都没有返回 None。

    **跨安装形态可跑**：Qoder 等把 `skills/fund-research/tools` 独立安装时，
    上面没有仓库根 package.json，不能写死 `HERE/../../../..`。返回 None 时
    对应断言跳过（不影响运行时代码）。`start` 仅用于测试注入。
    """
    here = start or HERE
    for _ in range(6):
        # Qoder 插件根标记：.qoder-plugin/plugin.json
        qp = os.path.join(here, '.qoder-plugin', 'plugin.json')
        if os.path.isfile(qp):
            try:
                with open(qp, encoding='utf-8') as fh:
                    v = json.load(fh).get('version')
                if v:
                    return v
            except Exception:
                pass
        # 本插件根：name 匹配 + assets/ 标记
        if os.path.isdir(os.path.join(here, 'assets')):
            pj = os.path.join(here, 'package.json')
            if os.path.isfile(pj):
                try:
                    with open(pj, encoding='utf-8') as fh:
                        pkg = json.load(fh)
                    if pkg.get('name') == 'dsh-invest-research':
                        v = pkg.get('version')
                        if v:
                            return v
                except Exception:
                    pass
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    return None


_pkg_v = _pkg_version()
if _pkg_v is None:
    # 非仓库/无清单布局：跳过同步断言，测试自身仍可跑
    print('SKIP _VERSION_FALLBACK 与插件清单版本同步（未找到插件清单，跨安装形态）')
else:
    check('_VERSION_FALLBACK 与 package.json.version 同步（防人肉抬值脱节）',
          ff._VERSION_FALLBACK == _pkg_v, (ff._VERSION_FALLBACK, _pkg_v))

_vtmp = os.path.join(os.path.abspath(os.environ.get('FR_TEST_TMPDIR') or '.'),
                     'fr_ver_%d' % os.getpid())
os.makedirs(_vtmp, exist_ok=True)
try:
    # 无关 package.json（name 不匹配）不得被采用
    _other = os.path.join(_vtmp, 'otherproj')
    os.makedirs(_other)
    with open(os.path.join(_other, 'package.json'), 'w', encoding='utf-8') as _f:
        json.dump({'name': 'some-other-project', 'version': '9.9.9'}, _f)
    got = ff._resolve_version(start=_other)
    check('_resolve_version 忽略 name 不匹配的无关 package.json',
          got == ff._VERSION_FALLBACK, got)
    # name 匹配但**没有 assets 子目录**（非插件根）也不得被采用
    _noassets = os.path.join(_vtmp, 'samename-noassets')
    os.makedirs(_noassets)
    with open(os.path.join(_noassets, 'package.json'), 'w', encoding='utf-8') as _f:
        json.dump({'name': 'dsh-invest-research', 'version': '7.7.7'}, _f)
    got_na = ff._resolve_version(start=_noassets)
    check('_resolve_version 要求目录下存在 assets/（插件根标记），否则不认',
          got_na == ff._VERSION_FALLBACK, got_na)
    # 本插件根（name 匹配 + assets/ 存在）应被采用
    _self = os.path.join(_vtmp, 'dsh-invest-research')
    os.makedirs(os.path.join(_self, 'assets'))
    with open(os.path.join(_self, 'package.json'), 'w', encoding='utf-8') as _f:
        json.dump({'name': 'dsh-invest-research', 'version': '8.8.8'}, _f)
    got2 = ff._resolve_version(start=_self)
    check('_resolve_version 采用 name 匹配且带 assets/ 的插件根 package.json',
          got2 == '8.8.8', got2)
    # _pkg_version 跨安装形态：Qoder 布局认 .qoder-plugin/plugin.json
    _qoder = os.path.join(_vtmp, 'qoder-root')
    os.makedirs(os.path.join(_qoder, '.qoder-plugin'))
    with open(os.path.join(_qoder, '.qoder-plugin', 'plugin.json'),
              'w', encoding='utf-8') as _f:
        json.dump({'name': 'dsh-invest-research', 'version': '6.6.6'}, _f)
    got3 = _pkg_version(start=_qoder)
    check('_pkg_version 认 Qoder 布局的 .qoder-plugin/plugin.json',
          got3 == '6.6.6', got3)
    # _pkg_version 找不到任何清单时返回 None（断言可跳过，不炸）
    _nm = os.path.join(_vtmp, 'nomanifest')
    os.makedirs(_nm)
    check('_pkg_version 无清单时返回 None（跨安装形态可跑）',
          _pkg_version(start=_nm) is None, _pkg_version(start=_nm))
finally:
    shutil.rmtree(_vtmp, ignore_errors=True)

for f in FAILS:
    print('  FAIL', f)
print('%d/%d passed' % (TOTAL - len(FAILS), TOTAL))
sys.exit(0 if not FAILS else 1)
