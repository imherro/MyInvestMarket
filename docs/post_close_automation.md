# MyInvestMarket 收盘后自动化

建议执行时间：工作日收盘后、主要数据源稳定后，例如 `16:30 Asia/Shanghai`。

当前 Codex 自动化：`a-3`，名称为 `MyInvestMarket市场研究收盘后更新`。

## 最短可用中文提示词

```text
执行 MyInvestMarket A股收盘后市场研究更新。

工作目录：C:\Users\kunpeng\Documents\MyInvestMarket

执行：
python .\scripts\run_post_close_update.py

要求：
1. 使用最新完整A股交易日数据更新市场快照、评分历史和市场研究报告；如果不是完整交易日、数据源未更新或脚本跳过，说明跳过原因。
2. 确认模型版本、仓位策略版本、配置策略版本与 /api/service 一致。
3. 验证 /api/index、/api/research/latest/market-score、/api/research/latest/market-analysis 可用且 run_id、basis_trade_date 一致。
4. 如服务未加载最新代码，重启 8011 服务后复验。
5. 若产生文件更新，完成测试、提交并推送 GitHub main；若没有更新，保持工作区干净。

最后用中文简报：基准交易日、run_id、市场机会分、拥挤惩罚、股票账户仓位分、推荐权益区间、配置状态、四仓配置区间、触发的风险上限、数据质量、API验证结果、commit 或跳过原因。
```

## 脚本行为

- 默认拒绝在脏工作区运行，避免把人工修改和每日数据更新混在一起。
- 使用 as-of 当日或之前的最新完整 A 股交易日。
- 若最新评分已经覆盖同一基准日且快照内容未变，不重复写入历史。
- 写入 `data/market_analysis_*.md` 市场研究报告。
- 验证 `/api/index`、`/api/research/latest/market-score`、`/api/research/latest/market-analysis`。
- `/api/index.market_data_status` 会对比本地最新完整市场快照、最新评分基准日和研究报告绑定关系；如果某个完整交易日已有数据但缺少对应研究，首页第一行会显示醒目预警。
- `/api/index.allocation_policy` 输出 `allocation_policy_v2` 四仓配置：β核心仓、α主动仓、防御因子仓、流动性仓。
- 有更新时提交并推送到 `origin main`。

## 手工测试

```powershell
python .\scripts\run_post_close_update.py --as-of 2026-06-22 --allow-dirty --no-git
```
