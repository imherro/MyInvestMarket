# MyInvestMarket A股市场研究系统

当前模型版本：`v3.4_contrarian`。系统服务于股票账户，不做总资产配置，也不再用 8% 目标波动率缩放官方股票仓位。波动率只作为风险扣分、风险上限和提示。

## A-FEAR v1 市场恐慌系统

系统新增独立的日频 `A-FEAR v1`，以 0～100 衡量当前恐慌强度。它与趋势、估值互不替代，第一期只做观察和预警，不直接修改官方股票仓位分。

```text
A-FEAR = 300/1000 ATM 30日IV百分位 × 40%
       + 20日下行波动率百分位 × 20%
       + 市场宽度恐慌百分位 × 25%
       + 300/1000尾部跌幅百分位 × 15%
```

- 历史窗口：750个交易日，最低正式发布样本250日。
- 期权：中金所沪深300 `IO` 与中证1000 `MO`，使用认购认沽平价估算远期，Black-76反解ATM IV，再按总方差插值到固定30日。
- 输出：A-FEAR、1日变化、3日变化、恐慌等级、恐慌阶段、300/1000分化和完整组件依据。
- 安全边界：高恐慌不等于立即抄底；v1不下单、不改变仓位建议。
- 完整设计契约：`docs/a_fear_v1.md`。

## Cycle Dataset v1

系统新增独立的月频 `cycle_dataset_v1`，作为后续牛熊周期研究引擎的 Point-in-Time 原始数据层。当前阶段只生成和审计数据：不计算周期分、不改变 v3.4 官方仓位、不新增 API，也不改动 A-FEAR。

- 覆盖：2010 年 1 月至最近完整自然月，每月以最后一个 A 股交易日为基准日。
- 域：宽基估值、盈利/宏观字段（含官方制造业 PMI 发布日 PIT）、长周期趋势，以及可选 A-FEAR 快照。
- 严格 PIT：每个值保存观测/公告日，只使用不晚于基准日的信息；财务公告晚于基准日时不可见。
- 缺失规则：历史国债收益率或全市场财务 PIT 数据源不可用时，字段保留 `available=false` 和原因，不以中性值替代。
- 设计和运行说明：[docs/cycle_dataset_v1.md](docs/cycle_dataset_v1.md)。

### Cycle Dataset v1 Final Freeze

Cycle Dataset v1 的输入契约已经冻结到 `2026-08`：

- [契约与模型输入注册表](data/cycle_dataset_contract_v1.json)
- [字段可用性矩阵](data/cycle_dataset_feature_availability_v1.json)
- [黄金样本回归点](data/cycle_dataset_golden_spots_v1.json)
- [冻结清单与 SHA-256](data/cycle_dataset_freeze_manifest_v1.json)
- [完整契约说明](docs/cycle_dataset_contract_v1.md)

运行 `python scripts/validate_cycle_dataset_contract.py` 可重验契约、PIT 结构、缺失边界、黄金样本和冻结哈希；运行 `python scripts/validate_cycle_dataset_contract.py --generate` 可在数据更新后重新生成上述审计产物。结构冻结通过不代表数据新鲜度通过；当前清单会如实记录两者状态。

### Cycle Engine v1 Evidence Vector

Phase 1 只把冻结数据转换为可追溯的月频 Evidence Vector，不计算周期分、牛熊状态、权重或仓位。生成前会强制验证冻结契约，结果和审计见 [docs/cycle_engine_features_v1.md](docs/cycle_engine_features_v1.md)、`data/cycle_engine_features_v1.json` 和 `data/cycle_engine_features_audit_v1.json`。

