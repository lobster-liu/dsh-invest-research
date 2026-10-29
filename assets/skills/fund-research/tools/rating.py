#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
rating.py —— 结论标签词表与解析器（stock-research 与 fund-research 共用）

存在理由
--------
结论标签原先在四个地方各写一遍（fund-research 的 SKILL.md、roles/orchestrator.md、
roles/peer-orchestrator.md，以及 tools/comparator.py 的 LABELS 元组），口径会漂移；
且旧解析方式是对整篇报告做子串扫描（`if l in md`），既可能被正文里随口提到的一个
标签命中，也无法区分「本次结论」与「被讨论到的他人结论」。

本模块把词表收敛成唯一权威来源，并提供：
  1. 统一的 5 档结论标签词表（只增不改）；
  2. **REVIEW 哨兵** —— 解析不出结论标签时返回 REVIEW，**绝不**静默退化成
     任何中性标签（把读不懂的决策当成「等待验证」，等于伪造了一个从未作出的判断）；
  3. 容忍 Markdown 加粗、全角冒号/括号、NFKC 归一化的锚定解析器；
  4. 方向性标签集合 —— 只有宣称了方向的标签才参与命中率统计。

调用方契约
----------
- `parse_label(md)` 返回 `LABELS` 之一或 `REVIEW`；
- 拿到 `REVIEW` 的调用方必须把它计入「未解析」清单并在报告中如实披露，
  **不得**当作 `等待验证` 或任何其他标签；
- `DIRECTIONAL_LABELS` 之外的标签（等待验证 / 数据不足 / REVIEW）不宣称方向，
  因此**不计算命中率**，但其样本数必须单独列出。
"""

import re
import unicodedata

# ---------------------------------------------------------------------------
# 唯一权威词表（只增不改：历史标签永不删除，避免决策日志回填时无法解析）
# ---------------------------------------------------------------------------
LABELS = (
    '优先研究',   # 证据支持，值得优先投入研究时间
    '可以关注',   # 有条件支持，需要先满足某项验证
    '等待验证',   # 不宣称方向，等某项证据到位再定
    '暂不优先',   # 证据不支持近期投入研究时间
    '数据不足',   # 关键数据缺失，本次结论不成立
)

# 解析失败的哨兵。它不是第六个标签，而是一个「这份决策不可读」的状态。
# 上游 TradingAgents 的对应设计：解析不出评级时发 REVIEW，而不是退化成 Hold。
REVIEW = 'REVIEW'

# 方向性标签：宣称了「看多/看空」方向的，才谈得上命中率。
# 等待验证 / 数据不足 / REVIEW 都不宣称方向，参与命中率统计会稀释结果。
DIRECTIONAL_LABELS = ('优先研究', '可以关注', '暂不优先')

# 每个方向标签对应的方向符号，用于判定「方向判对没有」。
DIRECTION = {
    '优先研究': 1,
    '可以关注': 1,
    '暂不优先': -1,
}

_LABEL_SET = set(LABELS)

# 「结论标签」标记词。允许同义词，避免模型写成「结论评级」就解析不出。
_LABEL_MARKERS = r'(?:结论标签|结论评级|评级标签|研究结论标签|结论文本)'

# 结论标签的合法写法集合（用于校验值本身）。
_VALUES = r'(?:' + '|'.join(LABELS) + r')'

# 1) 锚定解析：`结论标签：等待验证` / `**结论标签：等待验证**` / `- 结论标签 - 等待验证`
#    分隔符允许冒号 / 破折号 / 等号（半角与全角皆可），其后允许 markdown 强调符与空白。
_ANCHORED_RE = re.compile(
    _LABEL_MARKERS + r'\s*[:：\-—–=＝]?\s*[*_`「」【】\s]*(' + _VALUES + r')',
    re.IGNORECASE,
)

# 2) 兜底解析：`**结论标签：xxx**` 之外的裸标签行。
#    只接受「行首即标签」的形式，避免命中正文里随口提到的标签。
_BARE_LINE_RE = re.compile(
    r'^\s*[*_`「」【】#\-\s]*(' + _VALUES + r')\s*[*_`「」【】]*\s*$',
    re.MULTILINE,
)

# 3) 标签尺度说明行（模型把词表本身抄了回来），不是结论。
_SCALE_RE = re.compile(r'(?:标签|评级|结论)\s*(?:尺度|量表|档位|选项|说明|列表|词表)', re.IGNORECASE)


def _normalize(text):
    """NFKC 归一化：全角冒号/括号/数字折成半角，中文标点形态统一。"""
    if not text:
        return ''
    return unicodedata.normalize('NFKC', text)


def is_review(signal):
    """是否为 REVIEW 哨兵（决策不可读）。"""
    return signal == REVIEW


def is_directional(label):
    """该标签是否宣称了方向（决定能否参与命中率统计）。"""
    return label in DIRECTIONAL_LABELS


def extract_label(md):
    """从报告 Markdown 中提取结论标签；解析不出返回 ``None``。

    与 `parse_label` 的区别：本函数不返回 REVIEW，便于调用方区分
    「明确写了非法标签」与「压根没写标签」两种失败。
    """
    if not md:
        return None
    norm = _normalize(md)

    # 先剔除「标签尺度说明」行，避免模型抄回的词表被当成结论。
    lines = [ln for ln in norm.splitlines() if not _SCALE_RE.search(ln)]
    if not lines:
        return None

    # 1) 锚定：优先取第一处「结论标签：xxx」。锚定比裸标签可靠，
    #    因为它指向本次决策自己的结论行，而不是别人结论的引用。
    anchored = _ANCHORED_RE.search('\n'.join(lines))
    if anchored:
        return anchored.group(1)

    # 2) 兜底：正文里独立成行的标签。
    bare = _BARE_LINE_RE.search('\n'.join(lines))
    if bare:
        return bare.group(1)
    return None


def parse_label(md):
    """从报告 Markdown 中解析结论标签。

    返回 `LABELS` 之一；**无法可靠解析时返回 `REVIEW`**。

    REVIEW 表示「这份决策不可读」。调用方必须把它计入未解析清单，
    不得当作 `等待验证` 或任何其他标签 —— 一个读不懂的决策不是中性决策。
    """
    label = extract_label(md)
    if label is None:
        return REVIEW
    # 防御：即使正则放宽，也必须落在合法集内，否则视为不可读。
    if label not in _LABEL_SET:
        return REVIEW
    return label


def parse_label_from_record(record):
    """从 `decision.json` 这类结构化记录里取标签。

    优先读 `label` 字段；缺失或非法则回退到从 `report_path` 指向的报告正文解析；
    两者都拿不到时返回 REVIEW。
    """
    if not isinstance(record, dict):
        return REVIEW
    label = record.get('label')
    if isinstance(label, str) and label.strip() in _LABEL_SET:
        return label.strip()
    report_md = record.get('report_md')
    if isinstance(report_md, str) and report_md.strip():
        return parse_label(report_md)
    return REVIEW


def describe():
    """返回词表说明，供报告/文档生成时引用，保证词表只在一处定义。"""
    return {
        'labels': list(LABELS),
        'review': REVIEW,
        'directional': list(DIRECTIONAL_LABELS),
    }


if __name__ == '__main__':
    import json
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    print(json.dumps(describe(), ensure_ascii=False, indent=2))
