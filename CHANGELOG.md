# Changelog

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
