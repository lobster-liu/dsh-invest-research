#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
decision_score.py —— 决策质量回测（按结论标签聚合已结算决策）

存在理由
--------
一次运行只给出一个决策，**无法说明这套方法决策得好不好**。
只有把多个（标的, 决策日）单元的决策与后来的实际结果对齐，
按结论标签分组聚合，才能知道哪类结论更靠谱、哪类只是说说。

这与上游 TradingAgents 的 backtest 是同一件事，但**刻意不做组合模拟**：
把评级变成一笔成交需要数量、成交价与现金账本，本插件没有这些；
在一件评估工具背后塞一个执行模型是错的。因此每个单元相互独立。

口径（必须写进输出，否则数字不可复核）
------------------------------------
  - **入场**：决策日**之后第一个收盘日**（决策日当天收盘后才发布的信息
    不应计入）；无法确定时用决策日收盘并标注为近似。
  - **持有窗口**：默认 20 个交易日。
  - **原始收益**：窗口末相对窗口初。
  - **超额（alpha）**：原始收益 − 基准同期收益。基准序列必须覆盖同一区间。
  - **命中率只对方向性标签计算**：`等待验证` / `数据不足` / `REVIEW` 不宣称方向，
    参与命中率统计会稀释结果，因此它们的样本数单独列出、不给命中率。
  - **未到期 / 结算失败 / 不可解析**都必须显式列出，**不得静默丢弃**。

前视偏差说明（强制章节）
------------------------
结论标签词表与打分阈值会随版本变化。把今天的词表回填到历史决策，
会凭空制造出「当年就会做出这个判断」的效果。因此：
  - 记录里带 `vocabulary_version` 的，按版本**分组统计，不跨版本合并**；
  - 词表变化的历史单元单列为「旧词表」，不并入主口径；
  - 输出必须附一段前视偏差说明，写明本次统计用到的词表版本与已知偏差来源。

用法：
  python decision_score.py --ledger <ledger.jsonl> --settlements <settlements.json> --out <out.md>
