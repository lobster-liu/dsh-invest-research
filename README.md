# dsh-stock-research

> Multi-agent A-share research pipeline **skill plugin** for [DeepSeek Harness (DSH)](https://harness.deepseek.com).
> 6 个 AI 角色按固定流程协作:协调员调度、数据员取数、政策员梳官方政策、估值周期员打分、
> 风控员独立证伪(与估值员**双向盲审**)、审计员逐数核对(三轮门禁),
> 最终产出**每个数字带【来源|日期】、落盘前过 PII 脱敏**的研究报告。

**仅供研究参考,不构成投资建议。不接入任何交易通道,全程只读公开数据。**

## Install 安装

```bash
# 从 GitHub(发布后)
dsh plugin --profile <profile-name> add github:<your-user>/dsh-stock-research

# 或从本地目录 / zip 解包后
dsh plugin --profile <profile-name> add path/to/dsh-stock-research
```

重启 DSH → 新会话里说 **"分析 600048"** 或 **"跑一遍行情分析流水线"** 即触发。

## Quick check 安装自检

```bash
# 1) 取数冒烟(需可访问 push2.eastmoney.com;失败多为网络环境而非代码问题)
python assets/skills/stock-research/tools/fetch_data.py --code 600000 --out /tmp/sr/data.json
# 2) 脱敏门禁行为自检(15 场景,期望 exit 0)
python assets/skills/stock-research/tools/test_gate.py
```

## What's inside

| 组成 | 说明 |
|---|---|
| `assets/skills/stock-research/SKILL.md` | 流程总纲 + 环境解析(`EQUITY_PY` / `EQUITY_SECRET_SCANNER` / `$RUN` / `$ARCHIVE`) |
| `roles/*.md` ×6 | 各角色完整提示词(含 2026-10-15 真实事故教训固化:单一数据源、口径并列、先落盘再细化) |
| `tools/fetch_data.py` | 东财双通道行情/历史取数 + 分位/最大回撤衍生计算;**空数据退出码 1** |
| `tools/sanitize_check.py` | 落盘前 PII 门禁:5 类泄漏规则 + 4 层公开信息白名单(财报科目/政策条款/金融术语/否定声明);混合陷阱必拦 |
| `tools/test_gate.py` | 门禁行为自检(真泄漏必拦/公开条款必放/陷阱必拦) |
| `tools/run_pipeline.ps1` | Windows PowerShell 引导脚本(ASCII-only,PS 5.1 兼容) |

## Requirements
- DSH ≥ 0.2.0-rc(skill 注册走 Host `skills` 服务;**无该服务时插件加载为 no-op,不会报错**)
- Python 3.10+(DSH 自带 runtime 直接可用;取数零第三方依赖,akshare 可选)
- 网络可达 `push2.eastmoney.com` / `push2his.eastmoney.com`(行情);政策核对建议搭配 [`dsh-web-search-pro`](https://github.com/anweat/dsh-web-search-pro)(免费 anonymous 源,本插件按 `read.fetch`-为主设计)

## 环境变量(全部可选)
| 变量 | 作用 |
|---|---|
| `EQUITY_PY` | 指定 Python 解释器(默认自动解析 DSH 自带 runtime) |
| `EQUITY_SECRET_SCANNER` | 外接凭据扫描器路径(如 audit-secrets.py);未设则明示 skipped,内置 PII 规则照常生效 |
| `EQUITY_WORK` | run 产物根目录(默认当前工作目录 `./equity-runs/`) |

## Privacy
- 报告**禁止出现**个人持仓/成本/资金量——落盘前 `sanitize_check.py` 强制拦截(退出码非 0 禁止写入,无绕过开关);
- 政策原文中的条款数字(如"单户上限100万元")是公开信息,白名单放行且**不改写**;
- 所有产物默认留在用户工作区,是否归档进个人笔记库(Vault/Obsidian)由用户显式配置 `$ARCHIVE`。

## License
MIT