`Cycle Earnings PIT v1.1` 已用 `Tushare.income_vip` 补齐全 A 与非金融 A 的利润金额聚合同比。当前期只采用累计合并报表（`report_type=1`），上年同期优先使用当时已披露的调整后合并报表（`report_type=4`），不会混入单季或母公司口径；月末优先选择披露覆盖率不低于 70% 的最新季度，并以相同公司集合同比。缓存为 append-only，新增季度和最新季度的新披露版本会追加，历史记录不被改写。它仍是研究数据，不影响当前官方 v3.4 仓位输出。

### Cycle Engine v1 Domain Signals

Phase 2 将冻结 Evidence 去重压缩为估值、盈利、PMI 确认、长期趋势和独立 A-FEAR overlay 五类域状态，不生成综合分、牛熊状态机、仓位或交易信号。生成器、审计产物和规则说明见 [docs/cycle_engine_domain_signals_v1.md](docs/cycle_engine_domain_signals_v1.md)、`data/cycle_engine_domain_signals_v1.json` 和 `data/cycle_engine_domain_signals_audit_v1.json`。

### Cycle Engine v1 Ex-post Evaluation Targets

事后评价层已与 Evidence Vector 隔离，使用冻结数据中的 CSI300、CSI500 月末收盘价生成 3/6/12/24 个自然月的未来收益、路径最好/最差收益、未来最大回撤和到达月份。它明确标记 `evaluation_only=true`、`uses_future_information=true`，不生成周期分、标签、权重或仓位，也不得作为模型输入。

运行 `python scripts/cycle_engine_evaluation_targets.py --generate` 可生成评价目标与审计文件：`data/cycle_engine_evaluation_targets_v1.json`、`data/cycle_engine_evaluation_targets_audit_v1.json`。不完整的未来窗口保留为 `target_available=false` 和空值；宽基代理从 100 起按 CSI300/CSI500 月收益各 50% 复利，不平均指数点位。说明见 [docs/cycle_engine_evaluation_targets_v1.md](docs/cycle_engine_evaluation_targets_v1.md)。

### Cycle Engine v1 Feature Diagnostics

Phase 3 诊断层只把已通过 readiness 的 model candidate 与 Evaluation target 按月份连接，输出描述性 Spearman、固定 rank bucket、三个固定历史阶段和同月冗余矩阵。它不产生 score、feature ranking、recommendation、状态、权重或仓位；12/24 个月结果因高度重叠，仅作描述性诊断。运行 `python scripts/cycle_engine_feature_diagnostics.py --generate`，说明见 [docs/cycle_engine_feature_diagnostics_v1.md](docs/cycle_engine_feature_diagnostics_v1.md)。

Phase 4 walk-forward 诊断按 `as_of_month` 严格截断未来目标，针对 6/12/24 个月收益和最大回撤输出连续特征相关性、布尔特征 true/false 中位数差、36 个已实现样本门槛、最新可用起点和稳定性/符号翻转统计；仅作样本外描述性研究，不产生模型输入或交易信号。运行 `python scripts/cycle_engine_walk_forward_diagnostics.py --generate`，说明见 [docs/cycle_engine_walk_forward_diagnostics_v1.md](docs/cycle_engine_walk_forward_diagnostics_v1.md)。

Phase 4.1 使用固定自然月取模的 6/12/24 个月 non-overlap cohorts，分别输出连续特征与 Boolean 特征在 forward return / max drawdown 上的 cohort 统计、稳定性摘要和与重叠结果的描述性对照。所有 cohort 均保留，小样本输出 `null`；本层不产生选股、状态、权重、阈值、仓位或交易信号。运行 `python scripts/cycle_engine_nonoverlap_diagnostics.py --generate`，说明见 [docs/cycle_engine_nonoverlap_diagnostics_v1.md](docs/cycle_engine_nonoverlap_diagnostics_v1.md)。

## 核心输出

