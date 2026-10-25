#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
peer_builder.py —— fund-research 同业构建器（阶段 6 对比层第一步）

职责：给定锚点基金，自动或按名单构建"合法同业集合"。
核心判据：**跟踪标的严格相等**。名字 / 主题词 / 行业标签都不作数。

────────────────────────────────────────────────────────────────────────
脚本实际执行的判定（违反即剔除，共 3 条）
  A. 跟踪标的不严格相等 —— 直接剔除
  B. 主动管理型（非指数 / ETF / 被动）—— 剔除
  C. 与锚点属同一基金的不同份额 —— 剔除（按 strip_share_class 后的主体名比对）

不剔除、只打标记（1 条）
  D. 结构差异（联接 vs 直投）—— 写入 structure / comparability，标为"不可比较维度"

脚本 **不执行**、必须由 Agent-P1 人工复核（2 条，见 roles/peer-builder.md）
  E. 交易状态（封闭期 / 暂停申购 / 暂停大额申购）—— 本脚本不读交易状态字段
  F. 份额类别一致性（A 只对 A，C 只对 C）—— 本脚本只给 share_class 字段，不做分组剔除
────────────────────────────────────────────────────────────────────────

⚠️ 已知局限
  · share_class 由简称末位字母推断，是**启发式**而非披露字段；
    类型/联接缩写（ETF / LOF / FOF / QDII / 联接）结尾已排除，不会被误判成份额类别。
    识别不出的份额类别（share_class 为空）一律记为「未取得，须人工核对」。
  · 结构化字段 comparability 只表达"脚本能证明的前提"，不表达"可对比谁更优"。

用法（bash / PowerShell 均可；--codes 一律加引号，脚本内 zfill(6) 兜底）：
  & $PY peer_builder.py --anchor 012733 --keyword 人工智能 --out peers.json
  & $PY peer_builder.py --anchor 012733 --codes '011839,023461' --out peers.json
  & $PY peer_builder.py --anchor 012733 --codes '011839,023461' --track 中证人工智能主题指数 --out peers.json
