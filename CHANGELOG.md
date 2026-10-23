# Changelog

## 0.4.0 — 2026-10-23
- **新增 `fund-research` 对比层（阶段 6，跨基金同业对比）**：给定锚点 + 候选同业，先由
  `peer_builder.py` 按「跟踪标的一致 + 被动属性 + 同份额类别 + 开放申购」筛出合法同业
  （**只筛不评**，不构成"谁更优"的判断），再由**具备 spawn 能力的协调员亲自派发**
  互相隔离的独立角色 agent 做跨基金对比（宏观/行业/估值/绩效各一，互不共享结论防锚定），
  最后由独立 `peer-red-team` 逐条质疑、协调员按证据质量裁决。
- **新增 3 个角色文件**：`roles/peer-orchestrator.md`（对比协调员）、
  `roles/peer-builder.md`（同业筛选，只筛不评）、`roles/peer-red-team.md`（对比反方审查：
  同源假验证 / 样本冒充全组合 / 循环论证 / 被忽略的反向证据）。
- **新增 2 个工具**：`tools/peer_builder.py`（同业筛选器）、`tools/comparator.py`
  （对比矩阵生成器，读 `peers.json` + 各基金 `report.md`/`fund.json`，**不重算指标**、
  只对齐已冻结结论并暴露口径冲突）。
- **新增 `tools/test_peer_tools.py`**：对比层 10 条离线断言，覆盖 peer_builder 的
  跟踪标的解析/被动判定/份额类别/结构判定与 comparator 的报告标签提取/对比矩阵构建
  （零网络，fixture 用工作区临时目录——不用 `%TEMP%`，DSH 沙箱拒绝平台临时目录，
  且 `tempfile.mkdtemp` 建的目录在 Windows 下 ACL 不允许再建子目录）。
- **SKILL.md 新增铁律 11（对比层细则）**：跨基金对比必须由具备 spawn 能力的协调者
  亲自派发互相隔离的独立角色 agent + 独立 red-team；**不得把对比层交给无法派生子代理的
  执行者，否则退化为单模型自证**——此时必须如实声明，不得声称真实多智能体。
- **修 `peer_builder.py` 两个坑**（2026-10-22 实测踩到）：① 搜索候选全量抓跟踪标的过慢
  → 改为**逐只只抓锚点** + 候选仅在名字含目标关键词时抓；② 同名不同份额误判同业
  → 显式校验份额类别 + 标记结构差异为"不可比较维度"。
- **发布合规（第三方插件市场标准）**：
  - `package.json` 补 `author` / `homepage` / `bugs` / `publishConfig.access`；
  - `LICENSE` 版权方由旧包名 `dsh-stock-research contributors` 同步为 `dsh-invest-research contributors`；
  - `cordis.patch.yml` 与 `README.md` 的 `github:<user>/...` 占位符改为真实仓库
    `github:lobster-liu/dsh-invest-research`；
  - `.npmignore` 与 `package.json` `files` 排除 `__pycache__` / `*.pyc`；
  - `npm test` 保留 21 条注册冒烟；新增 `npm run test:python` 与 `npm run test:all`
    统一验证入口（21+27+30+10 条断言）；
  - `README.md` 补 badges、对比层说明与自检命令。

## 0.3.1 — 2026-10-17
- **修复 `test/smoke.mjs` 裸跑必挂**（Qoder 侧复核发现）：ROOT 默认 `'.'` 时
  `'file://' + './lib/skill.js'` 拼出 host 段为 `.` 的非法 file URL → `ERR_MODULE_NOT_FOUND`，
  只有传绝对路径才能跑出 21 条断言，换机器/换 shell 极易误判"测试挂了"。
  修法：默认仓库根由 `import.meta.url` 反推（不依赖 cwd），动态 import 改用
  `pathToFileURL(resolve(...)).href`；package.json 加 `"scripts": { "test": "node test/smoke.mjs" }`
  作为可执行入口（`npm test`、仓库内任意位置裸跑、显式传路径三种方式均验证通过）。
  仅动 `test/smoke.mjs` + `package.json`（version/scripts 两处），运行时代码与取数/门禁脚本零改动。