- `market_opportunity_score`：市场机会分，衡量趋势、宽度、流动性、资金、主线、估值和宏观环境。
- `crowding_penalty`：拥挤与脆弱性扣分，识别短线过热、资金分歧、估值偏贵、高波动、流动性枯竭。
- `pre_overlay_market_position_score`：趋势、区制和连续风险折扣后的仓位分，尚未应用深熊逆向 β 地板。
- `contrarian_beta_overlay`：深熊赔率逆向模块，低估、深回撤、拥挤不高且资金未踩踏时，只抬高 β核心仓。
- `pre_cap_market_position_score`：应用逆向 β 地板后的扣风险上限前仓位分。
- `market_position_score`：经过风险上限后的最终股票账户仓位分。
- `recommended_equity_position_range`：股票账户权益风险资产区间。
- `market_regime_layer`：市场区制层，区分底部吸筹、主升扩张、高位派发、下行收缩。
- `market_trend_layer`：趋势结构层，区分趋势初期、强趋势、趋势末期、趋势转弱。
- `risk_engine`：连续风险分和风险折扣，先做软衰减，再由风险上限兜底。
- `position_model`：基础仓位分经过趋势乘数、区制乘数、风险折扣后的仓位函数。
- `allocation_policy`：四仓配置建议，解释风险资产和流动性资产分别放在哪里。

## 分数含义

市场机会分不是仓位分。牛市越热，机会分可能较高，但估值、波动、主线拥挤、爆量顶部和资金退潮会通过拥挤惩罚与风险上限压低最终仓位分。熊市底部若估值便宜、深回撤已经出现、拥挤不高且资金没有踩踏，`contrarian_beta_overlay` 可以把仓位分抬到深熊赔率地板；这部分只进入 β核心仓宽基 ETF，不解锁 α主动仓。

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

## 四仓配置

`allocation_policy_v2` 把股票账户拆成四个仓位：

| 仓位 | 资产 | 作用 |
| --- | --- | --- |
| β核心仓（宽基ETF） | 沪深300 / 中证A500 / 中证500 / 纳指等宽基 ETF | 市场 beta 底盘 |
| α主动仓（行业ETF + 龙头个股） | 主线行业 ETF + 龙头个股 | 主动超额收益 |
| 防御因子仓（红利/低波/自由现金流） | 红利、低波、自由现金流、质量因子 | 权益防御与质量暴露 |
| 流动性仓（货币/短债） | 货币、短债、现金管理工具 | 等待权、回撤缓冲和再平衡弹药 |

核心公式：

`风险资产总仓位 = β核心仓 + α主动仓 + 防御因子仓`

`流动性仓 = 100% - 风险资产总仓位`

总仓位分先决定股票账户承担多少风险，再由四仓配置决定风险放在哪里。`allocation_policy_v1` 的旧历史会在展示层折算为四仓：核心宽基映射到 β核心仓，主线 ETF + 龙头合并为 α主动仓，收益防御映射到防御因子仓，现金替代映射到流动性仓。

深熊赔率逆向模块生效时，四仓配置会进入“深熊赔率期”：提高风险资产内部的 β核心仓占比，压低 α主动仓占比，并继续保留流动性仓作为回撤缓冲和再平衡弹药。

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

### 周期仓位回测

周期引擎回测已单独输出到 [web/cycle-engine-backtest.html](web/cycle-engine-backtest.html)，首页周期模块提供入口；机器调用使用 `GET /api/cycle-engine/backtest`。回测只读取冻结的周期政策、月度周期数据和上证图表数据，采用“月末信号、下一月收益兑现”的月度收盘代理，展示区间下限、中位数、上限三种仓位方案，并保留逐月状态、仓位、净收益、基准净值和审计结果。

当前回测不是精确的下一交易日成交回测：周期数据只有月度收盘，无法还原信号后的第一个交易日价格；不含分红、ETF跟踪误差、滑点、税费和真实成交价。结果只用于检查规则行为，不构成投资建议。

统一目录：

- `GET /api`：公开接口目录，返回系统名称、版本、说明、`base_url`、`docs`、推荐入口、安全边界、接口分组和 `total_endpoints`。该接口只做说明，不触发重计算、写入、交易或同步。