"""

import argparse
import datetime
import json
import re
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36')

SEARCH_URL = 'https://fund.eastmoney.com/js/fundcode_search.js'
# 东财该地址同时支持 http/https；个别网络只放行 http，故保留回退。
SEARCH_URL_FALLBACK = 'http://fund.eastmoney.com/js/fundcode_search.js'
# 搜索列表字段：代码 / 拼音 / 简称 / 类型 / 全称拼音
SEARCH_KEYS = ('fund_code', 'pinyin_abbr', 'fund_name', 'fund_type', 'pinyin_full')

# 类型 / 联接 / 结构缩写结尾：这些结尾的末位字母**不是**份额类别
# 修复历史缺陷：'某ETF' 曾因末尾是 F 被判成 F 份额。
TYPE_TAIL_WORDS = ('发起式联接', 'ETF联接', 'ETF-FOF', '联接', 'LOF', 'FOF',
                   'QDII', 'ETF', '指数增强', '指数', '增强', '基金')

# 份额类别字母（不含 B：少数分级 B 已退市，遇 B 走人工复核）
SHARE_CLASS_LETTERS = ('A', 'C', 'D', 'E', 'F', 'I', 'O', 'Y')

# 币种 / 份额修饰括号，剥掉后才判断末位字母
CURRENCY_PAREN = re.compile(
    r'[（(]\s*(?:人民币|美元|美元现汇|美元现钞|港币|欧元|美元份额|人民币份额)\s*[）)]\s*$')

# 末尾任意括号补充说明（如在管、仅限机构等），仅用于主体名比对
TRAILING_PAREN = re.compile(r'[（(][^（）()]*[）)]\s*$')


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Referer': 'https://fund.eastmoney.com/',
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode('utf-8', errors='replace')


def load_fund_list():
    """全量基金列表（约 2.8 万只）。返回 [{fund_code,fund_name,fund_type,...}]。"""
    raw = http_get(SEARCH_URL)
    try:
        m = re.search(r'\[\s*\[.*?\]\s*\]', raw, re.S)
        if not m:
            raise RuntimeError('fundcode_search.js 解析失败')
    except Exception:
        # https 被中间设备拦截时回退 http（同一路径，仅协议不同）
        raw = http_get(SEARCH_URL_FALLBACK)
        m = re.search(r'\[\s*\[.*?\]\s*\]', raw, re.S)
        if not m:
            raise RuntimeError('fundcode_search.js 解析失败')
    arr = json.loads(m.group(0))
    out = []
    for row in arr:
        if len(row) < 5:
            continue
        out.append({
            SEARCH_KEYS[0]: row[0],
            SEARCH_KEYS[1]: row[1],
            SEARCH_KEYS[2]: row[2],
            SEARCH_KEYS[3]: row[3],
            SEARCH_KEYS[4]: row[4],
        })
    return out


def parse_tracking_target(fund_page_html):
    """从基金主页抓跟踪标的。取不到返回 None。"""
    m = re.search(r'跟踪标的：</a>\s*([^|<]{1,60}?)\s*(?:<|\|)', fund_page_html)
    if m:
        return m.group(1).strip()
    m = re.search(r'业绩比较基准[^<]*<[^>]*>([^<]{1,80})', fund_page_html)
    if m:
        return m.group(1).strip()
    return None


def fetch_tracking_target(code):
    """只抓一只基金的跟踪标的（不做全量取数，速度可控）。"""
    url = f'https://fund.eastmoney.com/{code}.html'
    html = http_get(url, timeout=20)
    return parse_tracking_target(html)


def is_passive(fund_type):
    """被动型 = 指数型-股票 / 指数型-其他 / ETF 等。主动混合/股票/债券 均非同业。"""
    if not fund_type:
        return False
    return ('指数' in fund_type) or ('ETF' in fund_type) or ('被动' in fund_type)


def _ends_with_type_tail(name):
    """简称是否以类型/联接/结构缩写结尾（此时末位字母不构成份额类别）。"""
    return any(name.endswith(t) for t in TYPE_TAIL_WORDS)


def strip_share_class(name):
    """剥掉简称末尾的份额字母与币种括号，返回"基金主体名"，用于识别同基金不同份额。

    例：'天弘中证人工智能主题ETF发起式联接A' → '天弘中证人工智能主题ETF发起式联接'
        '天弘中证人工智能主题ETF发起式联接C' → '天弘中证人工智能主题ETF发起式联接'  （相等 → 同一基金）
        '某ETF'                              → '某ETF'（ETF 是类型缩写，不剥）
        '某指数A（人民币）'                   → '某指数'
    """
    s = (name or '').strip()
    if not s:
        return ''
    s = CURRENCY_PAREN.sub('', s).strip()
    if _ends_with_type_tail(s):
        return s
    m = re.search(r'([A-Z])$', s)
    if m and m.group(1) in SHARE_CLASS_LETTERS:
        return s[:-1].strip()
    return s


def detect_share_class(name, code=''):
    """份额类别：以简称结尾的 A/C/D/E/F/I/O/Y 判定；识别不出返回 ''。

    修复（上游 v0.4.0 缺陷）：先剥币种括号、再排除 ETF/LOF/FOF/QDII/联接/
    指数/增强/基金 等类型缩写结尾，最后才匹配末位字母。
    因此 '某ETF' 不再被判成 'F' 份额。
    """
    s = (name or '').strip()
    if not s:
        return ''
    s = CURRENCY_PAREN.sub('', s).strip()
    # 类型/联接缩写结尾 → 末位字母属于类型词，不是份额类别
    if _ends_with_type_tail(s):
        return ''
    m = re.search(r'([A-Z])$', s)
    if m and m.group(1) in SHARE_CLASS_LETTERS:
        return m.group(1)
    return ''


def detect_structure(name):
    """结构：'联接' → 联接基金；'发起式联接' → 发起式联接；'指数'/'ETF' → 直投指数。"""
    if '发起式联接' in name:
        return '发起式联接'
    if '联接' in name:
        return '联接'
    if 'ETF' in name and '联接' not in name:
        return 'ETF'
    return '指数'


def normalize_code(raw):
    """基金代码归一：去空白、补前导零到 6 位。

    修复（上游 v0.4.0 缺陷）：用户/OCR 传入 '11839' 时曾原样查询 → '未找到'。
    现统一 zfill(6) → '011839'。非纯数字代码（如场外特殊代码）原样返回。
    """
    s = (raw or '').strip()
    if not s:
        return ''
    if s.isdigit() and len(s) < 6:
        return s.zfill(6)
    return s


def normalize_codes(raw):
    """逗号分隔的候选代码串 → 归一后的列表（自动 zfill(6)、去空项、保序去重）。"""
    out = []
    for c in (raw or '').split(','):
        c = normalize_code(c)
        if c and c not in out:
            out.append(c)
    return out


def build(args):
    now = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
    anchor_code = normalize_code(args.anchor)
    padded = []
    if anchor_code != (args.anchor or '').strip():
        padded.append(f'{args.anchor}→{anchor_code}')

    # 全量基金列表只取一次：锚点名解析、候选集合都依赖它。
    fund_list = load_fund_list()
    by_code = {f['fund_code']: f for f in fund_list}

    # 第一步：锚点跟踪标的。
    # ⚠️ --track 只跳过"抓取跟踪标的"，不等于跳过身份解析：锚点简称仍须从全量
    # 列表解析，否则 anchor_stem 为空、判据 C（同基金不同份额剔除）会静默失效。
    anchor = by_code.get(anchor_code)
    anchor_name = anchor['fund_name'] if anchor else ''
    anchor_name_unresolved = not anchor_name
    if args.track:
        anchor_track = args.track
        print(f'[锚点] {anchor_code} {anchor_name} 使用用户指定的跟踪标的: {anchor_track}')
        if anchor_name_unresolved:
            print('[警告] 锚点不在全量基金列表中，无法解析简称 → 判据 C 失效，'
                  '须 Agent-P1 从 fund.json 补齐锚点名', file=sys.stderr)
    else:
        anchor_track = fetch_tracking_target(anchor_code)
        if not anchor_track:
            print('错误: 锚点跟踪标的无法确认，无法判定同业。', file=sys.stderr)
            return 1
        print(f'[锚点] {anchor_code} {anchor_name} 跟踪标的: {anchor_track}')

    # 第二步：候选集合（名称/类型一律从全量列表查，不依赖用户输入）
    pre_rejected = []
    dropped = 0
    capped = False
    if args.codes:
        codes = normalize_codes(args.codes)
        for raw in (args.codes or '').split(','):
            nc = normalize_code(raw)
            if raw.strip() and nc != raw.strip():
                padded.append(f'{raw.strip()}→{nc}')
        candidates = []
        for c in codes:
            f = by_code.get(c)
            if f:
                candidates.append(f)
            else:
                # 用户给的代码不在列表里，也允许，后续靠抓取跟踪标的判定
                candidates.append({'fund_code': c, 'fund_name': '', 'fund_type': ''})
        source = 'user-list'
    else:
        kw = args.keyword or ''
        if not kw:
            print('错误: 需 --codes 或 --keyword 指定候选范围', file=sys.stderr)
            return 1
        hits = [f for f in fund_list if kw in f['fund_name']]
        # 预筛：只有被动型才值得逐只抓主页；非被动型按判据 B 直接记为拒绝，
        # 不浪费一次串行抓取（keyword 命中量大时这是主要耗时来源）。
        candidates = [f for f in hits if is_passive(f['fund_type'])]
        for f in hits:
            if not is_passive(f['fund_type']):
                pre_rejected.append({
                    'code': f['fund_code'], 'name': f['fund_name'],
                    'type': f['fund_type'],
                    'reason': f'非被动型({f["fund_type"]})，不构成同标的同业'})
        cap = args.max_candidates
        if len(candidates) > cap:
            dropped = len(candidates) - cap
            candidates = candidates[:cap]
            capped = True
            pre_rejected.append({
                'code': '-', 'name': '-', 'type': 'keyword-cap',
                'reason': f'关键词命中被动型候选超过上限 {cap}，已截断（丢弃 {dropped} 只）；'
                          '调高 --max-candidates 或改用 --codes'})
        source = f'keyword:{kw}'
        print(f'[候选] {source} → 命中 {len(hits)} 只，其中被动型 {len(candidates)} 只待抓取'
              + (f'（上限 {cap} 已截断，丢弃 {dropped} 只）' if capped else ''))

    if padded:
        print(f'[代码归一] 已补前导零: {", ".join(padded)}')

    # 第三步：逐只核对
    peers = []
    rejected = list(pre_rejected)
    anchor_stem = strip_share_class(anchor_name)
    anchor_struct = detect_structure(anchor_name) if anchor_name else ''
    anchor_share = detect_share_class(anchor_name, anchor_code) if anchor_name else ''

    for cand in candidates:
        code = cand['fund_code']
        if code == anchor_code:
            continue
        name = cand.get('fund_name', '')
        ftype = cand.get('fund_type', '')
        # 份额与结构
        share = detect_share_class(name, code)
        struct = detect_structure(name)
        stem = strip_share_class(name)

        # 判定 B：主动型剔除
        if not is_passive(ftype):
            rejected.append({'code': code, 'name': name, 'type': ftype,
                             'reason': f'非被动型({ftype})，不构成同标的同业'})
            continue
        # 判定 C：同基金不同份额剔除
        if stem and anchor_stem and stem == anchor_stem and name != anchor_name:
            rejected.append({'code': code, 'name': name, 'type': ftype,
                             'reason': f'与锚点同基金不同份额（主体名"{stem}"相同），铁律禁止混用'})
            continue
        # 判定 A：跟踪标的严格相等
        cand_track = ''
        try:
            cand_track = fetch_tracking_target(code)
        except Exception:
            cand_track = ''
        if not cand_track:
            rejected.append({'code': code, 'name': name, 'type': ftype,
                             'reason': '跟踪标的取不到，无法判定'})
            continue
        if cand_track != anchor_track:
            rejected.append({'code': code, 'name': name, 'type': ftype,
                             'reason': f'跟踪标的不同: "{cand_track}" ≠ "{anchor_track}"'})
            continue

        # 判定 D：结构差异只标记不剔除
        if anchor_struct and struct != anchor_struct:
            struct_verdict = f'结构不同（锚点={anchor_struct} / 候选={struct}）：不可比较维度，保留但须标注'
        else:
            struct_verdict = f'结构一致（{struct}）'
        share_verdict = ('锚点份额类别未能从简称识别，须人工核对'
                         if not anchor_share
                         else ('份额类别一致' if share == anchor_share
                               else f'份额类别不一致（锚点={anchor_share} / 候选={share}）：须 Agent-P1 复核'))

        peers.append({
            'code': code,
            'name': name,
            'fund_type': ftype,
            'tracking_target': cand_track,
            'share_class': share,
            'structure': struct,
            'same_stem': stem,
            'comparability': {
                'tracking_target': 'same',
                'structure': struct_verdict,
                'share_class': share_verdict,
                'verdict': ('comparable_with_caveat'
                            if (anchor_struct and struct != anchor_struct) else 'comparable'),
            },
        })

    # 第四步：输出
    anchor_info = {
        'code': anchor_code,
        'name': anchor_name or '(未解析，须 Agent-P1 从 fund.json 补齐)',
        'tracking_target': anchor_track,
        'share_class': anchor_share,
        'structure': anchor_struct,
        'share_stem': anchor_stem,
    }
    gaps = [
        '交易状态/规模/经理任期/费率/跟踪误差需由 fetch_fund.py 逐只补齐',
        '交易状态与份额类别分组未被本脚本校验，属 Agent-P1 人工复核项',
    ]
    if anchor_name_unresolved:
        gaps.append(
            f'锚点 {anchor_code} 的简称未能从全量基金列表解析，判据 C（同基金不同份额）'
            '未生效；须 Agent-P1 从 fund.json 补齐锚点名后重新核对')
    if capped:
        gaps.append(f'关键词候选超过上限 {args.max_candidates}，已截断 {dropped} 只；'
                    '截断后的集合不代表全部命中')

    result = {
        'anchor': anchor_info,
        'anchor_tracking_target': anchor_track,
        'build_time': now,
        'source': source,
        'criteria_executed': [
            'tracking_target_exact_match（跟踪标的严格相等）—— 脚本执行',
            'passive_type_only（仅被动型）—— 脚本执行',
            'share_not_same_fund（同基金不同份额按主体名剔除）—— 脚本执行',
            'structure_flag（联接/直投差异标记，不剔除）—— 脚本执行',
        ],
        'agent_review_required': [
            'trading_status（封闭期/暂停申购/暂停大额申购）—— 脚本不读交易状态，必须 Agent-P1 人工复核',
            'share_class_consistency（A 只对 A，C 只对 C）—— 脚本只输出 share_class 字段，不做分组剔除，必须 Agent-P1 复核',
        ],
        'comparability': {
            'comparable': [p['code'] for p in peers if p['comparability']['verdict'] == 'comparable'],
            'comparable_with_caveat':
                [p['code'] for p in peers if p['comparability']['verdict'] == 'comparable_with_caveat'],
            'undeterminable': [r['code'] for r in rejected],
            'note': ('本字段只表达"脚本能证明的前提"。variance 维度（规模/费率/经理任期/'
                     '跟踪误差）不在此判定，由 fetch_fund.py 逐只补齐后交对比层角色。'),
        },
        'peers': peers,
        'rejected': rejected,
        'peer_count': len(peers),
        'rejected_count': len(rejected),
        'gaps': gaps,
    }

    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f'\n[结果] 锚点: {anchor_code} 跟踪标的: {anchor_track}')
    print(f'  合法同业: {len(peers)} 只')
    for p in peers:
        print(f'    {p["code"]} {p["name"]} [{p["share_class"]}/{p["structure"]}]'
              f' {p["comparability"]["verdict"]}')
    print(f'  剔除: {len(rejected)} 只')
    for r in rejected[:10]:
        print(f'    {r["code"]} {r["name"]} → {r["reason"]}')
    if len(rejected) > 10:
        print(f'    ... 还有 {len(rejected)-10} 只')
    print('  ⚠️ 待 Agent-P1 人工复核: 交易状态 / 份额类别一致性')
    print(f'  已写入: {args.out}')
    return 0


def main():
    ap = argparse.ArgumentParser(description='fund-research 同业构建器')
    ap.add_argument('--anchor', required=True, help='锚点基金代码，如 012733（不足 6 位自动补零）')
    ap.add_argument('--out', required=True, help='输出 peers.json 路径')
    ap.add_argument('--codes', default='',
                    help='逗号分隔的候选同业代码，必须加引号；给此则不用 keyword')
    ap.add_argument('--keyword', default='', help='名字关键词，自动搜索候选（如 "人工智能"）')
    ap.add_argument('--max-candidates', type=int, default=60,
                    help='--keyword 路径下最多抓取多少只被动型候选（默认 60，'
                         '防止命中量大时串行抓取耗时失控）')
    ap.add_argument('--track', default='', help='可选，直接指定锚点跟踪标的，跳过锚点抓取')
    args = ap.parse_args()
    return build(args)


if __name__ == '__main__':
    sys.exit(main())
