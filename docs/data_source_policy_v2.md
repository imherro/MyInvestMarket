# 数据源策略 v2

## 目标

日更研究不依赖通达信或同花顺桌面客户端。远程同花顺接口作为行情增强源，现有 Tushare、AKShare 和 FRED 按字段继续承担补充、全市场聚合和宏观数据职责。

## 路由

| 数据类型 | 主源 | 回退/补充 | 说明 |
| --- | --- | --- | --- |
| 指数历史行情 | 同花顺 `index history` | Tushare `index_daily` | 周期趋势、波动率优先使用同花顺；单个指数不支持时逐项回退 |
| 指数快照 | 同花顺 `index snapshot` | Tushare | 当前快照验证入口 |
| 全市场个股日行情 | Tushare `daily` | 不静默替代 | 用于涨跌家数、中位数涨跌幅和市场宽度聚合 |
| 涨跌停池 | Tushare | 同花顺 `limit-up/down-pool` | 仅在 Tushare 失败时使用同花顺；保留来源备注 |
| 资金流、行业排名 | Tushare | 不静默替代 | 需要统一历史口径和字段定义 |
| 当前估值 | Tushare `index_dailybasic` | 不静默替代 | 历史估值分位仍依赖现有缓存和口径 |
| 宏观数据 | FRED、AKShare、Eastmoney | 按现有策略 | 不假定同花顺覆盖宏观和点时数据 |

## 运行要求

同花顺适配层调用已安装的 `hithink-finance` CLI，并使用其安全凭据配置。它只执行远程只读命令，不调用交易接口，也不写本地 DuckDB。未配置 `HITHINK_FINANCE_API_KEY`、CLI 不存在或请求失败时，指数指标自动回退 Tushare。

通达信 TQ 仍可作为独立的可选探测源，但不再是本项目日更运行的前置条件。

## 审计字段

每个指数指标保留 `source` 字段；快照的 `data_quality.sources_used` 会记录 `HiThink.index.history` 或 `Tushare.index_daily`。回退原因写入 `data_quality.notes`，不会把回退结果伪装成同花顺数据。

## 当前验证

2026-09-03 已验证同花顺远程接口可以返回上证指数快照、指数历史和跌停池；北证 50 当前代码目录未识别，因此按设计回退 Tushare。
