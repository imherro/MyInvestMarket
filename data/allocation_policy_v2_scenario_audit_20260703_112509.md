# allocation_policy_v2 场景审计

- 生成时间: 2026-07-03T11:25:09+08:00
- 配置策略版本: `allocation_policy_v2`
- 场景数量: 6
- 总体结论: 通过

## 审计口径

- 检查四个一级仓位是否固定为 `beta_core / alpha_active / defensive_factor / liquidity`。
- 检查 `流动性仓 = 100% - 风险资产总仓位`。
- 检查 `β核心仓 + α主动仓 + 防御因子仓` 的中位数是否接近风险资产总仓位中位数。
- 针对熊末、主升、深熊逆向、牛末、顶部反抽、极端杀跌分别设置直觉约束。

## 场景结果

| 场景 | 状态 | 风险资产 | β核心 | α主动 | 防御因子 | 流动性 | 结论 |
|---|---|---:|---:|---:|---:|---:|---|
| 熊末低估但趋势未确认 | 弱修复期 | 20%-40% | 10%-20% | 0%-5% | 9%-15% | 60%-80% | 通过 |
| 健康主升共振 | 低拥挤强趋势期 | 90%-100% | 46%-50% | 40%-43% | 4%-7% | 0%-10% | 通过 |
| 深熊赔率逆向加仓 | 深熊赔率期 | 40%-60% | 30%-41% | 0%-4% | 11%-15% | 40%-60% | 通过 |
| 牛末泡沫冲顶 | 高位过热风控 | 20%-40% | 8%-15% | 1%-5% | 11%-21% | 60%-80% | 通过 |
| 顶部反抽但风控压制 | 高位过热风控 | 40%-60% | 18%-24% | 3%-8% | 19%-28% | 40%-60% | 通过 |
| 极端杀跌 | 防守期 | 0%-20% | 0%-7% | 0%-2% | 3%-12% | 80%-100% | 通过 |

## 逐项检查

### 熊末低估但趋势未确认

底部便宜不等于直接满仓，优先提高 beta 和防御，alpha 仍小。

- 通过 `four_expected_sleeves`：actual=['beta_core', 'alpha_active', 'defensive_factor', 'liquidity']
- 通过 `liquidity_is_complement`：liquidity=60.0-80.0, risk=20.0-40.0
- 通过 `risk_sleeve_midpoints_match_total`：risk_mid_sum=29.5, total_mid=30.0
- 通过 `liquidity_still_high`：底部便宜不等于直接满仓，优先提高 beta 和防御，alpha 仍小。
- 通过 `beta_above_alpha`：底部便宜不等于直接满仓，优先提高 beta 和防御，alpha 仍小。
- 通过 `alpha_not_open`：底部便宜不等于直接满仓，优先提高 beta 和防御，alpha 仍小。

### 健康主升共振

趋势、宽度、资金、主线共振且不拥挤时，风险资产可接近满仓，alpha 打开。

- 通过 `four_expected_sleeves`：actual=['beta_core', 'alpha_active', 'defensive_factor', 'liquidity']
- 通过 `liquidity_is_complement`：liquidity=0.0-10.0, risk=90.0-100.0
- 通过 `risk_sleeve_midpoints_match_total`：risk_mid_sum=95.0, total_mid=95.0
- 通过 `liquidity_low`：趋势、宽度、资金、主线共振且不拥挤时，风险资产可接近满仓，alpha 打开。
- 通过 `alpha_open`：趋势、宽度、资金、主线共振且不拥挤时，风险资产可接近满仓，alpha 打开。
- 通过 `defensive_small`：趋势、宽度、资金、主线共振且不拥挤时，风险资产可接近满仓，alpha 打开。

### 深熊赔率逆向加仓

估值便宜且深回撤时，可以左侧提高股票账户风险资产，但只交给β核心仓，不打开alpha追涨。

- 通过 `four_expected_sleeves`：actual=['beta_core', 'alpha_active', 'defensive_factor', 'liquidity']
- 通过 `liquidity_is_complement`：liquidity=40.0-60.0, risk=40.0-60.0
- 通过 `risk_sleeve_midpoints_match_total`：risk_mid_sum=50.5, total_mid=50.0
- 通过 `state_is_contrarian`：估值便宜且深回撤时，可以左侧提高股票账户风险资产，但只交给β核心仓，不打开alpha追涨。
- 通过 `beta_dominates`：估值便宜且深回撤时，可以左侧提高股票账户风险资产，但只交给β核心仓，不打开alpha追涨。
- 通过 `alpha_capped`：估值便宜且深回撤时，可以左侧提高股票账户风险资产，但只交给β核心仓，不打开alpha追涨。
- 通过 `liquidity_buffer`：估值便宜且深回撤时，可以左侧提高股票账户风险资产，但只交给β核心仓，不打开alpha追涨。

### 牛末泡沫冲顶

机会分仍高但估值、拥挤和波动压仓位，优先压 alpha、抬流动性。

- 通过 `four_expected_sleeves`：actual=['beta_core', 'alpha_active', 'defensive_factor', 'liquidity']
- 通过 `liquidity_is_complement`：liquidity=60.0-80.0, risk=20.0-40.0
- 通过 `risk_sleeve_midpoints_match_total`：risk_mid_sum=30.5, total_mid=30.0
- 通过 `alpha_capped`：机会分仍高但估值、拥挤和波动压仓位，优先压 alpha、抬流动性。
- 通过 `liquidity_high`：机会分仍高但估值、拥挤和波动压仓位，优先压 alpha、抬流动性。
- 通过 `defensive_at_least_alpha`：机会分仍高但估值、拥挤和波动压仓位，优先压 alpha、抬流动性。

### 顶部反抽但风控压制

反抽能抬高机会分，但宽度弱和高位风险未解除，alpha 不应快速扩张。

- 通过 `four_expected_sleeves`：actual=['beta_core', 'alpha_active', 'defensive_factor', 'liquidity']
- 通过 `liquidity_is_complement`：liquidity=40.0-60.0, risk=40.0-60.0
- 通过 `risk_sleeve_midpoints_match_total`：risk_mid_sum=50.0, total_mid=50.0
- 通过 `alpha_capped`：反抽能抬高机会分，但宽度弱和高位风险未解除，alpha 不应快速扩张。
- 通过 `liquidity_buffer`：反抽能抬高机会分，但宽度弱和高位风险未解除，alpha 不应快速扩张。
- 通过 `beta_above_alpha`：反抽能抬高机会分，但宽度弱和高位风险未解除，alpha 不应快速扩张。

### 极端杀跌

极端下跌时便宜也不能替代趋势确认，保持高流动性和极低 alpha。

- 通过 `four_expected_sleeves`：actual=['beta_core', 'alpha_active', 'defensive_factor', 'liquidity']
- 通过 `liquidity_is_complement`：liquidity=80.0-100.0, risk=0.0-20.0
- 通过 `risk_sleeve_midpoints_match_total`：risk_mid_sum=12.0, total_mid=10.0
- 通过 `liquidity_very_high`：极端下跌时便宜也不能替代趋势确认，保持高流动性和极低 alpha。
- 通过 `alpha_near_zero`：极端下跌时便宜也不能替代趋势确认，保持高流动性和极低 alpha。
- 通过 `defensive_above_beta`：极端下跌时便宜也不能替代趋势确认，保持高流动性和极低 alpha。
