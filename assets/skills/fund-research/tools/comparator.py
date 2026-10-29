#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
comparator.py —— fund-research 同业对比器（技能更新新增工具）

职责：在每只基金已完成完整 7 角色流程、report.md 与 fund.json 均已冻结后，
读取冻结产物做**结构化对比**。**不重算任何指标、不做新分析**——对比层
只负责把已裁决的结论按维度对齐，暴露口径冲突，产出对比矩阵与对比报告。

输入（全部只读）：
  --base  对比工作目录，内含 peer_builder 产出的 peers.json
           以及每只同业基金的 <code>/fund.json、<code>/report.md
           （或直接 --json 给已汇总的 facts.json）

用法：
  & $PY comparator.py --base <peer-compare 目录> --out comparison.md
"""

import argparse
import datetime
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 结论标签词表与解析器（唯一权威来源，stock-research 与 fund-research 共用）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from rating import LABELS, REVIEW, DIRECTIONAL_LABELS, parse_label, is_review
except Exception:  # pragma: no cover - 词表缺失时降级为不可解析，不静默取中性标签
    LABELS = ('优先研究', '可以关注', '等待验证', '暂不优先', '数据不足')
    REVIEW = 'REVIEW'
    DIRECTIONAL_LABELS = ('优先研究', '可以关注', '暂不优先')

    def parse_label(md):
        return REVIEW

    def is_review(signal):
        return signal == REVIEW

# 对比维度（每个维度一行结论，标注来源与是否同口径）
DIMENSIONS = (
    ('跟踪标的与结构', '是否跟踪同一指数；联接/直投/发起式结构差异'),
    ('持仓集中度', '前十大集中度；样本 vs 全组合口径'),
    ('行业暴露', '行业配置；样本行业占比 vs 全组合行业占比'),
    ('估值风险', '重仓股 PE/PB 分布；估值分化与透支程度'),
    ('费率结构', '管理费/托管费/申购费；对长期持有收益的影响'),
    ('规模与流动性', '规模单位一致性；规模对跟踪精度/申赎冲击的影响'),
    ('经理与稳定性', '经理任期；经理变更风险'),
    ('跟踪精度', '跟踪误差；被动跟踪偏离度'),
    ('风险调整收益', '夏普/最大回撤/年化波动；口径是否一致（rf、窗口、复权）'),
    ('结论标签', '每只基金独立流程给出的结论标签是否矛盾'),
)


def _load_json(path):
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _read_md(path):
    if not path or not os.path.exists(path):
        return ''
    with open(path, encoding='utf-8') as f:
        return f.read()


def extract_report_tags(md):
    """从 report.md 提取：结论标签、调度声明、口径缺陷、未取得项。

    结论标签用共用的 `rating.parse_label` 解析：锚定到「结论标签：xxx」，
    容忍 Markdown 加粗与全角标点；解析不出返回 REVIEW 哨兵。
    旧实现是对整篇报告做 `if l in md` 子串扫描，会把正文里随口提到的
    标签当成结论（例如对比表里出现「可以关注」就抢先命中），且解析失败
    时静默返回空串——读不懂的决策被当成没有标签，等于伪造了一个中性结论。
    """
    label = parse_label(md)
    # 调度声明
    decl = ''
    m = re.search(r'调度声明[^\n]*\n(.{0,300})', md)
    if m:
        decl = m.group(1).strip()
    # 口径缺陷
    caveats = []
    for kw in ('口径', '未取得', '不一致', '同源', '占位', '单位不一致'):
        if kw in md:
            caveats.append(kw)
    return {'conclusion_label': label, 'schedule_decl': decl,
            'caveats_found': caveats}


def build_matrix(base_dir):
    """扫描 base_dir 下所有 <code>/report.md + fund.json，汇总对比事实。"""
    peers_json = os.path.join(base_dir, 'peers.json')
    peers_meta = _load_json(peers_json) or {}
    anchor = peers_meta.get('anchor', {})
    anchor_code = anchor.get('code', '')
    anchor_track = peers_meta.get('anchor_tracking_target', '')

    # 收集所有基金目录（锚点 + peers）
    entries = []
    for name in sorted(os.listdir(base_dir)):
        sub = os.path.join(base_dir, name)
        if not os.path.isdir(sub):
            continue
        code = name
        md = _read_md(os.path.join(sub, 'report.md'))
        fj = _load_json(os.path.join(sub, 'fund.json'))
        if not md and not fj:
            continue
        tag = extract_report_tags(md)
        entries.append({
            'code': code,
            'report_md': md,
            'fund_json': fj,
            'label': tag['conclusion_label'],
            'schedule_decl': tag['schedule_decl'],
            'caveats': tag['caveats_found'],
        })

    # 口径一致性检查：所有基金是否同一跟踪标的、同一结论标签集合
    tracks = set()
    for e in entries:
        fj = e['fund_json'] or {}
        t = (fj.get('跟踪标的') or fj.get('tracking_target') or
             fj.get('业绩比较基准') or '')
        if t:
            tracks.add(str(t)[:40])
    labels = {e['label'] for e in entries if e['label'] and e['label'] != REVIEW}
    # REVIEW 单独统计：解析不出来的报告是**流程故障**，不是研究分歧，
    # 混进「结论标签分化」会把基础设施问题误报成结论矛盾。
    review_codes = [e['code'] for e in entries if e['label'] == REVIEW]

    return {
        'anchor': anchor,
        'anchor_track': anchor_track,
        'entries': entries,
        'distinct_tracks': list(tracks),
        'distinct_labels': list(labels),
        'review_codes': review_codes,
    }


def render_md(matrix):
    """渲染对比矩阵 Markdown。"""
    lines = []
    lines.append('# 基金同业对比矩阵\n')
    lines.append(f"- 对比基准日：{datetime.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %z')}")
    lines.append(f"- 锚点：{matrix['anchor'].get('code','')} {matrix['anchor'].get('name','')}")
    lines.append(f"- 锚点跟踪标的：{matrix['anchor_track'] or '未取得'}")
    lines.append(f"- 对比基金数：{len(matrix['entries'])}")
    if matrix['distinct_tracks']:
        lines.append(f"- 观测到的跟踪标的集合（应为同一集合才可对比）：{matrix['distinct_tracks']}")
    if len(matrix['distinct_tracks']) > 1:
        lines.append('> ⚠️ **跟踪标的不一致**——以下基金不构成严格同业，对比结论需打折扣。')
    lines.append(f"- 各基金独立流程给出的结论标签集合：{matrix['distinct_labels']}")
    if matrix.get('review_codes'):
        lines.append(f"- ⚠️ **结论标签不可解析（REVIEW）**：{matrix['review_codes']}"
                     " —— 这是流程故障（报告未按「结论标签：xxx」格式落盘），"
                     "不是结论分歧；须退回该基金补齐后重新对比。")
    lines.append('')

    # 调度声明一致性
    lines.append('## 调度声明一致性（铁律11）\n')
    lines.append('| 基金 | 调度声明摘要 | 是否声明独立多Agent验证 |')
    lines.append('|---|---|---|')
    for e in matrix['entries']:
        d = e['schedule_decl']
        is_multi = ('子代理' in d and '独立' in d and '0 次' not in d)
        lines.append(f"| {e['code']} | {(d[:80] or '无声明')} | {'✅' if is_multi else '❌ 未声称独立多Agent'} |")
    lines.append('')

    # 口径一致性总表
    lines.append('## 各基金结论标签与口径状态\n')
    lines.append('| 基金 | 结论标签 | 口径缺陷检出 |')
    lines.append('|---|---|---|')
    for e in matrix['entries']:
        lines.append(f"| {e['code']} | {e['label'] or '未标注'} | {', '.join(e['caveats']) or '无'} |")
    lines.append('')
    # 对比维度矩阵
    lines.append('## 十维度对比矩阵\n')
    lines.append('| 维度 | 说明 | 对比结论 |')
    lines.append('|---|---|---|')
    lines.append('| 跟踪标的与结构 | 是否同一指数；联接/直投/发起式 | 见上表跟踪标的集合检查 |')
    lines.append('| 持仓集中度 | 前十大集中度；样本 vs 全组合 | 需读各基金 report.md 持仓章 |')
    lines.append('| 行业暴露 | 行业配置；样本 vs 全组合口径 | 需读各基金 report.md 行业章 |')
    lines.append('| 估值风险 | PE/PB 分布、估值分化 | 需读各基金 report.md 估值章 |')
    lines.append('| 费率结构 | 管理/托管/申购费 | 需读各基金 report.md 身份章 |')
    lines.append('| 规模与流动性 | 规模单位一致性 | 需读各基金 report.md 规模章 |')
    lines.append('| 经理与稳定性 | 经理任期与变更风险 | 需读各基金 report.md 经理章 |')
    lines.append('| 跟踪精度 | 跟踪误差、偏离度 | 需读各基金 report.md 跟踪章 |')
    lines.append('| 风险调整收益 | 夏普/回撤/波动，口径一致性 | 需读各基金 report.md 绩效章 |')
    lines.append('| 结论标签 | 各基金独立结论是否矛盾 | 见上表标签集合 |')
    lines.append('')

    # 冲突与未取得
    lines.append('## 关键冲突与口径风险\n')
    conflict_found = False
    if len(matrix['distinct_tracks']) > 1:
        lines.append(f'- **跟踪标的不一致**：{matrix["distinct_tracks"]}')
        conflict_found = True
    if len(matrix['distinct_labels']) > 1:
        lines.append(f'- **结论标签分化**：{matrix["distinct_labels"]}（需协调员裁决是否矛盾）')
    if matrix.get('review_codes'):
        lines.append(f'- **结论标签不可解析**：{matrix["review_codes"]}'
                     '（流程故障，须补齐后重比；不得当作「等待验证」）')
    for e in matrix['entries']:
        if e['caveats']:
            lines.append(f"- {e['code']} 检出口径线索：{', '.join(e['caveats'])}")
    if not conflict_found:
        lines.append('- 未发现跟踪标的层面的硬冲突。')

    lines.append('')
    lines.append('## 结论\n')
    lines.append('**本对比矩阵仅对齐各基金独立流程已冻结的结论，不重算任何指标。**')
    lines.append('各维度明细须回到对应 report.md 原文核对；本矩阵暴露的缺口与口径差异')
    lines.append('应作为协调员裁决的依据，不得用对比层数据反推未披露的事实。\n')
    lines.append('**仅供研究参考，不构成投资建议。**')

    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description='fund-research 同业对比器')
    ap.add_argument('--base', required=True, help='对比工作目录（含 peers.json + 各基金子目录）')
    ap.add_argument('--out', required=True, help='输出 Markdown 路径')
    args = ap.parse_args()

    matrix = build_matrix(args.base)
    md = render_md(matrix)
    with open(args.out, 'w', encoding='utf-8') as f:
        f.write(md)

    print(f'对比基金数: {len(matrix["entries"])}')
    print(f'跟踪标的集合: {matrix["distinct_tracks"]}')
    print(f'结论标签集合: {matrix["distinct_labels"]}')
    print(f'已写入: {args.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
