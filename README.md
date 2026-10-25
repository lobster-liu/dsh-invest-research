# dsh-invest-research

[![npm version](https://img.shields.io/npm/v/dsh-invest-research.svg?style=flat-square)](https://www.npmjs.com/package/dsh-invest-research)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)

> Multi-agent equity & fund research pipeline **skill plugin** for [DeepSeek Harness (DSH)](https://harness.deepseek.com).
> 同一包内提供**10 个 skill**，共用脱敏门禁与环境约定：
>
> | 类别 | skill | 用途 |
> |---|---|---|
> | 个股 | `stock-research` | 单只 A 股行情/估值/周期/政策分析 | 6 角色（协调员/数据员/政策员/估值周期员/风控员/审计员），双盲隔离 + 三轮审计 |
> | 基金重研究 | `fund-research` | **基金穿透式研究**（主动/指数/ETF/联接/FOF/QDII/债基）+ **可选同业对比层** | 7 角色 + 对比层 3 角色（peer-orchestrator/peer-builder/peer-red-team），五阶段 + 阶段 6 对比 |
> | 基金轻工作流 | `pick-funds`（入口）· `fund-screen` · `fund-profile` · `fund-watch` · `holdings-style` · `manager-profile` · `report-render` · `xlsx-author` | 筛选 / 单基金画像 / 经理画像 / 持仓风格 / 持续跟踪 / PDF·DOCX·XLSX 交付 | 单 agent 按技能逐步执行，产出带 `[披露]/[测算]/…` 溯源标签的交付物 |
>
> 最终都产出**每个数字带【来源|日期|口径|类型】、落盘前过 PII 脱敏**的研究报告。

**仅供研究参考,不构成投资建议。不接入任何交易通道,全程只读公开数据。**

## Install 安装

```bash
# 从 GitHub
dsh plugin --profile <profile-name> add github:lobster-liu/dsh-invest-research

# 或从本地目录 / zip 解包后
dsh plugin --profile <profile-name> add path/to/dsh-invest-research
```

> **v0.3.0 起包名由 `dsh-stock-research` 改为 `dsh-invest-research`**（加入了基金研究能力）。
> GitHub 旧地址会自动重定向；已安装旧版的用户请移除后按新名重装。
> **v0.4.0 起 `fund-research` 新增可选同业对比层**（阶段 6）：同一主题下多只基金"谁更优"，
> 由对比协调员亲自派发互相隔离的独立角色 agent 做跨基金对比 + 独立 red-team 质疑。

重启 DSH → 新会话里说 **"分析 600048"**（stock-research）或 **"分析基金 025490"**、**"穿透这只基金的持仓"**（fund-research）即触发；说 **"筛选基金"**、**"这只基金怎么样"**、**"基金经理画像"**、**"出一份 PDF 报告"** 则命中 pick-funds 套件。

## Quick check 安装自检

```bash
# 1) 个股取数冒烟(需可访问 push2.eastmoney.com;失败多为网络环境而非代码问题)
python assets/skills/stock-research/tools/fetch_data.py --code 600000 --out /tmp/sr/data.json
# 2) 基金取数冒烟(需可访问 fund.eastmoney.com)
python assets/skills/fund-research/tools/fetch_fund.py --code 025490 --out /tmp/fr/fund.json --peer-stocks 10
# 3) 基金取数器离线自测(35 条断言,不依赖网络,期望 exit 0)
python assets/skills/fund-research/tools/test_fund_tools.py
# 4) 脱敏门禁行为自检(27 场景,期望 exit 0)
python assets/skills/stock-research/tools/test_gate.py
# 5) 对比层工具离线自测(23 条断言,期望 exit 0;含 ETF/联接份额、短码补零、--track 仍解析锚点名、关键词截断、https 回退、列表外代码不误拒)
python assets/skills/fund-research/tools/test_peer_tools.py
# 统一入口:npm test 跑 21 条注册冒烟;npm run test:all 跑全部(21+27+30+14)
```

## What's inside

| 组成 | 说明 |
|---|---|
| `assets/skills/stock-research/SKILL.md` | 个股流程总纲 + 环境解析(`EQUITY_PY` / `EQUITY_SECRET_SCANNER` / `$RUN` / `$ARCHIVE`) |
| `assets/skills/stock-research/roles/*.md` ×6 | 各角色完整提示词(含 2026-10-15 真实事故教训固化:单一数据源、口径并列、先落盘再细化) |
| `assets/skills/stock-research/tools/fetch_data.py` | 东财双通道行情/历史取数 + 分位/最大回撤衍生计算;**空数据退出码 1** |
| `assets/skills/stock-research/tools/fetch_fundamentals.py` | **(v0.2.0)** 可选 akshare 财务基本面通道:ROE/每股净资产/负债率/现金流 + PE·PB 近一年真分位;未装 akshare 时退出码 1 不阻断主流程 |
| `install_akshare.ps1` / `requirements.txt` | **(v0.2.0)** 沙箱内离线装 akshare(Node fetch 下 wheel + `--no-index --find-links`),绕开 pip 平台临时目录 `WinError 5` 与 schannel 两个坑 |
| `assets/skills/fund-research/SKILL.md` | **(v0.3.0 / v0.4.0)** 基金流程总纲:五阶段 + 阶段6 对比层、10 章报告、5 个结论标签、三种情景、跟踪清单、条件式行动、铁律 11(对比层必由独立 agent 派发) |
| `assets/skills/fund-research/roles/*.md` ×10 | **(v0.3.0 / v0.4.0)** 协调员 + Agent1–Agent6 + 对比层 3 角色(`peer-orchestrator` / `peer-builder` / `peer-red-team`),统一提交格式 |
| `assets/skills/fund-research/tools/fetch_fund.py` | **(v0.3.0 / 版本自 v0.5.5 起从本插件根 `package.json` 读,回落值 `_VERSION_FALLBACK` 有测试断言同步)** 基金身份/净值/多期持仓/行业配置/债券持仓/规模份额/持有人/资产配置/经理/基准对比/重仓股快照;多通道降级,**空数据退出码 1** |
| `assets/skills/fund-research/tools/test_fund_tools.py` | **(v0.3.0)** 35 条离线断言(内联 fixture + 网络桩,零网络) |
| `assets/skills/fund-research/tools/peer_builder.py` | **(v0.5.5)** 同业筛选器:**脚本执行 3 条**(跟踪标的严格相等 / 仅被动型 / 非同一基金不同份额)+ **标记 1 条**(结构差异);**交易状态与份额类别一致性不执行**,写入 `agent_review_required[]` 交 Agent-P1 人工复核,**只筛不评**;候选支持 `--codes`(列表外代码先抓身份页兜底,类型仍未知时记 `type_unknown_codes[]` + `agent_review_required(type_unverified)`,不按非被动型误拒)/ `--keyword`(被动型预筛 + `--max-candidates>=1` 上限)/ `--track`(仍解析锚点简称,不静默关掉判据 C);基金列表源 https 优先、**抓取与解析失败都回退 http** |
| `assets/skills/fund-research/tools/comparator.py` | **(v0.4.0)** 对比矩阵生成器:读 `peers.json` + 各基金 `report.md`/`fund.json`,对齐已冻结结论、暴露口径冲突,**不重算指标** |
| `assets/skills/fund-research/tools/test_peer_tools.py` | **(v0.5.4)** 对比层 23 条离线断言(含 `某ETF` 不得判成 F 份额、`11839→011839` 补零、`--track` 不得让判据 C 失效、`--keyword` 预筛+截断+下限、https 连接层/解析层回退、列表外代码不得按非被动型误拒六项回归;纯逻辑 + 工作区临时目录 fixture,零网络) |
| `tools/sanitize_check.py` | 落盘前 PII 门禁:5 类泄漏规则 + 5 层公开信息白名单(财报科目/政策条款/金融术语/**基金公开披露**/否定声明);混合陷阱必拦 |
| `tools/test_gate.py` | 门禁行为自检 27 场景(真泄漏必拦/公开条款必放/基金披露必放/陷阱必拦) |
| `tools/run_pipeline.ps1` | Windows PowerShell 引导脚本(ASCII-only,PS 5.1 兼容) |

## pick-funds 分析师套件（v0.5.0 新增）

移植自 ZCode 官方插件 **pick-funds v0.1.1**，把原「1 agent + 7 skills」改为纯 skill 承载，
入口技能 `pick-funds` 承载工作模式路由、数据源优先级与共享护栏。

| 技能 | 触发场景 |
|---|---|
| `pick-funds` | 基金研究类任务入口；共享护栏 + **DSH 数据源映射** |
| `fund-screen` | 筛选基金 / 找基金 / 近一年收益前 10% |
| `fund-profile` | 基金画像 / XX 基金怎么样 |
| `fund-watch` | 基金跟踪 / 持仓基金有没有问题 / 规模异动 |
| `holdings-style` | 持仓分析 / 风格漂移 / 两只基金重合度 |
| `manager-profile` | 基金经理 / 经理画像 / 这个经理靠谱吗 |
| `report-render` | 出一份 PDF / 导出报告 / 存成 docx |
| `xlsx-author` | 表格类交付落成 .xlsx |

### 与 `fund-research` 的分工

要「筛 / 画像 / 盯 / 比 / 出报告」用本套件（单 agent 工作流）；要「穿透底层 + 多 agent
交叉验证 + 固定 10 章」用 `fund-research`。两者都只读公开数据、不出具投资建议。

### DSH 数据源映射

本套件按 DSH 原生方式接线：**无 MCP server 依赖**，直接走本插件自带取数脚本 + Web 检索兜底。

| 需要的数据 | DSH 取法 |
|---|---|
| 基金档案/净值/持仓/规模/份额/持有人/经理/费率/基准/重仓股 | 本插件 `fetch_fund.py`（`数据` / `持仓` / `净值序列` 等字段） |
| 指数/个股行情、板块、财务基本面 | 本插件 `fetch_data.py` + `web_fetch` |
| 基金经理变更公告、基金公司事件 | `web_search` + `web_fetch`（基金公司公告 / 巨潮 / 交易所披露页） |
| 定性背景（经理访谈、基金公司事件） | `web_search` + `web_fetch`（媒体档标 `[媒体]`） |
| 基金筛选（全市场按条件过滤） | **无等价脚本** → `web_search` + `web_fetch`（天天基金等筛选页），须在覆盖度写明引擎口径 |

没有对应能力时记 `源不可用` 并写入覆盖度区块，**不得静默跳到通用搜索兜底**。
`fetch_fund.py` 退出码 `1` 表示基金身份与净值都取不到，此时停止并如实报告，不带空数据继续。

### 依赖边界

- `report-render` 另需 `reportlab / matplotlib / pypdf / pypdfium2 / pillow / fonttools / pymupdf`
  （见 `assets/skills/report-render/scripts/requirements.txt`；`pymupdf` 为可选项，缺则字形覆盖
  检查自动跳过）与系统 CJK 字体；
- `xlsx-author` 需 `openpyxl`，公式重算校验走 headless LibreOffice（缺失时用技能定义的强制
  替代检查并如实标注，不假装通过）；
- `peer_builder.py` 基金列表源为 `https://fund.eastmoney.com/js/fundcode_search.js`，
  个别网络只放行 http，故**保留 `http://` 回退**（设计取舍，非缺陷）；连接层或解析层失败都会触发回退。
- 两者脚本均为纯 Python，随技能原样携带，无平台耦合。

### report-render / xlsx-author 完整度
本仓库技能**只要求 `soffice` 在 PATH 上**（探测用 `shutil.which("soffice")`）。缺失时
docx 排版量测 / xlsx 公式重算**如实降级**为"未测量 / 未经视觉验收 / recalc_unavailable"，
**不假装通过**。

```powershell
# 1) Python 依赖(dsh 自带 python 或 $PY) —— 已装并验证:
& "$PY" -m pip install -r assets/skills/report-render/scripts/requirements.txt
#    reportlab / matplotlib / pypdf / pypdfium2 / pillow / fonttools / pymupdf
#    → PDF 直出、图表、墨量/空白页校验、CJK 字形覆盖全部可用(无需 LibreOffice)

# 2) LibreOffice(仅 docx 排版量测 + xlsx 公式重算需要)。无管理员时用「管理镜像」解包:
#    winget 不可用的环境示例 —— 官方 mirror 下载 Win_x86-64 MSI 后:
#    msiexec /a "LibreOffice_X.Y.Z.msi" /qn TARGETDIR="D:\Users\...\LibreOffice"
#    !!! 坑:解包后 program\bootstrap.ini 里 InstallMode=<installmode>(未替换占位符)
#        会报"配置文件已损坏";改成 InstallMode=1 后 soffice.COM 通常可用,soffice.exe 不一定。
#        若仍报错,请用管理员权限正常安装,不要沿用管理镜像。
#    然后把 <target>\program 加入用户 PATH。

# 3) 自检:python assets/skills/report-render/scripts/selftest.py <输出目录>
#    PDF 半程应全过;docx 排版量测有无取决于步骤 2。
```
> 本机现状（2026-10-25）：Python 依赖已装齐；LibreOffice 三种安装方式（`winget` / 用户级 MSI /
> 管理镜像）均未稳定成功，已从用户 PATH 移除，docx/xlsx 校验走降级路径。**这不影响 PDF 交付
> 与数据正确性，只影响 docx 逐页视觉验收和公式重算校验两项。**

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
