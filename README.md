# MyInvestMarket A股市场评分系统

`MODEL_VERSION = v1.0_stable` 是当前稳定发布版。该版本冻结核心评分规则和 `risk_cap` 类型，后续只允许调参数、补数据源、补展示和补测试；如需新增风险上限逻辑分支，应升级新的模型版本。

## 评分目标

系统服务于股票账户，不按总资产做波动率缩放。输出核心是：

- `market_opportunity_score`：市场机会分，衡量趋势、宽度、流动性、资金、主线、估值和宏观环境。
- `crowding_penalty`：拥挤与脆弱性扣分，识别短线过热、资金分歧、估值偏贵、高波动、流动性枯竭。
- `pre_cap_market_position_score`：机会分扣除拥挤惩罚后的仓位分。
- `market_position_score`：经过风险上限后的最终股票账户仓位分。
- `recommended_equity_position_range`：最终建议权益仓位区间。

## 模块权重

| 模块 | 权重 | 作用 |
| --- | ---: | --- |
| 指数趋势 | 20 | 判断宽基趋势、MA20、5/20日涨跌和趋势确认。 |
| 市场宽度 | 15 | 判断上涨家数、行业扩散、中位数涨跌、强弱个股结构。 |
| 成交与流动性 | 10 | 判断指数量能比、中小盘活跃度和大盘承接。 |
| 资金与风险偏好 | 15 | 判断北向、主力资金及5日持续性。 |
| 主线强度 | 15 | 判断领涨行业、前五行业净流入、价量重合和主线连续性。 |
| 估值与再定价 | 15 | 使用宽基PE/PB/ERP便宜度，分数越高代表越便宜。 |
| 宏观与外部环境 | 10 | 参考中美利率、美元指数和汇率压力。 |

## 仓位映射

| 最终仓位分 | 股票账户权益仓位 |
| ---: | --- |
| 0-20 | 0%-20% |
| 20-35 | 20%-40% |
| 35-50 | 40%-60% |
| 50-65 | 55%-75% |
| 65-80 | 75%-90% |
| 80-100 | 90%-100% |

高分不等于无条件满仓。若估值、波动、资金退潮、爆量顶部或主线拥挤等风险上限触发，`market_position_score` 会被硬上限压低。

## 稳定版风险上限

`v1.0_stable` 固定以下 `risk_cap` 类型：

- `high_crowding_extreme`
- `high_crowding`
- `volume_blowoff_top`
- `sector_concentration_top`
- `capital_outflow_combo`
- `extreme_expensive_valuation`
- `expensive_valuation`
- `bubble_top_combo`
- `extreme_high_volatility`
- `high_volatility`
- `missing_valuation_data_hot_market`
- `missing_volatility_data_hot_market`
- `missing_core_risk_data_hot_market`
- `strong_index_weak_breadth`

多个风险上限同时触发时，系统按最低 `score_cap` 选择真正最严格的上限；如果 `score_cap` 相同，则 `severity` 更高者优先。评分记录会保留：

- `risk_caps`：全部触发的风险上限。
- `applied_cap`：最终生效的风险上限。
- `discarded_caps`：被更严格上限覆盖的风险上限。

## 发布锁定

稳定版通过回归测试锁定：

- 模型版本必须为 `v1.0_stable`。
- `risk_cap` 类型白名单不得漂移。
- 未在白名单中的 `risk_cap` 会直接报错。
- 真实历史快照 `data/market_snapshot_2026-06-18.json` 的核心评分、模块分、风险上限和最终仓位不得漂移。

## API

主要接口：

- `GET /api/index`：主页核心内容、稳定版元信息、评分摘要、仓位映射、风险概览和历史曲线数据。
- `GET /api/service`：服务版本、模型版本、稳定版冻结状态和允许的风险上限类型。
- `GET /api/history`：当前版本评分历史。
- `GET /api/history?include_legacy=true`：包含旧版本的完整历史。
- `GET /api/research/latest`：最新市场快照、评分和分析报告绑定结果。

建议每日收盘后执行系统更新，让最新快照、评分历史和分析报告保持一致。
