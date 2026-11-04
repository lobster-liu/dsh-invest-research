# BACKLOG

已决定「不做单独文档版」之后，纯文档增量攒在这里，随下一个功能版本一起发（届时通知下游重新 pin）。

## 待并入（下一个功能版）

- [ ] `assets/skills/_shared/references/fee-rules-2026.md` §5（校验与降级）：补一句「渠道与费用种类只接受中文枚举
      `直销`/`代销`、`认申购费`/`销售服务费`；传英文枚举按 `fee-E7` 处理」。
      背景：下游首次抽查时传了 `direct` / `subscription_fee`，11 条断言全抛 E7；`fund_cost.py:124-128` 的报错
      本身已列出合法取值，属调用侧错误，不是工具缺口。
- [ ] `assets/skills/fund-watch/SKILL.md` Step 6：给 `validate_fee_leg` 补一个带 `holding_days` 的调用示例
      （代销、2027 后两支各一例），现在只有签名没有示例。

## 已决定不做

- **不加英文枚举别名**：渠道与费用种类是登记维度，同一概念两种拼写会在报告里造出口径歧义。下游同意。
- **`_VERSION_FALLBACK` 改为运行时读 `package.json`**：仓库已有 `_resolve_version()`；下游安装布局
  （`~/.qoder-cn/skills/`，装的是单文件 ROOT A）没有 `package.json`，新逻辑仍会回落，churn 换不来收益；
  四层 `dirname` 只到 `assets/`，要五层才回到包根。

## 接口级（需单独立项，不属文档增量）

`fee-rules-2026.md` §7 列的三类剩余边界：份额批次不拆（一个 `holding_days` 管一个账户）、跨期必须手工先
`split_holding_period`、转换/红利再投/部分赎回后的持有期连续性不建模。要动就得改 `validate_fee_leg` 的输入
形态（批次列表或 `contract_regime` 枚举），属接口变更，不在补丁范围内。
