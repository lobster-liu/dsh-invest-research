# Changelog

## 0.2.0 — 2026-10-16
- **akshare 财务基本面通道**（本次核心新增，直接命中 v0.1.0 两次实测的数据缺口）：
  - `tools/fetch_fundamentals.py`:akshare 取财务分析指标(ROE/每股净资产/资产负债率/
    流动·速动比率/每股经营现金流)、财务摘要(归母净利/营收/扣非/现金流 多期)、
    **PE(TTM)·PB 近一年真分位**(百度估值接口,补上 v0.1.0 只有"区间位置"没有"时间排名"
    的缺陷)。与 data.json 同契约(逐数带来源、取不到填 null 禁止估算、逐接口容错)。
    **akshare 未装时退出码 1 并说明原因,不阻断主流程(HTTP 兜底照常)**。
  - `install_akshare.ps1`:沙箱内离线装 akshare 的固定脚本(Node fetch 下 wheel 到工作区
    + `pip --no-index --find-links` 本地装,绕开 DSH 沙箱对平台临时目录的 `WinError 5`
    拦截 + schannel TLS 握手失败两个坑;jsonpath(sdist) 用 `tarfile filter='data'` 手动装)。
  - `requirements.txt`:pin 到 akshare 1.19.1 实测通过的依赖版本。
- SKILL.md 环境限制节改写:从"不建议装 akshare"更新为"已可离线装,用随包脚本,附沙箱根因
  与已知限制"(akshare 1.19.x 已移除银行监管指标接口,不良率/拨备覆盖率/资本充足率
  仍走 fetch_data.py HTTP 通道或列为数据缺口)。

## 0.1.0 — 2026-10-15
- 首次发布:6 角色多智能体 A 股研究流水线 skill(协调员/数据员/政策员/估值周期员/风控员/审计员)
- `tools/fetch_data.py`:东财双通道取数(HTTP 兜底零依赖,akshare 存在即自动启用)、重试、
  价格分位/最大回撤衍生计算、**空数据退出码 1**(禁止带空跑)
- `tools/sanitize_check.py`:落盘前 PII 门禁(持仓/成本/资金/盈亏/账户 5 类规则 +
  金融术语/政策条款/财报科目/否定声明 4 层白名单;混合陷阱必拦);
  可选外接凭据扫描器(环境变量 `EQUITY_SECRET_SCANNER`)
- `tools/test_gate.py`:15 场景门禁行为自检(安装验证用)
- `tools/run_pipeline.ps1`:ASCII-only(PS 5.1 安全),Python 三级解析(`EQUITY_PY` >
  `DSH_HOME` 自带运行时 > PATH),产物只写当前工作目录
- 流程纪律:双盲隔离、两轮审计不可跳过、runid 带秒防并发、单一数据源锁定、
  多口径并列披露、角色任务"先落盘再细化"
- 已知环境适配:内置 `web_search` 在多数环境不可用 → 角色一律用 `web_call`
  (搭配 `dsh-web-search-pro` 时 `read.fetch` 为主、`search.run` 仅辅助)