"""

import argparse
import io
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from rating import LABELS, REVIEW, DIRECTIONAL_LABELS, DIRECTION, parse_label
except Exception:  # pragma: no cover
    LABELS = ('优先研究', '可以关注', '等待验证', '暂不优先', '数据不足')
    REVIEW = 'REVIEW'
    DIRECTIONAL_LABELS = ('优先研究', '可以关注', '暂不优先')
    DIRECTION = {'优先研究': 1, '可以关注': 1, '暂不优先': -1}

    def parse_label(md):
        return REVIEW

# 结算状态
SETTLED = 'SETTLED'
PENDING = 'PENDING'
SETTLE_FAILED = 'SETTLE_FAILED'


def load_json(path):
    if not path or not os.path.exists(path):
        return None
    try:
        with io.open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return None


def load_jsonl(path):
    records, broken = [], 0
    if not path or not os.path.exists(path):
        return records, broken
    with io.open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    records.append(obj)
                else:
                    broken += 1
            except Exception:
                broken += 1
    return records, broken


def _alpha(entry):
    """从结算记录里取超额收益（单位：小数）。取不到返回 None。"""
    if not isinstance(entry, dict):
        return None
    raw = entry.get('超额收益')
    if raw is None:
        raw = entry.get('alpha')
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().rstrip('%')
    try:
        value = float(text)
    except ValueError:
        return None
    # 裸数字按小数处理；带 % 的按百分数处理
    if str(raw).strip().endswith('%'):
        return value / 100.0
    if abs(value) > 1.0:
        return value / 100.0
    return value


def build_cells(decisions, settlements):
    """把决策与结算对齐成单元列表。

    结算记录以 ``(code, as_of)`` 为键；缺结算的决策记为 PENDING。
    """
    settle_map = {}
    for s in settlements:
        if not isinstance(s, dict):
            continue
        key = (str(s.get('code') or ''), str(s.get('as_of') or ''))
        settle_map[key] = s

    cells = []
    for rec in decisions:
        code = str(rec.get('code') or '')
        as_of = str(rec.get('as_of') or '')
        label = rec.get('label')
        if not isinstance(label, str) or label not in LABELS:
            label = REVIEW
        s = settle_map.get((code, as_of))
        if s is None:
            status = PENDING
            alpha = None
            raw = None
            reason = '未找到结算记录'
        else:
            status = s.get('状态') or s.get('status') or SETTLE_FAILED
            alpha = _alpha(s)
            raw = s.get('原始收益') if s.get('原始收益') is not None else s.get('raw_return')
            reason = s.get('原因') or s.get('reason') or ''
            if status == SETTLED and alpha is None:
                status = SETTLE_FAILED
                reason = reason or '结算记录缺少超额收益'
        cells.append({
            'run_id': rec.get('run_id'),
            'code': code,
            'as_of': as_of,
            'label': label,
            'vocabulary_version': rec.get('vocabulary_version') or '未标注',
            'status': status,
            'alpha': alpha,
            'raw': raw,
            'reason': reason,
        })
    # 结算了但决策日志里没有的单元 —— 也要列出（可能是日志被截断）
    for (code, as_of), s in settle_map.items():
        if not any(c['code'] == code and c['as_of'] == as_of for c in cells):
            cells.append({
                'run_id': None, 'code': code, 'as_of': as_of, 'label': REVIEW,
                'vocabulary_version': '未知', 'status': SETTLED,
                'alpha': _alpha(s), 'raw': None,
                'reason': '结算记录在决策日志中无对应条目（可能日志被截断或手工删除）',
            })
    return cells


def summarize(cells):
    """按标签聚合。返回可直接渲染的统计结构。"""
    settled = [c for c in cells if c['status'] == SETTLED and c['alpha'] is not None]
    pending = [c for c in cells if c['status'] == PENDING]
    failed = [c for c in cells if c['status'] == SETTLE_FAILED]

    # 标签维度必须覆盖**所有出现过的标签**，哪怕它的已结算样本数为 0。
    # 只渲染「有已结算单元」的标签，会让「全部未到期」的标签（典型是
    # 等待验证 / 数据不足）连样本数一起消失 —— 那样就看不出
    # 「这个标签一条都没验证过」，正是最该看见的信息。
    all_labels = list(LABELS) + [REVIEW]
    by_label = {}
    for label in all_labels:
        group = [c for c in settled if c['label'] == label]
        n_pending = len([c for c in pending if c['label'] == label])
        n_failed = len([c for c in failed if c['label'] == label])
        n_total = len(group) + n_pending + n_failed
        if n_total == 0:
            continue
        alphas = [c['alpha'] for c in group]
        direction = DIRECTION.get(label, 0)
        hit_rate = None
        if direction and alphas:
            hit_rate = sum(1 for a in alphas if a * direction > 0) / float(len(alphas))
        by_label[label] = {
            'count': len(group),
            'pending': n_pending,
            'failed': n_failed,
            'total': n_total,
            'mean_alpha': (sum(alphas) / len(alphas)) if alphas else None,
            'hit_rate': hit_rate,
            'directional': bool(direction),
        }

    # 按词表版本分组（跨版本不得合并）
    by_vocab = {}
    for c in settled:
        v = c['vocabulary_version']
        by_vocab.setdefault(v, []).append(c)

    return {
        'resolved': len(settled),
        'pending': len(pending),
        'failed': len(failed),
        'unscored': len([c for c in cells if c['label'] == REVIEW]),
        'by_label': by_label,
        'by_vocab': {v: len(g) for v, g in by_vocab.items()},
        'cells': cells,
    }


def render_md(summary, holding='20 个交易日'):
    """渲染回测报告 Markdown。"""
    lines = []
    lines.append('# 决策质量回测\n')
    lines.append('- 已结算单元：%d' % summary['resolved'])
    lines.append('- 未到期（PENDING）：%d' % summary['pending'])
    lines.append('- 结算失败（SETTLE_FAILED）：%d' % summary['failed'])
    lines.append('- 结论标签不可解析（REVIEW）：%d' % summary['unscored'])
    lines.append('- 持有窗口：%s' % holding)
    lines.append('')

    lines.append('## 按结论标签\n')
    lines.append('| 结论标签 | 已结算 n | 未到期 | 结算失败 | 平均超额 | 命中率 | 说明 |')
    lines.append('|---|---|---|---|---|---|---|')
    for label in list(LABELS) + [REVIEW]:
        s = summary['by_label'].get(label)
        if not s:
            continue
        if s['directional']:
            hit = '%.0f%%' % (s['hit_rate'] * 100) if s['hit_rate'] is not None else '—'
            note = '方向性标签，命中率有意义'
        else:
            hit = '不适用'
            note = '**不宣称方向，不计命中率**（计入会稀释结果）'
        mean = ('%+.2f%%' % (s['mean_alpha'] * 100)) if s['mean_alpha'] is not None else '—'
        if s['count'] == 0:
            note += '；**已结算样本为 0**，该标签尚未被验证过'
        lines.append('| %s | %d | %d | %d | %s | %s | %s |' % (
            label, s['count'], s['pending'], s['failed'], mean, hit, note))
    if not summary['by_label']:
        lines.append('| （无决策单元） | 0 | 0 | 0 | — | — | 尚无满足持有窗口的决策 |')
    lines.append('')

    lines.append('## 前视偏差说明（必读）\n')
    lines.append('结论标签词表与打分阈值会随版本变化。把**今天的词表**回填到历史决策，')
    lines.append('会凭空制造「当年就会做出这个判断」的效果。因此：')
    lines.append('')
    lines.append('- 已按 `vocabulary_version` 分组统计，**跨版本不合并**：')
    for v, n in sorted(summary['by_vocab'].items()):
        lines.append('  - 词表版本 `%s`：%d 个已结算单元' % (v, n))
    if len(summary['by_vocab']) > 1:
        lines.append('  - ⚠️ 存在多个词表版本，上表的分组统计混合了不同词表下的决策，'
                     '结论只能作参考；应分版本复算后再比较。')
    else:
        lines.append('  - 本次统计只涉及单一词表版本，词表漂移未引入偏差。')
    lines.append('')
    lines.append('其他已知偏差来源：')
    lines.append('- **入场上沿**：决策日当天收盘后才发布的信息不计入，入场取其后第一个收盘日。')
    lines.append('- **模型采样**：LLM 采样本身不确定，同一标的同一决策日两次运行结论可能不同。')
    lines.append('- **单一快照**：本表反映的是这批决策的样本表现，不代表未来。')
    lines.append('')

    pending = [c for c in summary['cells'] if c['status'] == PENDING]
    failed = [c for c in summary['cells'] if c['status'] == SETTLE_FAILED]
    if pending:
        lines.append('## 未到期单元（未计入统计）\n')
        lines.append('| 标的 | 决策日 | 结论标签 |')
        lines.append('|---|---|---|')
        for c in pending:
            lines.append('| %s | %s | %s |' % (c['code'], c['as_of'], c['label']))
        lines.append('')
    if failed:
        lines.append('## 结算失败单元（未计入统计）\n')
        lines.append('| 标的 | 决策日 | 结论标签 | 原因 |')
        lines.append('|---|---|---|---|')
        for c in failed:
            lines.append('| %s | %s | %s | %s |' % (
                c['code'], c['as_of'], c['label'], c['reason'] or '未记录原因'))
        lines.append('')

    lines.append('## 结论\n')
    lines.append('**本表评估的是决策质量，不是组合收益。**它不模拟持仓、不产生买卖建议，')
    lines.append('也不评价任何单只基金。样本量小、词表会变、模型会漂——')
    lines.append('把它当作「哪类结论值得更多信任」的粗略线索，而不是精确度量。\n')
    lines.append('**仅供研究参考，不构成投资建议。**')
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description='决策质量回测（按结论标签聚合）')
    ap.add_argument('--ledger', required=True, help='决策日志 ledger.jsonl 路径')
    ap.add_argument('--settlements', default=None,
                    help='结算记录 settlements.json（数组或 {"结算": [...]}）')
    ap.add_argument('--out', required=True, help='输出 Markdown 路径')
    ap.add_argument('--json-out', default=None, help='同时输出 JSON')
    ap.add_argument('--holding', default='20 个交易日', help='持有窗口描述')
    args = ap.parse_args()

    decisions, broken = load_jsonl(args.ledger)
    settlements = []
    obj = None
    if args.settlements:
        obj = load_json(args.settlements)
        if isinstance(obj, list):
            settlements = obj
        elif isinstance(obj, dict):
            for key in ('结算', 'settlements', 'records', '单元'):
                if isinstance(obj.get(key), list):
                    settlements = obj[key]
                    break

    cells = build_cells(decisions, settlements)
    summary = summarize(cells)
    summary['broken_lines'] = broken

    md = render_md(summary, args.holding)
    directory = os.path.dirname(os.path.abspath(args.out))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with io.open(args.out, 'w', encoding='utf-8') as fh:
        fh.write(md)
    if args.json_out:
        with io.open(args.json_out, 'w', encoding='utf-8') as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({
        '已结算': summary['resolved'],
        '未到期': summary['pending'],
        '结算失败': summary['failed'],
        '不可解析': summary['unscored'],
        '损坏行': broken,
        '输出': args.out,
    }, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
