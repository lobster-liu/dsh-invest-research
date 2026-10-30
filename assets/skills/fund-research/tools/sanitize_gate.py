#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
sanitize_gate.py —— 决策闭环共用的落盘脱敏门禁

背景
----
decision-loop 会落盘四类产物：
  阶段 1  ledger.jsonl          （decision_log.py 写）
  阶段 2  settlements.json      （settle.py 写）
  阶段 3  reflections.jsonl     （角色写）
  阶段 4  decision-quality.md   （decision_score.py 写）

阶段 1/2 由脚本写盘，**必须**在代码里过门禁；阶段 3/4 由角色写，SKILL.md
要求其自查。本模块把「对自由文本跑 sanitize_check」这件事提成同目录可导入的
公共件，让 decision_log.py 与 settle.py **共用同一份规则与同一套失败关闭语义**，
避免两处各写一遍导致口径漂移。

规则来源：`stock-research/tools/sanitize_check.py`（同一份，不复制）。
因此 fund-research 硬依赖同级的 stock-research/tools 目录 —— 这是安全正确的
行为：门禁脚本缺失时**失败关闭**（返回 ``(-1, 'missing')``），调用方必须拒绝写入，
绝不静默放行。

公开接口
--------
  load_sanitize()          -> module | None
  sanitize_record(record)  -> (命中数, 规则集合)；门禁缺失时 (-1, 'missing')
  sanitize_text(text, src) -> (命中数, 规则集合)
  is_blocked(...)          -> bool
"""

import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 门禁脚本位置：本文件在 fund-research/tools/，sanitize_check.py 在同级
# stock-research/tools/。两个 skill 必须同级同装。
_SANITIZE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir,
    'stock-research', 'tools', 'sanitize_check.py')

# 拦截级严重度（与 sanitize_check 默认拦截级一致：CRITICAL/HIGH）
BLOCKING_SEVERITIES = ('CRITICAL', 'HIGH')


def load_sanitize():
    """按路径惰性加载共享门禁脚本；加载失败返回 None（调用方据此失败关闭）。"""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            '_shared_sanitize_check', os.path.abspath(_SANITIZE_PATH))
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def record_texts(record):
    """递归取出记录里所有字符串值（自由文本与结构化字段一并覆盖）。"""
    out = []
    stack = [record]
    while stack:
        cur = stack.pop()
        if isinstance(cur, str):
            out.append(cur)
        elif isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, (list, tuple, set)):
            stack.extend(cur)
    return out


def _count_blocking(hits):
    blocking = [h for h in hits if h.get('severity') in BLOCKING_SEVERITIES]
    rules = sorted({h.get('rule', '?') for h in blocking})
    return len(blocking), ','.join(rules)


def sanitize_text(text, source='<text>'):
    """对一段原始文本跑门禁。返回 ``(命中数, 规则集合)``；缺失时 ``(-1, 'missing')``。"""
    sanitize = load_sanitize()
    if sanitize is None:
        return -1, 'missing'
    return _count_blocking(sanitize.scan_text(text, source))


def sanitize_record(record, source='<record>'):
    """对一条结构化记录（dict / list / 任意嵌套）跑门禁。

    返回 ``(命中数, 规则集合)``：
      - 正常：``(0, '')``
      - 被拦：``(N, 'rule1,rule2')``
      - 门禁脚本缺失：``(-1, 'missing')``（调用方据此失败关闭）
    """
    sanitize = load_sanitize()
    if sanitize is None:
        return -1, 'missing'
    hits = []
    for text in record_texts(record):
        hits.extend(sanitize.scan_text(text, source))
    return _count_blocking(hits)


def is_blocked(result):
    """``sanitize_*`` 的返回值是否意味着「必须拒绝写入」。

    ``-1``（门禁缺失）同样算 blocked —— 失败关闭。
    """
    count, _rules = result
    return count != 0
