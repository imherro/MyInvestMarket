# MyInvestMarket A股市场研究系统

当前模型版本：`v3.3_position`。系统服务于股票账户，不做总资产配置，也不再用 8% 目标波动率缩放官方股票仓位。波动率只作为风险扣分、风险上限和提示。

## 核心输出

- `market_opportunity_score`：市场机会分，衡量趋势、宽度、流动性、资金、主线、估值和宏观环境。
- `crowding_penalty`：拥挤与脆弱性扣分，识别短线过热、资金分歧、估值偏贵、高波动、流动性枯竭。
- `pre_cap_market_position_score`：机会分扣除拥挤惩罚后的仓位分。
- `market_position_score`：经过风险上限后的最终股票账户仓位分。
- `recommended_equity_position_range`：股票账户权益风险资产区间。
- `market_regime_layer`：市场区制层，区分底部吸筹、主升扩张、高位派发、下行收缩。
- `market_trend_layer`：趋势结构层，区分趋势初期、强趋势、趋势末期、趋势转弱。
- `risk_engine`：连续风险分和风险折扣，先做软衰减，再由风险上限兜底。
- `position_model`：基础仓位分经过趋势乘数、区制乘数、风险折扣后的仓位函数。
- `allocation_policy`：五仓配置建议，解释风险资产和防御资产分别放在哪里。

## 分数含义

市场机会分不是仓位分。牛市越热，机会分可能较高，但估值、波动、主线拥挤、爆量顶部和资金退潮会通过拥挤惩罚与风险上限压低最终仓位分。熊市底部若估值便宜、宽度止跌、波动回落、资金改善，最终仓位分才会提高。

## 模块权重

| 模块 | 权重 | 作用 |
| --- | ---: | --- |
| 指数趋势 | 20 | 判断宽基趋势、MA20、5/20日涨跌和趋势确认。 |
| 市场宽度 | 15 | 判断上涨家数、行业扩散、中位数涨跌、强弱个股结构。 |
| 成交与流动性 | 10 | 判断指数量能比、中小盘活跃度和大盘承接。 |
| 资金与风险偏好 | 15 | 判断北向、主力资金及5日持续性。 |
| 主线强度 | 15 | 判断领涨行业、前五行业净流入、价量重合和主线连续性。 |
| 估值与再定价 | 15 | 使用宽基 PE/PB/ERP 便宜度，分数越高代表越便宜。 |
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

## 五仓配置

`allocation_policy_v1` 把股票账户拆成五个仓位：

| 仓位 | 资产 | 作用 |
| --- | --- | --- |
| 核心仓 | 宽基 ETF | 宏观 beta 底座 |
| 主线仓 | 行业/主题 ETF | 产业 beta 增强 |
| 龙头仓 | 龙头个股 | 资金 alpha 弹性 |
| 收益防御仓 | 红利低波/自由现金流 ETF | 低波动权益防御 |
| 现金替代仓 | 短融 ETF/货币工具 | 等待权与回撤缓冲 |

总仓位分决定股票账户承担多少风险，五仓配置决定风险放在哪里。

## 风险上限

模型固定以下 `risk_cap` 类型：

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

多个风险上限同时触发时，系统按最低 `score_cap` 选择真正最严格的上限；如果 `score_cap` 相同，则 `severity` 更高者优先。

## API

统一目录：

- `GET /api`：公开接口目录，返回系统名称、版本、说明、`base_url`、`docs`、推荐入口、安全边界、接口分组和 `total_endpoints`。该接口只做说明，不触发重计算、写入、交易或同步。

文档入口：

- `GET /docs`：浏览器版接口目录。
- `GET /redoc`：浏览器版精简接口目录。
- `GET /openapi.json`：OpenAPI 风格机器可读接口摘要。

主要数据接口：

- `GET /api/index`：主页核心内容、评分摘要、五仓配置、仓位映射、风险概览和历史曲线数据。
- `GET /api/service`：服务版本、模型版本、配置策略版本和允许的风险上限类型。
- `GET /api/history`：当前版本评分历史。
- `GET /api/history?include_legacy=true`：包含旧版本的完整历史。
- `GET /api/research/latest`：最新市场快照、评分和研究报告绑定结果。
- `GET /api/research/latest/market-analysis`：最新 Markdown 市场研究报告。
- `GET /api/research/latest/model-validation`：最新回测与模型验证报告。
- `GET /api/research/latest/model-health`：模型漂移、滚动表现、健康分和校准触发建议。
- `GET /api/research/latest/strategy-robustness`：因果代理分析、样本外验证、压力测试和策略稳健性评分。

写入接口：

- `POST /api/score`：根据本地最新市场快照记录一次评分，会更新本地评分历史；不下单、不同步 GitHub、不连接交易系统。

## 模型验证

Phase 6 增加回测与验证层，用来检查策略是否只是“看起来合理”，还是能被历史记录重复验证。

```powershell
python .\scripts\backtest_engine.py --include-legacy
python .\scripts\report_generator.py --include-legacy
python .\scripts\calibration_trigger.py --include-legacy
python .\scripts\robustness_score.py --include-legacy
```

验证层固定使用至少 1 个交易日延迟的仓位信号，避免用当天收盘评分解释当天收盘到收盘收益。当前真实 v3 历史样本仍短，因此报告会明确标出样本不足，不把短样本结果包装成统计结论。

## 生产保护层

Phase 7 增加模型漂移与健康监控：

- `scripts/drift_detector.py`：检测 market regime、trend transition、risk penalty 分布漂移。
- `scripts/rolling_monitor.py`：计算滚动 Sharpe、滚动回撤和区制命中率。
- `scripts/model_health.py`：输出 `health_score` 与 `healthy / warning / degraded` 状态。
- `scripts/calibration_trigger.py`：当漂移过高或健康分过低时，只给出校准建议，不自动改实盘参数。

## 策略可信性层

Phase 8 增加策略稳健性验证：

- `scripts/causal_analysis.py`：用 permutation test、分组效应和风险干预代理分析策略信号是否有统计解释力。
- `scripts/oos_validator.py`：按时间严格切分 train / validation / test，检查样本外表现和未来信息泄露。
- `scripts/stress_tester.py`：模拟极端牛市、极端熊市、流动性枯竭和高频震荡。
- `scripts/robustness_score.py`：综合 OOS、因果代理、稳定性和压力测试输出 `robustness_score`。

这些结果是研究和风控证据，不是自动交易指令；短样本时系统会降低可部署判断。

## 每日更新

工作日收盘后执行：

```powershell
python .\scripts\run_post_close_update.py
```

脚本会获取最新完整交易日数据、生成评分记录、写入研究报告、验证 API，并在有更新时提交推送到 `origin main`。
每日更新也会生成 `data/model_validation_latest.md` 和 `data/model_validation_latest.json`，供页面和外部系统读取。
