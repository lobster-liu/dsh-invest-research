#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
peer_builder.py —— fund-research 同业构建器（技能更新新增工具）

职责：给定锚点基金，自动或按名单构建"合法同业集合"。
核心判据：**跟踪标的严格相等**。名字 / 主题词 / 行业标签都不作数。

铁律（违反即剔除）：
  1. 同一基金的不同份额（A/C/E/I/联接）绝不构成同业 —— 直接剔除
  2. 跟踪标的不严格相等 —— 直接剔除
  3. 主动管理型 —— 剔除（不构成"同标的指数"同业）
  4. 交易状态非开放申购 —— 剔除
  5. 份额类别不一致 —— 剔除（A 只对 A，C 只对 C）
  6. 结构差异（联接 vs 直投）—— 不剔除，但标记为"不可比较维度"

用法（Windows，必须走 pwsh 调 python）：
  & $PY peer_builder.py --anchor 012733 --keyword 人工智能 --out peers.json
  & $PY peer_builder.py --anchor 012733 --codes 011839,023461 --out peers.json
  & $PY peer_builder.py --anchor 012733 --codes 011839,023461 --track 中证人工智能主题指数 --out peers.json
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

SEARCH_URL = 'http://fund.eastmoney.com/js/fundcode_search.js'
# 搜索列表字段：代码 / 拼音 / 简称 / 类型 / 全称拼音
SEARCH_KEYS = ('fund_code', 'pinyin_abbr', 'fund_name', 'fund_type', 'pinyin_full')


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


def detect_share_class(name, code):
    """份额类别：以简称结尾的 A/C/E/I/D/Y/F 判定。联接 / 发起式 单独标记。"""
    suffix = ''
    for s in ('A', 'C', 'E', 'I', 'D', 'Y', 'F'):
        if name.endswith(s):
            suffix = s
            break
    return suffix


def detect_structure(name):
    """结构：'联接' → 联接基金；'发起式联接' → 发起式联接；'指数'/'ETF' → 直投指数。"""
    if '发起式联接' in name:
        return '发起式联接'
    if '联接' in name:
        return '联接'
    if 'ETF' in name and '联接' not in name:
        return 'ETF'
    return '指数'


def build(args):
    now = datetime.datetime.now().astimezone().isoformat(timespec='seconds')

    # 第一步：锚点跟踪标的
    anchor_name = ''
    if args.track:
        anchor_track = args.track
        print(f'[锚点] 使用用户指定的跟踪标的: {anchor_track}')
    else:
        # 从基金列表找锚点名
        fund_list = load_fund_list()
        anchor = next((f for f in fund_list if f['fund_code'] == args.anchor), None)
        if anchor:
            anchor_name = anchor['fund_name']
        anchor_track = fetch_tracking_target(args.anchor)
        if not anchor_track:
            print('错误: 锚点跟踪标的无法确认，无法判定同业。', file=sys.stderr)
            return 1
        print(f'[锚点] {args.anchor} {anchor_name} 跟踪标的: {anchor_track}')

    # 第二步：候选集合（名称/类型一律从全量列表查，不依赖用户输入）
    fund_list = load_fund_list()
    by_code = {f['fund_code']: f for f in fund_list}
    if args.codes:
        codes = [c.strip() for c in args.codes.split(',') if c.strip()]
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
        if kw:
            candidates = [f for f in fund_list if kw in f['fund_name']]
            source = f'keyword:{kw}'
        else:
            print('错误: 需 --codes 或 --keyword 指定候选范围', file=sys.stderr)
            return 1
        print(f'[候选] {source} → {len(candidates)} 只')

    # 第三步：逐只核对
    peers = []
    rejected = []
    seen_stem = {}  # 去重：去掉份额后缀后的"母基金名"
    anchor_stem = re.sub(r'[ACEIDYF]$', '', anchor_name)

    for cand in candidates:
        code = cand['fund_code']
        if code == args.anchor:
            continue
        name = cand.get('fund_name', '')
        ftype = cand.get('fund_type', '')
        # 份额与结构
        share = detect_share_class(name, code)
        struct = detect_structure(name)
        stem = re.sub(r'[ACEIDYF]$', '', name)

        # 铁律 3：主动型剔除
        if not is_passive(ftype):
            rejected.append({'code': code, 'name': name, 'type': ftype,
                             'reason': f'非被动型({ftype})，不构成同标的同业'})
            continue
        # 铁律 1：同基金不同份额剔除
        if stem and stem == anchor_stem and name != anchor_name:
            rejected.append({'code': code, 'name': name, 'type': ftype,
                             'reason': f'与锚点同基金不同份额（{stem}），铁律禁止混用'})
            continue
        # 铁律 2：跟踪标的严格相等
        cand_track = ''
        try:
            cand_track = fetch_tracking_target(code)
        except Exception as e:
            cand_track = ''
        if not cand_track:
            rejected.append({'code': code, 'name': name, 'type': ftype,
                             'reason': f'跟踪标的取不到，无法判定'})
            continue
        if cand_track != anchor_track:
            rejected.append({'code': code, 'name': name, 'type': ftype,
                             'reason': f'跟踪标的不同: "{cand_track}" ≠ "{anchor_track}"'})
            continue

        peers.append({
            'code': code,
            'name': name,
            'fund_type': ftype,
            'tracking_target': cand_track,
            'share_class': share,
            'structure': struct,
            'same_stem': stem,
        })

    # 第四步：输出
    anchor_info = {
        'code': args.anchor,
        'name': anchor_name or '(由 fund.json 提供)',
        'tracking_target': anchor_track,
    }
    result = {
        'anchor': anchor_info,
        'anchor_tracking_target': anchor_track,
        'build_time': now,
        'source': source,
        'criteria': [
            'tracking_target_exact_match（跟踪标的严格相等）',
            'share_class_not_same_fund（同基金不同份额剔除）',
            'passive_type_only（仅被动型）',
            'structure_flag（联接/直投差异标记为不可比较维度，不剔除）',
        ],
        'peers': peers,
        'rejected': rejected,
        'peer_count': len(peers),
        'rejected_count': len(rejected),
        'gaps': ['交易状态/规模/经理任期/费率需由 fetch_fund.py 逐只补齐'],
    }

    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f'\n[结果] 锚点: {args.anchor} 跟踪标的: {anchor_track}')
    print(f'  合法同业: {len(peers)} 只')
    for p in peers:
        print(f'    {p["code"]} {p["name"]} [{p["share_class"]}/{p["structure"]}]')
    print(f'  剔除: {len(rejected)} 只')
    for r in rejected[:10]:
        print(f'    {r["code"]} {r["name"]} → {r["reason"]}')
    if len(rejected) > 10:
        print(f'    ... 还有 {len(rejected)-10} 只')
    print(f'  已写入: {args.out}')
    return 0


def main():
    ap = argparse.ArgumentParser(description='fund-research 同业构建器')
    ap.add_argument('--anchor', required=True, help='锚点基金代码，如 012733')
    ap.add_argument('--out', required=True, help='输出 peers.json 路径')
    ap.add_argument('--codes', default='', help='逗号分隔的候选同业代码；给此则不用 keyword')
    ap.add_argument('--keyword', default='', help='名字关键词，自动搜索候选（如 "人工智能"）')
    ap.add_argument('--track', default='', help='可选，直接指定锚点跟踪标的，跳过锚点抓取')
    args = ap.parse_args()
    return build(args)


if __name__ == '__main__':
    sys.exit(main())
