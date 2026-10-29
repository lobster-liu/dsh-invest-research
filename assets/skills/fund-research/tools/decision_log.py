#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
decision_log.py —— 决策记录与决策日志（append-only ledger）

存在理由
--------
此前本插件的每次研究都是**一次性**的：报告落在各自的 run 目录里，
没有任何机制把「上次结论是什么」和「后来发生了什么」连起来。
于是无法回答两个最基本的问题：
  1. 上次给的结论，后来对不对？
  2. 这套方法整体的决策质量如何（哪类结论更靠谱）？

这与上游 TradingAgents 的 Memory Log 是同一个缺口。补法：
  - 每次运行结束，协调员把结论写成一条**结构化决策记录** `decision.json`；
  - 该记录**只增追加**进决策日志 `ledger.jsonl`（一行一条 JSON）；
  - 后续运行可读取历史决策 → 结算 → 复盘 → 形成教训。

设计约束（重要）
----------------
1. **只增不改**：日志行永不重排、覆盖、截断。同一 `run_id` 重复写入时按
   `run_id` 去重（保留首次写入），保证日志幂等且可重放。
2. **日志不是数据源**：历史决策里的数字**不得**进入新报告的数据表。
   它只提供「先验教训」与「上次结论是否被证伪」。这是与既有
   「单一数据源锁定」铁律的边界，必须由调用方显式声明。
3. **不含个人头寸**：日志只存公开研究结论与公开数据，受脱敏门禁约束。
4. **写日志失败不中止研究**：日志是增强件，不是研究本身。写失败必须如实报告。

用法：
  # 写入一条决策
  python decision_log.py append --ledger <path> --record <decision.json>
  # 读取（可选过滤）
  python decision_log.py list --ledger <path> --code 011839
  # 校验日志格式
  python decision_log.py verify --ledger <path>
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

SCHEMA = 'dsh-invest-decision/1'

# 决策记录的必备字段。缺任何一个都不算一条合格的决策记录。
REQUIRED_FIELDS = ('run_id', 'code', 'as_of', 'label')

# 已知字段（用于校验与文档生成）
KNOWN_FIELDS = (
    'schema', 'run_id', 'code', 'name', 'as_of', 'label', 'label_conditions',
    'label_horizon', 'confidence', 'conditions', 'benchmark', 'report_path',
    'source_skill', 'source_version', 'vocabulary_version', 'notes',
)


def load_ledger(path):
    """读取决策日志，返回 (记录列表, 损坏行数)。

    损坏行不阻断读取：日志里一行坏 JSON 不该让整份历史不可用，
    但损坏行数必须如实报告。
    """
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


def write_ledger(path, records):
    """**整体重写**日志（仅供测试与人工整理使用）。

    正常写入路径请用 `append_record`，那是只增操作。
    """
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with io.open(path, 'w', encoding='utf-8') as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + '\n')


def append_record(path, record):
    """把一条决策记录**追加**进日志。

    返回 ``(是否写入, 说明)``：
      - 写入成功 → (True, 'appended')
      - run_id 已存在 → (False, 'duplicate:run_id=<id>')（幂等，不重复写）
      - 字段不全 → (False, 'invalid:<缺失字段>')
      - 目录不可写 → (False, 'unwritable:<原因>')
    """
    if not isinstance(record, dict):
        return False, 'invalid:not_a_dict'
    missing = [f for f in REQUIRED_FIELDS if not record.get(f)]
    if missing:
        return False, 'invalid:missing=' + ','.join(missing)
    record.setdefault('schema', SCHEMA)

    existing, _ = load_ledger(path)
    run_id = str(record.get('run_id'))
    for rec in existing:
        if str(rec.get('run_id')) == run_id:
            return False, 'duplicate:run_id=' + run_id

    directory = os.path.dirname(os.path.abspath(path))
    try:
        if directory:
            os.makedirs(directory, exist_ok=True)
        with io.open(path, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n')
    except Exception as exc:
        return False, 'unwritable:%s' % (type(exc).__name__)
    return True, 'appended'


def read_record(path):
    """读取一条 `decision.json` 文件。"""
    if not path or not os.path.exists(path):
        return None
    try:
        with io.open(path, encoding='utf-8') as fh:
            obj = json.load(fh)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def filter_records(records, code=None, since=None, until=None):
    """按代码与基准日区间过滤决策记录。"""
    out = []
    for rec in records:
        if code and str(rec.get('code')) != str(code):
            continue
        as_of = str(rec.get('as_of') or '')
        if since and as_of < str(since):
            continue
        if until and as_of > str(until):
            continue
        out.append(rec)
    return out


def verify(records, broken=0):
    """校验日志一致性。返回问题列表（空列表 = 通过）。"""
    problems = []
    if broken:
        problems.append('有 %d 行无法解析为 JSON（已跳过，但不可静默忽略）' % broken)
    seen = {}
    for rec in records:
        run_id = str(rec.get('run_id') or '')
        if not run_id:
            problems.append('存在缺少 run_id 的记录')
            continue
        if run_id in seen:
            problems.append('run_id 重复：%s（日志应为只增追加，不得重写）' % run_id)
        seen[run_id] = True
        missing = [f for f in REQUIRED_FIELDS if not rec.get(f)]
        if missing:
            problems.append('记录 %s 缺少字段：%s' % (run_id, ', '.join(missing)))
    return problems


def main():
    ap = argparse.ArgumentParser(description='决策日志工具')
    sub = ap.add_subparsers(dest='cmd')

    ap_add = sub.add_parser('append', help='追加一条决策记录')
    ap_add.add_argument('--ledger', required=True, help='ledger.jsonl 路径')
    ap_add.add_argument('--record', required=True, help='decision.json 路径')

    ap_list = sub.add_parser('list', help='列出决策记录')
    ap_list.add_argument('--ledger', required=True)
    ap_list.add_argument('--code', default=None)
    ap_list.add_argument('--since', default=None)
    ap_list.add_argument('--until', default=None)

    ap_verify = sub.add_parser('verify', help='校验日志')
    ap_verify.add_argument('--ledger', required=True)

    args = ap.parse_args()

    if args.cmd == 'append':
        record = read_record(args.record)
        if record is None:
            print('[FATAL] 读取决策记录失败：%s' % args.record, file=sys.stderr)
            return 1
        ok, why = append_record(args.ledger, record)
        print(json.dumps({'written': ok, 'reason': why,
                          'ledger': args.ledger}, ensure_ascii=False))
        return 0 if ok else 1

    if args.cmd == 'list':
        records, broken = load_ledger(args.ledger)
        picked = filter_records(records, args.code, args.since, args.until)
        for rec in picked:
            print(json.dumps(rec, ensure_ascii=False, sort_keys=True))
        print(json.dumps({'总数': len(records), '筛选后': len(picked),
                          '损坏行': broken}, ensure_ascii=False), file=sys.stderr)
        return 0

    if args.cmd == 'verify':
        records, broken = load_ledger(args.ledger)
        problems = verify(records, broken)
        if problems:
            print('[FAIL] 决策日志校验未通过：')
            for p in problems:
                print('  - %s' % p)
            return 1
        print('[PASS] 决策日志校验通过（%d 条记录）' % len(records))
        return 0

    ap.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())
