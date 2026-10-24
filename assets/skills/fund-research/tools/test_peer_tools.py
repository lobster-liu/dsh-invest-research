#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_peer_tools.py —— peer_builder.py / comparator.py 离线自测（零网络）。

覆盖 peer_builder 的 7 个纯逻辑函数（跟踪标的解析 / 被动判定 / 份额类别 /
类型后缀剥离 / 主体名剥离 / 代码归一 / 结构判定）
与 comparator 的 2 个纯函数（报告标签提取 / 对比矩阵构建）。

回归重点（上游 v0.4.0 缺陷，2026-10 修复）：
  · '某ETF' 曾被 detect_share_class 判成 'F' 份额 → 现必须返回 ''
  · '11839' 曾原样查询导致"未找到" → 现必须归一为 '011839'

fixture 用工作区内临时目录（不用 %TEMP%，DSH 沙箱拒绝平台临时目录 → PermissionError 13）。

运行：python test_peer_tools.py   （期望 exit 0）
"""
import importlib.util
import itertools
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

_seq = itertools.count()


def _load(name):
    path = os.path.join(HERE, name)
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pb = _load('peer_builder.py')
cp = _load('comparator.py')


def _mk_tmpdir():
    """建临时目录做 fixture。不用 tempfile.mkdtemp：它创建的目录在 Windows 下
    ACL 不允许再建子目录（WinError 5）。改用 os.makedirs 一次建多层，
    落到 cwd 或环境变量 PEER_TEST_TMPDIR 指定的可写目录。"""
    base = os.path.abspath(os.environ.get('PEER_TEST_TMPDIR') or '.')
    d = os.path.join(base, 'peer_test_' + str(next(_seq)))
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# peer_builder
# ---------------------------------------------------------------------------
def test_parse_tracking_target_ok():
    html = ('<p>业绩比较基准：<a>中证人工智能主题指数收益率×95%</a></p>\n'
            '<p>跟踪标的：</a>中证人工智能主题指数</p>')
    assert pb.parse_tracking_target(html) == '中证人工智能主题指数'


def test_parse_tracking_target_fallback():
    """无「跟踪标的」字段时回退到业绩比较基准。"""
    html = '业绩比较基准<a href="x">沪深300指数×90%</a>'
    got = pb.parse_tracking_target(html)
    assert got is not None and '沪深300' in got


def test_parse_tracking_target_none():
    assert pb.parse_tracking_target('<p>无相关字段</p>') is None
    assert pb.parse_tracking_target('') is None


def test_is_passive():
    assert pb.is_passive('指数型-股票') is True
    assert pb.is_passive('指数型-其他') is True
    assert pb.is_passive('股票指数型') is True
    assert pb.is_passive('ETF-场内') is True
    assert pb.is_passive('混合型-偏股') is False
    assert pb.is_passive('股票型') is False
    assert pb.is_passive('债券型-长债') is False
    assert pb.is_passive('') is False
    assert pb.is_passive(None) is False


def test_detect_share_class():
    assert pb.detect_share_class('某指数A', '000001') == 'A'
    assert pb.detect_share_class('某指数C', '000002') == 'C'
    assert pb.detect_share_class('某指数E', '000003') == 'E'
    assert pb.detect_share_class('某指数I', '000004') == 'I'
    assert pb.detect_share_class('某指数（无后缀）', '000005') == ''


def test_detect_share_class_type_tail_not_share_class():
    """回归：类型/联接缩写结尾的末位字母绝不能当份额类别。"""
    assert pb.detect_share_class('某ETF', '000010') == ''
    assert pb.detect_share_class('某LOF', '000011') == ''
    assert pb.detect_share_class('某QDII', '000012') == ''
    assert pb.detect_share_class('某行业指数', '000013') == ''
    # 类型缩写 + 真份额字母 → 仍能识别
    assert pb.detect_share_class('某ETF联接A', '000014') == 'A'
    assert pb.detect_share_class('天弘中证人工智能主题ETF发起式联接C', '000015') == 'C'
    # 币种括号不干扰
    assert pb.detect_share_class('某指数A（人民币）', '000016') == 'A'
    # 真空份额 F 仍识别
    assert pb.detect_share_class('某指数F', '000017') == 'F'


def test_strip_share_class():
    """同基金不同份额剥完后主体名必须相等；ETF 等类型缩写不得被剥掉。"""
    a = pb.strip_share_class('天弘中证人工智能主题ETF发起式联接A')
    c = pb.strip_share_class('天弘中证人工智能主题ETF发起式联接C')
    assert a == c == '天弘中证人工智能主题ETF发起式联接'
    assert pb.strip_share_class('某ETF') == '某ETF'      # 类型缩写不剥
    assert pb.strip_share_class('某指数A（人民币）') == '某指数'
    assert pb.strip_share_class('') == ''
    # 不同基金主体名必须不同（防误剔）
    assert pb.strip_share_class('华夏沪深300指数A') != pb.strip_share_class('易方达沪深300指数A')


def test_normalize_code():
    """回归：短码必须补前导零，否则查询直接「未找到」。"""
    assert pb.normalize_code('11839') == '011839'
    assert pb.normalize_code(' 11839 ') == '011839'
    assert pb.normalize_code('011839') == '011839'
    assert pb.normalize_code('') == ''
    assert pb.normalize_code(None) == ''


def test_normalize_codes():
    """逗号串归一：补零 + 去空 + 保序去重（幂等，防 PowerShell 剥零）。"""
    assert pb.normalize_codes('11839,023461') == ['011839', '023461']
    assert pb.normalize_codes(' 11839 , 23461 ') == ['011839', '023461']
    assert pb.normalize_codes('11839,,11839') == ['011839']
    assert pb.normalize_codes('') == []


def test_detect_structure():
    assert pb.detect_structure('天弘中证人工智能主题ETF发起式联接A') == '发起式联接'
    assert pb.detect_structure('某联接基金A') == '联接'
    assert pb.detect_structure('某ETF联接A') == '联接'
    assert pb.detect_structure('某ETF') == 'ETF'
    assert pb.detect_structure('某指数基金') == '指数'


# ---------------------------------------------------------------------------
# comparator
# ---------------------------------------------------------------------------
def _mk_report(label, decl='已由 8 个子代理独立产出', caveat=''):
    return ('## 协调员汇总\n'
            '调度声明：\n' + decl + '。\n\n'
            '**结论标签：' + label + '**\n\n'
            + caveat + '\n')


def test_extract_report_tags():
    md = _mk_report('等待验证', caveat='存在口径缺陷：样本口径与全组合不一致')
    tag = cp.extract_report_tags(md)
    assert tag['conclusion_label'] == '等待验证'
    assert '子代理' in tag['schedule_decl']
    assert '口径' in tag['caveats_found']


def test_extract_report_tags_empty():
    tag = cp.extract_report_tags('')
    assert tag['conclusion_label'] == ''
    assert tag['schedule_decl'] == ''


def test_build_matrix():
    """工作区内临时目录 fixture：锚点 + 一只 peer，验证 entries 与 distinct_tracks。"""
    base = _mk_tmpdir()
    try:
        os.makedirs(os.path.join(base, '012733'))
        os.makedirs(os.path.join(base, '011839'))
        with open(os.path.join(base, 'peers.json'), 'w', encoding='utf-8') as f:
            json.dump({
                'anchor': {'code': '012733'},
                'anchor_tracking_target': '中证人工智能主题指数',
                'peers': [{'code': '011839'}],
            }, f, ensure_ascii=False)
        with open(os.path.join(base, '012733', 'report.md'), 'w', encoding='utf-8') as f:
            f.write(_mk_report('等待验证'))
        with open(os.path.join(base, '012733', 'fund.json'), 'w', encoding='utf-8') as f:
            json.dump({'跟踪标的': '中证人工智能主题指数'}, f, ensure_ascii=False)
        with open(os.path.join(base, '011839', 'report.md'), 'w', encoding='utf-8') as f:
            f.write(_mk_report('等待验证'))
        with open(os.path.join(base, '011839', 'fund.json'), 'w', encoding='utf-8') as f:
            json.dump({'tracking_target': '中证人工智能主题指数'}, f, ensure_ascii=False)

        m = cp.build_matrix(base)
        assert len(m['entries']) == 2
        assert set(m['distinct_tracks']) == {'中证人工智能主题指数'}
        assert set(m['distinct_labels']) == {'等待验证'}
        assert {e['code'] for e in m['entries']} == {'012733', '011839'}
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_build_matrix_ignores_no_data_dir():
    """无 report.md 与 fund.json 的子目录（如 _indump）应被忽略。"""
    base = _mk_tmpdir()
    try:
        os.makedirs(os.path.join(base, '_indump'))
        os.makedirs(os.path.join(base, '012733'))
        with open(os.path.join(base, 'peers.json'), 'w', encoding='utf-8') as f:
            json.dump({'anchor': {'code': '012733'}}, f)
        m = cp.build_matrix(base)
        assert len(m['entries']) == 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


def main():
    tests = [(k, v) for k, v in list(globals().items())
             if k.startswith('test_') and callable(v)]
    failed = []
    for name, fn in tests:
        try:
            fn()
            print('PASS ' + name)
        except Exception as e:
            failed.append((name, repr(e)))
            print('FAIL ' + name + ': ' + repr(e))
    print(f'{len(tests)-len(failed)}/{len(tests)} passed')
    if failed:
        for n, e in failed:
            print('  FAILED ' + n + ' -> ' + e)
        return 1
    print('✅ peer_builder / comparator 行为正确')
    return 0


if __name__ == '__main__':
    sys.exit(main())