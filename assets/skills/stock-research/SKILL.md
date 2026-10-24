---
name: stock-research
description: 多智能体协同的 A 股行情分析流水线。6 角色（协调员/数据员/政策员/估值周期员/风控员/审计员）按固定流程协作，双盲隔离+三轮审计+落盘前脱敏门禁，输出逐数带【来源|日期】的分析报告。当用户要求"分析某只股票/板块"、"跑行情分析流水线"、"多 agent 分析 XX"时使用。
---

# A 股行情分析 · 多智能体流水线（stock-research）

> 本 skill 由插件 `dsh-invest-research` 提供，`roles/`、`tools/` 与本文件同包发布。

## 何时使用
- 用户要求分析某只 A 股或某个板块的行情、估值、周期、政策
- 用户明确说"多 agent"/"多 bot 协同"/"跑流水线"
- 需要带来源可追溯、经独立风控挑战、经审计核对的严谨分析

## 环境解析（执行任何命令前先做一次，全程复用）
- `$BASE`   —— 本 skill 的 base 目录（DSH 加载 skill 时会在提示中给出）
- `$TOOLS`  = `$BASE/tools`（fetch_data.py / fetch_fundamentals.py / sanitize_check.py / run_pipeline.ps1 均在此，**产物绝不写入插件目录**）
- `$PY`     —— Python 解释器，按优先级：
  1. 环境变量 `EQUITY_PY`；
  2. DSH 自带运行时 `%DSH_HOME%\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe`（Windows，有 numpy/pandas）；
  3. PATH 中的 `python`。
