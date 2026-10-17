# dsh-invest-research

> Multi-agent equity & fund research pipeline **skill plugin** for [DeepSeek Harness (DSH)](https://harness.deepseek.com).
> 同一包内提供**两个 skill**，共用脱敏门禁与环境约定：
>
> | skill | 用途 | 角色 |
> |---|---|---|
> | `stock-research` | 单只 A 股行情/估值/周期/政策分析 | 6 角色（协调员/数据员/政策员/估值周期员/风控员/审计员），双盲隔离 + 三轮审计 |
> | `fund-research` | **基金穿透式研究**（主动/指数/ETF/联接/FOF/QDII/债基） | 7 角色（协调员 + 基金画像穿透/宏观政策/行业趋势/公司估值/绩效归因/反方审查），五阶段流程 |
>
> 最终都产出**每个数字带【来源|日期|口径|类型】、落盘前过 PII 脱敏**的研究报告。

**仅供研究参考,不构成投资建议。不接入任何交易通道,全程只读公开数据。**

## Install 安装

```bash
# 从 GitHub(发布后)
dsh plugin --profile <profile-name> add github:<your-user>/dsh-invest-research

# 或从本地目录 / zip 解包后
dsh plugin --profile <profile-name> add path/to/dsh-invest-research
```

> **v0.3.0 起包名由 `dsh-stock-research` 改为 `dsh-invest-research`**（加入了基金研究能力）。
> GitHub 旧地址会自动重定向；已安装旧版的用户请移除后按新名重装。

重启 DSH → 新会话里说 **"分析 600048"**（stock-research）或 **"分析基金 025490"**、**"穿透这只基金的持仓"**（fund-research）即触发。

## Quick check 安装自检

```bash
# 1) 个股取数冒烟(需可访问 push2.eastmoney.com;失败多为网络环境而非代码问题)
python assets/skills/stock-research/tools/fetch_data.py --code 600000 --out /tmp/sr/data.json
# 2) 基金取数冒烟(需可访问 fund.eastmoney.com)
python assets/skills/fund-research/tools/fetch_fund.py --code 025490 --out /tmp/fr/fund.json --peer-stocks 10
# 3) 基金取数器离线自测(30 条断言,不依赖网络,期望 exit 0)
python assets/skills/fund-research/tools/test_fund_tools.py
# 4) 脱敏门禁行为自检(27 场景,期望 exit 0)
python assets/skills/stock-research/tools/test_gate.py
```

## What's inside

| 组成 | 说明 |
|---|---|
| `assets/skills/stock-research/SKILL.md` | 个股流程总纲 + 环境解析(`EQUITY_PY` / `EQUITY_SECRET_SCANNER` / `$RUN` / `$ARCHIVE`) |
| `assets/skills/stock-research/roles/*.md` ×6 | 各角色完整提示词(含 2026-10-15 真实事故教训固化:单一数据源、口径并列、先落盘再细化) |
| `assets/skills/stock-research/tools/fetch_data.py` | 东财双通道行情/历史取数 + 分位/最大回撤衍生计算;**空数据退出码 1** |
| `assets/skills/stock-research/tools/fetch_fundamentals.py` | **(v0.2.0)** 可选 akshare 财务基本面通道:ROE/每股净资产/负债率/现金流 + PE·PB 近一年真分位;未装 akshare 时退出码 1 不阻断主流程 |
| `install_akshare.ps1` / `requirements.txt` | **(v0.2.0)** 沙箱内离线装 akshare(Node fetch 下 wheel + `--no-index --find-links`),绕开 pip 平台临时目录 `WinError 5` 与 schannel 两个坑 |
| `assets/skills/fund-research/SKILL.md` | **(v0.3.0)** 基金流程总纲:五阶段、10 章报告、5 个结论标签、三种情景、跟踪清单、条件式行动 |
| `assets/skills/fund-research/roles/*.md` ×7 | **(v0.3.0)** 协调员 + Agent1–Agent6 完整提示词,统一 7 项提交格式 |
| `assets/skills/fund-research/tools/fetch_fund.py` | **(v0.3.0)** 基金身份/净值/多期持仓/行业配置/债券持仓/规模份额/持有人/资产配置/经理/基准对比/重仓股快照;多通道降级,**空数据退出码 1** |
| `assets/skills/fund-research/tools/test_fund_tools.py` | **(v0.3.0)** 30 条离线断言(内联 fixture + 网络桩,零网络) |
| `tools/sanitize_check.py` | 落盘前 PII 门禁:5 类泄漏规则 + 5 层公开信息白名单(财报科目/政策条款/金融术语/**基金公开披露**/否定声明);混合陷阱必拦 |
| `tools/test_gate.py` | 门禁行为自检 27 场景(真泄漏必拦/公开条款必放/基金披露必放/陷阱必拦) |
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