## 0.3.0 — 2026-10-17
- **修复外部复核（Qoder 侧）发现的 3 项问题**：
  - **P1（阻断）** `install_akshare.ps1` 原为 UTF-8 无 BOM，PowerShell 5.1 按 GBK 解码中文串
    导致 parse 失败（line 100「字符串缺少终止符」）——加 UTF-8 BOM 修复，`ParseFile` 复验 0 错。
    ⚠️ 维护约定：**该文件含中文，任何后续编辑保存都必须保持 BOM**（本次修复中内容改完
    BOM 又被无 BOM 工具冲掉过一次，靠复验抓回）；`run_pipeline.ps1` 保持 ASCII-only 无需 BOM。
    原注释「实测 100% 通过（2026-10-16）」已更正为 pwsh 7.x 宿主实测——5.1 宿主此前连 parse
    都过不去，该声明对 5.1 不成立。
  - **P2（功能）** `run_pipeline.ps1` run 目录拼接错误：`'equity-runs' + $runid` 粘连成
    `equity-runs600048-…`，缺中间层级 → 改为 `Join-Path (Join-Path … 'equity-runs') $runid`，
    与 SKILL.md 的 `<工作区>\equity-runs\<标的>-<时间戳>\` 约定一致。
  - **P3（发布）** `install_akshare.ps1` 删除硬编码个人绝对路径（泄露用户名/安装位置且他机必失败），
    node 探测改为四级查找：`$env:NODE` → `$env:DSH_HOME` 下自带 runtime（3 种 Windows 布局）→
    `$env:LOCALAPPDATA` 候选 → PATH；全部取不到则 throw 并列出三种可执行修法。
- **包名改为 `dsh-invest-research`**（原 `dsh-stock-research`）：v0.3.0 加入基金研究能力后，
  旧名已不能覆盖 `fund-research` skill。两个 skill 名不变（`stock-research` / `fund-research`），
  插件层统一为单一 provider `dsh-invest-research`。GitHub 仓库同步改名后旧地址
  自动 301 重定向；已安装旧版的请移除后按新名重装。
- **新增第二个 skill `fund-research`（基金穿透式研究流水线）**，与 `stock-research` 同包发布、
  共用同一套 PII 门禁与环境约定。7 角色：协调员 + Agent1 基金画像与持仓穿透 / Agent2 宏观政策 /
  Agent3 行业趋势 / Agent4 重仓公司与估值 / Agent5 基金管理与绩效 / Agent6 风险与反方审查。
  五阶段流程：身份与基准日 → 冻结共享事实底稿 → 四路并行独立初稿（互不引用防锚定）→
  反方审查 + 定向补证一次 → 协调员按证据质量裁决（不按多数投票、保留分歧）。
  固定 10 章报告 + 5 个结论标签 + 三种情景 + 5–8 项跟踪清单 + 条件式行动参考。
- **`lib/skill.js` 泛化为多 skill 注册**：`registerSkillsWhenAvailable(ctx, dirs)` 按目录批量注册，
  两个 skill 统一归属 provider `dsh-invest-research`（`PLUGIN_NAME` 常量，不再按目录名推导）；
  单个 SKILL.md 损坏只 warn，其余照常注册；
  保留 `registerSkillWhenAvailable()` 单 skill 兼容入口。`test/smoke.mjs` 扩到 21 条断言
  （两 skill 独立注册 / 无 skills 服务降级 / 坏文件隔离 / provider 不串台）。
- **`assets/skills/fund-research/tools/fetch_fund.py`**（新增）：基金身份、净值序列、多期持仓、
  行业配置、债券持仓、规模份额、持有人结构、资产配置、基金经理、申赎状态、基准对比、
  重仓股快照。多通道降级（东财 pingzhongdata / 基金主页 / f10 归档 / 腾讯行情），
  取不到即列「未取得的指标」，**空数据退出码 1**。
  实测修掉的坑：① 东财时间戳是北京时间的当日零点，取 UTC 会整体错一天，
  导致净值与指数错位、跟踪误差/捕获率失真（已 +8h）；
  ② f10 报告期优先取页面「截止至：YYYY-MM-DD」，比从「2026年2季度」推算可靠；
  ③ 季度披露 >20 条判为半年报/年报全量，否则只是前十大；
  ④ `--history-days` 默认 0（全部历史），否则「成立以来」会静默退化成样本区间
     （另修 `_days_between` 返回 0 被 `or 999` 吞掉的 falsy-zero bug——净值首日恰为成立日时
     正是最该标「成立以来」的情况，却总被错标成「样本区间」）；
  ⑤ 联接/FOF 显式标注「f10 股票持仓不含目标 ETF 与子基金」，防重复计入；
  ⑥ 主页持仓无显式报告期时的推断：只认「季度末 + 25 日历日 ≤ 最新净值日」的最新季度末
     （正推最近的季度末会在 10 月中旬得出尚未披露的三季报 09-30，实际持仓是 06-30 的）。
- **`tools/test_fund_tools.py`**（新增）：30 条离线断言（内联 fixture + 网络桩 + 绊线，
  零网络），覆盖解析、陈旧判定、f10 解析、区间/年化/回撤/分位/基准对比。
- **`sanitize_check.py` 扩展**：新增基金公开披露白名单（净值/阶段收益/规模/份额/持有人/
  资产配置/跟踪误差/持仓占比/重仓股估值等），并把「公司盈利」等公司层面表述与
  第一人称盈亏区分开（真泄漏仍必拦）。`test_gate.py` 从 15 场景扩到 27 场景，含 D 组
  「基金公开披露必放」与「公司豁免不得掩护第一人称盈亏」混合陷阱。

## 0.2.1 — 2026-10-16
- **修复真宿主上 skill 无法加载**(`skill "stock-research" is unknown or no longer
  available`)。根因是提供者契约理解错误:宿主注册表取正文时调用的是
  `provider.get(candidate, options)`(**candidate 对象**,见 `@deepseek-ai/dsh-skill`
  的 `match.provider.get(match.candidate, options)`),而 `get()` 却把入参当**字符串**
  与技能名比较,恒不相等 → 恒返回 `undefined` → 工具报"unknown or no longer available"。
  现在同时接受 candidate 对象与纯名字两种形态。
- **回归测试补齐**:`test/smoke.mjs` 新增 `get(candidate)` 与"外部 candidate"两个用例
  (11/11)。原来只用字符串调用 `get()`,所以这个 bug 在 9/9 全绿下漏过了宿主验证。

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