- `$RUN`    —— 本次运行输出目录：`<用户当前工作区>\equity-runs\<标的>-<yyyyMMdd-HHmmss>\`
- `$ARCHIVE`—— 可选归档根（如 Obsidian 库）；**未配置则跳过归档步骤，只保留 `$RUN`**。
  若配置了 git 同步的笔记库：报告虽经脱敏，写入仍会扩散到该库的所有同步端——
  **用户未明确要求写入其个人笔记库之前，不得归档**。

## 核心原则（不可违反）
1. **数字必须有来源**：每个数字带【来源|日期】，无来源即退回，最多重试 2 次，仍失败列入「数据缺口」，**禁止估算填补**。
2. **两轮审计不可跳过**：数据后一轮、风控后一轮；可加第三轮终审。
3. **估值员与风控员双向隔离**：估值员不产目标价、看不到风控结论；风控员看不到估值结论。
4. **落盘前必须过脱敏门禁**：`sanitize_check.py` 退出码非 0 → 禁止写入。
5. **报告不含个人持仓**：成本、仓位、资金量一律不写（会暴露个人头寸，属高危 PII）。
6. **单一数据源锁定**：一次运行只认本次 `$RUN/data.json`；任何角色不得改读其他 run、`smoke*`、`_` 开头目录（2026-10-15 真实事故教训，详 `roles/auditor.md` G 项）。
7. **口径并列披露**：盘中 vs 收盘、累计 vs 单月、合并 vs 归母等同一指标多口径时，**必须并列披露并声明所用口径**，禁止只挑一个。
8. **结尾必须声明**：仅供研究参考，不构成投资建议。

## 角色文件（派发子代理时，读取对应文件作为其完整提示词）
```
roles/orchestrator.md  协调员：调度/汇总/归档，不取数不判断
roles/data.md          数据员：fetch_data.py 双通道取数，只输出 JSON
roles/policy.md        政策员：gov.cn 站内检索 + read.fetch 原文核对
roles/valuation.md     估值周期员：分位/周期/四维打分/触发式建仓条件
roles/risk.md          风控员：≥3 条反驳+证伪条件，独立回撤测算
roles/auditor.md       审计员：只读核对 A-G 七类，PASS/FAIL+问题清单
```

## 执行流程
### 1. 建立 run 目录（runid 带秒，防并发撞号）
```powershell
$runid = '<标的>-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
$RUN = (Get-Location).Path + "\equity-runs\$runid"
New-Item -ItemType Directory -Path $RUN -Force
```

### 2. 阶段一：数据员 + 政策员（**并行派发**）
- 数据员：读 `roles/data.md`。先调取数器：
  `& "$PY" "$TOOLS/fetch_data.py" --code <代码> --out "$RUN/data.json" --history-days 1300`
  （**退出码 1 = 全通道失败，禁止带空数据继续**；财务科目缺失按 data.md 的 read.fetch 指引补，见环境限制节）
  **若已装 akshare**，紧接着取基本面（可选增强，退出码 1 不阻断主流程）：
  `& "$PY" "$TOOLS/fetch_fundamentals.py" --code <代码> --out "$RUN/fundamentals.json"`
  取到的 ROE / 每股净资产 / 资产负债率 / 现金流 / PE·PB 分位可显著减少「数据缺口」。
- 政策员：读 `roles/policy.md`，官网站内检索 + `read.fetch` 抓原文。

### 3. 阶段二：审计员第一轮（**不可跳过**）
读 `roles/auditor.md`，核对 `$RUN/data.json` + `policy.md`。PASS → 进阶段三；FAIL → 退回对应角色，最多 2 次。

### 4. 阶段三：估值周期员
读 `roles/valuation.md`。**只喂审计通过的数据**。产出 `valuation.md`（不产目标价）。

### 5. 阶段四：风控员（与估值员盲审隔离）
读 `roles/risk.md`，喂 `data.json` + `policy.md`；**明确禁止读取 valuation.md**。产出 `risk.md`。

### 6. 阶段五：审计员第二轮
核对 valuation.md + risk.md：算术、口径、隔离性、脱敏、数据源正确性。FAIL 处置同上。

### 7. 阶段六：协调员汇总
读 `roles/orchestrator.md`，按固定 8 章节生成 `report.md`（一句话结论/核心数据/政策时间轴/周期判断/打分表/建仓计划/风险证伪/数据缺口）。

### 8. 阶段七：门禁 + 可选归档（**门禁不可绕过**）
```powershell
& "$PY" "$TOOLS/sanitize_check.py" "$RUN" --json
```
- 退出码 0 → 若 `$ARCHIVE` 已配置，将 `report.md/valuation.md/risk.md/audit*.md/policy.md/data.json`（不含 `_` 开头文件）复制到 `$ARCHIVE\<标的>-<名称>-<日期>\`；
- 非 0 → 退回重写，**不得绕过、不得删规则放行**。

## 模型分配（成本优化）
| 角色 | 档位 | 理由 |
|---|---|---|
| 数据员、政策员 | 便宜快速 | 取数与检索，量大但简单 |
| 估值、风控、审计、协调 | 强推理 | 严谨判断与交叉核验 |

## ⚠️ 环境限制（派发子代理前必读，2026-10-15 实测）
1. **内置 `web_search` 在多数环境不可用**（DeepSeek 搜索需 API key，免费账户登录通道对子代理不生效，报 `WEB_PROVIDER_CREDENTIAL_MISSING`）。
   → 全部角色改用 `web_call`（推荐搭配插件 `dsh-web-search-pro`，免费 anonymous 源即可）：
   - **`read.fetch`：极可靠**，直连官网原文——主路径；
   - **`search.run`：仅辅助**，中文政府站点覆盖差（`site:pbc.gov.cn` 硬约束 0 结果），且其"needs covered N/N"为启发式假阳性，结论必须回原文核实。
2. **行情接口间歇性不可达**（网络中间层干扰时 `fetch_data.py` 会 FAILED）。→ 脚本自带重试+双通道+**空数据退出码 1**；失败时终止报告"数据缺口"，不要带空跑。
3. **akshare 已可离线安装（v0.2.0 起）**。DSH 沙箱会拦截 pip 在平台临时目录里的
   build/unpack 操作（`WinError 5 拒绝访问`），因此**不要**直接 `pip install akshare`。
   用随包脚本一次装成（Node fetch 下载 wheel + 本地离线安装，避开平台 temp）：
   ```powershell
   & "$BASE/install_akshare.ps1" -VenvPython <venv 的 python.exe> -WheelsDir <工作区内目录>
   ```
   装成后 `tools/fetch_fundamentals.py` 可用（财务分析指标 22×86 / 财务摘要 80×88 /
   PE·PB 近一年真分位）。**未装 akshare 时该脚本退出码 1 并说明原因，其余流程照常跑。**
   已知限制：akshare 1.19.x 已移除银行监管指标接口（不良率/拨备覆盖率/资本充足率），
   这些字段请用 `fetch_data.py` 的 HTTP 通道或列为数据缺口。
4. **子代理核算类任务必须"先落盘再细化"**（真实教训：两个子代理反复试算、不落盘、耗尽上下文后成果全丢，见 LESSONS.md）。派发时明确要求：先写结论文件（可标注"核算中"），再继续补充。

## 数据质量红线（来自 LESSONS 的浓缩版）
- 冒烟/测试数据一律 `_` 前缀目录；正式角色禁止扫描；
- 多会话共用工作区：runid 带秒、绝不清空他人 run 目录；
- 报告只认本次 run 的 data.json；样本窗口/口径差异必须显式声明；
- 政策原文中的条款数字（"单户上限100万元"等）不得改写——门禁已知白名单处理。

## 验证安装（首次使用先跑这两步）
```powershell
# 1) 取数冒烟(应输出记录数>0, exit 0; 全通道失败=网络环境问题)
& "$PY" "$TOOLS/fetch_data.py" --code 600000 --out "$env:TEMP\sr-smoke\data.json"
# 2) 门禁自检(3 类断言: 真泄漏必拦 / 政策财报条款必放 / 混合陷阱必拦)
& "$PY" "$TOOLS/test_gate.py"
```
`test_gate.py` 退出码 0 = 脱敏门禁在本机行为正确。

## 免责
本 skill 仅生成研究参考报告，不构成任何投资建议；不接入任何下单通道，分析全程只读公开数据。