文档入口：

- `GET /docs`：浏览器版接口目录。
- `GET /redoc`：浏览器版精简接口目录。
- `GET /openapi.json`：OpenAPI 风格机器可读接口摘要。

主要数据接口：

- `GET /api/dashboard`：首页决策台的精简摘要，只返回当前决策、双时间尺度状态、核心依据、风险提醒和近况曲线，不返回完整历史。
- `GET /api/index`：主页核心内容、当前研究基准日、盘感观察、数据/研究新鲜度状态、评分摘要、四仓配置、仓位映射、风险概览和历史曲线数据。
- `GET /api/service`：服务版本、模型版本、配置策略版本和允许的风险上限类型。
- `GET /api/history`：当前版本评分历史。
- `GET /api/history?include_legacy=true`：包含旧版本的完整历史。
- `GET /api/research/latest`：最新市场快照、评分和研究报告绑定结果。
- `GET /api/research/latest/market-analysis`：最新 Markdown 市场研究报告。
- `GET /api/research/latest/model-validation`：最新回测与模型验证报告。
- `GET /api/research/latest/model-health`：模型漂移、滚动表现、健康分和校准触发建议。
- `GET /api/research/latest/strategy-robustness`：因果代理分析、样本外验证、压力测试和策略稳健性评分。
- `GET /api/fear/latest`：最新 A-FEAR、变化、等级、阶段和数据质量。
- `GET /api/fear/history`：完整 A-FEAR 历史，支持 `start_date`、`end_date`。
- `GET /api/fear/components/latest`：最新四组件、底层指标和300/1000恐慌差。
- `GET /api/fear/status`：数据日期、样本门槛、置信度和新鲜度。
- `GET /api/fear/audit/latest`：最新历史深度、分数边界、组件相关性和跳变审计。

## Web 工作台

首页 `/` 现在是“今日决策台”，只回答基准日、当前执行权益区间、战略周期锚、战术状态、盘面观察和待处理提醒。完整内容按用途拆分到专题页：

- `/research.html`：市场评分、七大模块、仓位依据和评分历史。
- `/risk.html`：A-FEAR、风险上限、恐慌组件和数据质量。
- `/cycle.html`：周期引擎 200 个月状态与战略权益区间。
- `/allocation.html`：股票账户 β核心、α主动、防御因子、流动性四仓。
- `/cycle-engine-backtest.html`：周期仓位回测、净值、回撤、敏感性和逐月记录。
- `/methodology.html`：研究分层、数据链、审计边界和接口入口。

周期引擎和日度市场评分在首页并列展示：周期引擎是战略锚，日度模型是战术状态；两者没有未经定义的强行合成分数。

写入接口：

- `POST /api/score`：根据本地最新市场快照记录一次评分，会更新本地评分历史；不下单、不同步 GitHub、不连接交易系统。

## 参数审计

- `python .\scripts\audit_contrarian_beta_overlay.py`：生成深熊逆向 β 模块参数审计，检查估值、回撤、拥挤、资金踩踏、波动率和强度阈值边界，并输出 JSON/Markdown 报告。
- `python .\scripts\build_a_fear_dataset.py --trading-days 1`：更新最新交易日 A-FEAR；默认同时扫描最近30个交易日并逐日补齐缺失原始观测。可用 `--gap-scan-trading-days 60` 扩大补洞窗口，或用 `--no-fill-gaps` 进行单日诊断。
- `python .\scripts\audit_a_fear_v1.py`：审计历史深度、分数边界、组件相关性、跳变频率和最新极端读数一致性。

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
每条评分记录会同步保存 `market_observation` 盘感观察，并在 Markdown 研究报告、Web 首页和 `/api/index.summary.market_observation` 中展示，用于复盘当日主线强弱、市场宽度、传统权重反抽和反转确认度。
