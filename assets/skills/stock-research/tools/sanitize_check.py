#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
行情报告脱敏门禁 —— 落盘前的最后一道闸

两道检查：
  A. 复用工作区已有的 audit-secrets.py（28 规则 + 高熵兜底，输出强制脱敏）
     —— 拦截密钥、Token、Bearer、私钥等凭据
  B. 行情报告专用 PII 规则（本文件）
     —— 拦截个人持仓、成本价、资金规模、账号等

设计原则：
  1. **失败即拒绝**：任何命中 → 退出码 1，调用方必须拒绝写入。
  2. **输出脱敏**：只显示前 4 + 后 2 + 长度，绝不把明文写进终端或报告。
  3. **零误报容忍度可调**：--strict 下 MEDIUM 也拦截。

用法：
  python sanitize_check.py <file-or-dir> [--strict] [--json]

退出码：
  0 = 通过（可落盘）
  1 = 发现敏感内容（禁止落盘）
  2 = 用法错误 / 目标不存在
"""

import argparse
import json
import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
# Optional external credential scanner (e.g. a Vault audit tool).
# Default absent -> explicitly 'skipped'; built-in PII rules still run.
# Enable via env: EQUITY_SECRET_SCANNER=/path/to/audit-secrets.py

# ---------------------------------------------------------------------------
# 个人持仓 PII 规则
#    严重度：CRITICAL=直接暴露个人头寸/资金  HIGH=强关联个人  MEDIUM=需留意
# ⚠️ 设计约束（2026-10-15 实测教训，改规则前必读）：
#    1. 不得把「政策条款数字」当个人资金 —— 「单户上限100万元」「本金年化1个百分点」
#       是公开政策参数。这类误报曾连续出现 3 次。
#    2. 不得把「年份/日期」当资金额 —— 「2026-10-01起实施」的 2026 不是钱。
#    3. 不得把「分数/比例」当数值 —— 「1/3」的 1 不是成本价。
#    因此以下规则都要求「金额词 + 明确货币单位」同时出现才命中，
#    单有数字没有「万/亿/元/W」不触发。
# ---------------------------------------------------------------------------
PII_RULES = [
    # 持仓数量：中文语境下"持仓 N 股/手/份"、"持有 N 股"
    ('holding_qty', 'CRITICAL',
     re.compile(r'(?:持仓|持有|买入|卖出|加仓|减仓|清仓)[^\d]{0,8}'
                r'(\d[\d,]*)\s*(?:股|手|份|张|单位)')),
    # 成本价：成本词 + 数字 + 货币单位（元/块），或「成本价 数字」无单位也命中
    # 无单位时用负向断言排除「利率1/3」这类分数与「个百分点」等政策表述
    ('cost_price', 'CRITICAL',
     re.compile(r'(?:成本价?|持仓成本|建仓价|我的成本)[^\d]{0,8}'
                r'(\d+\.?\d*)\s*(?:元|块)?(?![\d/%])(?!个百分点)(?!pct)')),
    # 资金规模：资金词 + 货币单位（万/亿/元/W）。无单位不命中（避免命中年份）
    ('capital_amount', 'CRITICAL',
     re.compile(r'(?:资金|本金|仓位|投入|可用资金|总资产)[^\d]{0,8}'
                r'(\d[\d,]*\.?\d*)\s*(?:万|亿|元|块|W|w)(?![\d/%])')),
    # 盈亏金额。财报中「亏损(-28.11 亿元)」是标准表述（**半角括号内负数**），
    # 故关键词与数字之间不允许出现半角括号或负号；
    # 但**全角括号仍算命中** —— 「浮盈（15 万元）」是真实个人盈亏，必须拦。
    ('pnl_amount', 'CRITICAL',
     re.compile(r'(?:浮盈|浮亏|盈利|亏损|收益|赔了|赚了)'
                r'[^\d(\-—–]{0,8}'
                r'(\d[\d,]*\.?\d*)\s*(?:万|亿|元|块|%|个点)(?![\d/%])')),
    # 账户 / 券商标识
    ('broker_account', 'HIGH',
     re.compile(r'(?:资金账号|股东代码|证券账户|交易账户|券商)[^\d]{0,6}(\d{6,})')),
    # 身份证 / 手机号（连带保护）
    ('cn_idcard', 'HIGH',
     re.compile(r'\b(\d{17}[\dXx])\b')),
    ('cn_phone', 'MEDIUM',
     re.compile(r'\b(1[3-9]\d{9})\b')),
    # 邮箱
    ('email', 'MEDIUM',
     re.compile(r'\b([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b')),
]

SEVERITY_ORDER = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']

# ---------------------------------------------------------------------------
# 金融术语豁免：这些词含敏感关键词但属公开财务概念，不是个人持仓信息
# 例如「股权成本」「每股收益」会被 cost_price / pnl_amount 误伤
# 误报的危害等同漏报：告警疲劳会淹没真泄漏
# ---------------------------------------------------------------------------
FIN_TERM_SAFE = re.compile(
    r'(?:股权成本|资金成本|负债成本|融资成本|存款成本|边际成本|机会成本'
    r'|每股收益|每股净资产|净资产收益|年化收益|收益率|收益增速|收益质量'
    r'|资金面|资金流向|资金利用率|主力资金|北向资金'
    r'|持仓集中度|持仓占比|机构持仓|基金持仓|持仓市值'      # 公开披露口径，非个人
    r'|持仓量|持仓结构|持仓成本线'                          # 分析术语，非个人成本
    r'|成本费用率|成本收入比|成本管控|成本优势|成本端'
    r'|盈利预测|盈利能力|盈利质量|净利|毛利'
    r'|亏损面|亏损企业|亏损收窄)'
)

# ---------------------------------------------------------------------------
# 否定式声明豁免：「不涉及任何资金规模」「未记录个人持仓」这类表述
# 本身是合规声明，不是泄漏。若命中处的前文含否定词，则不阻断。
# ---------------------------------------------------------------------------
NEGATION_BEFORE = re.compile(
    r'(?:不涉及|未记录|未包含|无任何|不含|不写|不含任何|禁止|不得|未出现|未披露|无个人)'
    r'[^。；\n]{0,24}$'
)

# ---------------------------------------------------------------------------
# 财报科目豁免：资产负债表/利润表/现金流量表的公开科目不是个人持仓信息
# 例如「货币资金 8888.88 亿元」「经营活动现金流量净额 +100.00 亿元」
#     「综合融资成本 2.50%」「归母净利润」等
# ⚠️ 只做【紧邻前文 ≤24 字符】的局部豁免，不做整行豁免
#    （整行豁免会放过「政策显示再贷款额度扩大。同时我持仓12000股」这类混合行）
# ---------------------------------------------------------------------------
FIN_STATEMENT_SAFE = re.compile(
    r'(?:货币资金|现金及现金等价物|账面现金|经营活动现金流|现金流量净额|现金流净额|经营现金流'
    r'|营业收入|营业总收入|归母净利润|净利润|营业成本|综合成本|融资成本|资金成本|资本成本|负债成本|存款成本'
    r'|总资产|净资产|股东权益|少数股东权益|合同负债|有息负债'
    r'|存货|预收账款|应收账款|短期借款|长期借款|应付债券'
    r'|总市值|流通市值|总股本|流通股本|每股净资产|每股收益'
    r'|毛利率|净利率|资产负债率|分红|股息|贴息|额度'
    r'|拓展金额|拿地|签约|回笼|回款|地价|楼面价|计容'
    r'|减值|拨备|担保|质押|抵押)'
    # 科目名与数字之间允许：Markdown 表格管道符 | 、空格、中文逗号/冒号、括号及其内容
    # 不允许：句号、分号、换行等断句符（否则混合句会被一起放过）
    r'[ |，,：:（(【\[]?[^。；;，,]{0,10}$'
)


def _is_fin_statement(line: str, match_start: int, match_text: str = '') -> bool:
    r"""命中是否属于财报科目披露。

    ⚠️ 关键设计（2026-10-15 三次踩坑后定稿）：
    PII 规则形如 `(?:资金|本金|...)[^\d]{0,8}(\d...)`，匹配起点落在**关键词开头**。
    以「货币资金 8888.88 亿元」为例，匹配串是 `资金 8888.88 亿`，
    match_start=2，于是 line[:2] = "货币" —— 科目名的前半段**留在匹配串之外**。

    因此上下文的正确拼法是：
        line[:match_start]  +  匹配串中"数字之前的部分"
    而非把整个匹配串拼回去（那会把数字也包进窗口，反而挤掉科目名）。

    同时要求科目名与数字之间无断句符，避免
    「货币资金 1338 亿。同时我持仓 12000 股」这类混合句被一起放过。
    """
    # 取匹配串中第一个数字之前的部分（即关键词 + 间隔符）
    m_num = re.search(r'\d', match_text)
    prefix = match_text[:m_num.start()] if m_num else match_text
    # 向前看 30 字符：科目名可能被 Markdown 表格管道符或括号内容隔开
    ctx = (line[:match_start] + prefix)[-30:]
    return FIN_STATEMENT_SAFE.search(ctx) is not None


# ---------------------------------------------------------------------------
# 政策条款豁免：政策原文中的金额/规模数字是公开政策参数，不是个人资金
# 例如「单户上限100万元」「本金年化1个百分点」等
# ⚠️ 只做【紧邻前文 ≤24 字符】的局部豁免，绝不做整行豁免
#    （整行豁免会放过「政策显示再贷款额度扩大。同时我持仓12000股」这类混合行）
# ---------------------------------------------------------------------------
POLICY_TERM_SAFE = re.compile(
    r'(?:单户上限|上限|下限|额度|规模|限额|比例|门槛|首付|贴息'
    r'|增至|提高至|提升至|扩大至|由.{0,12}增至'
    r'|再贷款|逆回购|正回购|降准|降息|基点|pct|个百分点'
    r'|注册资本|资本净额|一级资本|集中度|拨备覆盖率|净融出余额)'
    r'[^\d]{0,12}$'
)


def _is_policy_term(line: str, match_start: int) -> bool:
    """命中处前文 ≤24 字符内是否紧跟政策参数词。只做局部豁免，不做整行豁免。"""
    head = line[:match_start][-24:]
    return POLICY_TERM_SAFE.search(head) is not None


def _is_fin_term(line: str, match_start: int, match_end: int) -> bool:
    """判断命中处是否落在金融术语豁免区间内。"""
    for m in FIN_TERM_SAFE.finditer(line):
        if m.start() <= match_start < m.end() or m.start() < match_end <= m.end():
            return True
    return False


def mask_value(v: str) -> str:
    """脱敏显示：前4 + 后2 + 长度。短值全打码。"""
    if v is None:
        return '(null)'
    s = str(v)
    if len(s) <= 8:
        return f'{"*" * len(s)}(len={len(s)})'
    return f'{s[:4]}...{s[-2:]}(len={len(s)})'


def scan_text(text: str, path: str):
    """对单份文本跑 PII 规则。"""
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for name, sev, rx in PII_RULES:
            for m in rx.finditer(line):
                # 金融术语豁免：公开财务概念不算个人持仓信息
                if _is_fin_term(line, m.start(), m.end()):
                    continue
                # 否定式声明豁免：「不涉及任何资金规模」这类合规声明不算泄漏
                if NEGATION_BEFORE.search(line[:m.start()]):
                    continue
                # 政策条款豁免：政策原文的金额/额度/比例是公开参数，不是个人资金
                if _is_policy_term(line, m.start()):
                    continue
                # 财报科目豁免：资产负债表/利润表/现金流量表公开科目不是个人持仓信息
                if _is_fin_statement(line, m.start(), m.group(0)):
                    continue
                val = m.group(1) if m.groups() else m.group(0)
                hits.append({
                    'rule': name,
                    'severity': sev,
                    'file': path,
                    'line': lineno,
                    'masked': mask_value(val),
                    'context': re.sub(r'\S', '·', line[:120]),
                })
    return hits


def iter_files(target: str):
    if os.path.isfile(target):
        yield target
        return
    for root, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for fn in files:
            if fn.endswith(('.md', '.txt', '.json', '.csv', '.yaml', '.yml')):
                yield os.path.join(root, fn)


def run_audit_secrets(target: str):
    """调用工作区已有的 audit-secrets.py（若存在）。"""
    ext = os.environ.get('EQUITY_SECRET_SCANNER', '')
    if not ext or not os.path.exists(ext):
        return None, ('skipped: no external scanner (set EQUITY_SECRET_SCANNER; built-in rules still run)')
    try:
        r = subprocess.run(
            [sys.executable, ext, target, '--json'],
            capture_output=True, text=True, timeout=300,
            encoding='utf-8', errors='replace')
    except Exception as e:
        return None, f'failed: {type(e).__name__}: {e}'
    if r.returncode == 2:
        return None, 'skipped(usage): ' + (r.stderr or '')[:200]
    try:
        data = json.loads(r.stdout or '{}')
    except Exception:
        return None, 'unparsable output'
    findings = data.get('findings') or data.get('hits') or []
    if not findings and isinstance(data, list):
        findings = data
    return findings, f'exit={r.returncode}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('target', help='要检查的文件或目录')
    ap.add_argument('--strict', action='store_true', help='MEDIUM 也拦截')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--no-external', action='store_true', help='跳过 audit-secrets.py')
    args = ap.parse_args()

    if not os.path.exists(args.target):
        print(f'[usage] target not found: {args.target}', file=sys.stderr)
        return 2

    all_hits = list(scan_text_collect(args.target))

    external = None
    ext_note = 'not run'
    if not args.no_external:
        external, ext_note = run_audit_secrets(args.target)
        if external:
            for f in external:
                all_hits.append({
                    'rule': f.get('rule', 'external'),
                    'severity': f.get('severity', 'CRITICAL'),
                    'file': f.get('file', args.target),
                    'line': f.get('line', '?'),
                    'masked': f.get('masked') or mask_value(f.get('value')),
                    'context': (f.get('context') or '')[:120],
                })

    block_sev = ['CRITICAL', 'HIGH', 'MEDIUM'] if args.strict else ['CRITICAL', 'HIGH']
    blocking = [h for h in all_hits if h['severity'] in block_sev]

    if args.json:
        print(json.dumps({'hits': all_hits, 'blocking': len(blocking),
                          'external_scan': ext_note}, ensure_ascii=False, indent=2))
    else:
        print(f'=== 脱敏门禁：{args.target} ===')
        print(f'external(audit-secrets): {ext_note}')
        print(f'PII 规则命中: {len(all_hits)}   拦截级({"/".join(block_sev)}): {len(blocking)}')
        for h in all_hits:
            print(f'  [{h["severity"]:8}] {h["rule"]:16} '
                  f'{os.path.basename(h["file"])}:{h["line"]}  {h["masked"]}')
            if h.get('context'):
                print(f'      ctx: {h["context"]}')
        print('---')
        if blocking:
            print('❌ BLOCKED —— 发现敏感内容，禁止落盘。请脱敏后重跑。')
        else:
            print('✅ PASS —— 可落盘。')

    return 1 if blocking else 0


def scan_text_collect(target):
    out = []
    for p in iter_files(target):
        try:
            with open(p, 'r', encoding='utf-8', errors='replace') as f:
                txt = f.read()
        except Exception:
            continue
        out.extend(scan_text(txt, p))
    return out


if __name__ == '__main__':
    sys.exit(main())
