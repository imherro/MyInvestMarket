# Cycle Dataset v1

`cycle_dataset_v1` is a monthly Point-in-Time research dataset for the later Cycle Engine. It does not calculate a cycle score, does not change an official position recommendation, and is not exposed through an API in this phase.

## Time contract

- One record per calendar month from January 2010 through the latest fully completed calendar month.
- `basis_trade_date` is the last SSE open day in that month.
- The builder may read prices from January 2005 to form early rolling indicators, but every record only uses observations dated on or before its basis date.
- Financial observations must satisfy `ann_date <= basis_trade_date`. An announcement on the basis date is available; a later announcement is invisible.
- All slow feature objects contain `value`, observation or announcement date, source, `lag_days`, `available`, and `pit_safe`.

## Included domains

- Valuation: CSI 300/500/1000 PE TTM and PB, expanding historical percentile and z-score, CSI 300 earnings yield, China 10-year yield placeholder, and ERP placeholder.
- Earnings: all-A/non-financial earnings and ROE, industrial profit, PMI, and PPI schema fields. The initial runtime marks them unavailable unless a broad-market, announcement-date PIT source is configured. It never backfills a neutral score or uses the current listed universe retroactively.
- Trend: CSI 300/500/1000 closing level relative to MA250, six-month and twelve-month returns, and drawdown from the prior 12-month high.
- Sentiment: optional A-FEAR snapshot. Its shorter history is non-blocking.

The dataset intentionally excludes short-horizon 5/20-day returns, MA20, advancer/decliner counts, price limits, board data, northbound/main-fund flows, industry flows, and five-day volume from the cycle inputs.

## Sources and limits

Price, trade calendar, and index valuation history use `Tushare.trade_cal`, `Tushare.index_daily`, and `Tushare.index_dailybasic`. The configured account does not currently have historical `yc_cb` access and does not have a configured broad-market PIT financial source. These gaps are emitted as unavailable fields with explicit reasons and audit coverage; they are not imputed.

## Earnings growth PIT v1.1

`Tushare.income_vip` supplies quarterly parent-company net profit, announcement dates, report types, and `comp_type`. For each basis month, the builder selects the newest quarter whose actually announced report coverage is at least 70%; it then matches the identical companies with the prior-year same quarter. The published growth is `matched_current_profit_sum / matched_prior_profit_sum - 1`, never an average of company growth rates.

Current-period profits use only `report_type == 1`: consolidated cumulative statements. This means Q1, H1, Q3, and annual figures are never mixed with single-quarter or parent-company reports. For the prior-year comparator, a Point-in-Time-visible adjusted consolidated statement (`report_type == 4`) takes precedence; otherwise the original consolidated cumulative statement (`report_type == 1`) is used. Any identical source identity with conflicting profit values is retained in the cache audit and excluded from aggregation.

The stock denominator is historical: `list_date <= report_period` and no delisting on or before that report-period end. Later delistings remain in their historical universe; later IPOs do not enter it. `comp_type == 1` is the only nonfinancial classification. The nonfinancial denominator is the PIT-visible `comp_type == 1` universe, while unknown classifications remain unknown and are reported separately. If matched coverage is below 65% or matched prior profit is non-positive, the growth value is unavailable.

`data/cycle_earnings_source_cache.json` is append-only. New report periods and newly disclosed versions of the newest completed report period are fetched and appended; exact duplicates are ignored and older source rows are never rewritten. `last_successful_refresh_date` records a successful remote cache check, not the dataset's `as_of` date; `last_refresh_date` is retained as its compatible alias. Cache metadata round-trips unknown future fields and persists stock metadata conflicts.

The cache freshness check only requires a period after its statutory reporting deadline: Q1 on April 30, H1 on August 31, Q3 on October 31, and annual results on April 30 of the following year. A live refresh failure never overwrites the source cache: existing cached earnings remain usable for historical research, while the run records `refresh_error` and returns `freshness_passed=false`. Offline rebuilds do not access or change the source cache and are explicitly marked `offline=true`, so they cannot pass as a live freshness verification.

## Aggregate ROE(TTM) PIT v1

`earnings.all_a_roe_ttm_pct` and `earnings.nonfinancial_a_roe_ttm_pct` are amount-aggregated market ROE measures, not arithmetic averages of company `roe` values. The definition is `aggregate attributable net profit TTM / average aggregate attributable equity * 100`, calculated from one identical matched company set. TTM profit uses current cumulative profit for annual reports; Q1/H1/Q3 use `current cumulative + prior FY - prior-year same-period cumulative`.

Equity comes from `Tushare.balancesheet_vip`, using `total_hldr_eqy_exc_min_int` (attributable parent equity excluding minority interest). Each profit component and equity observation must have an effective announcement date at or before the monthly basis date. Current balance sheets only use `report_type == 1`; prior-year comparable equity prefers PIT-visible adjusted consolidated `report_type == 4`, otherwise `report_type == 1`. The existing historical listed-stock universe and `comp_type == 1` nonfinancial classification are shared with earnings growth. If the matched coverage is below 65% or aggregate average equity is non-positive, ROE is unavailable rather than imputed.

`data/cycle_roe_source_cache.json` contains only append-only balance-sheet source rows and its independent refresh metadata. Income data stays exclusively in `cycle_earnings_source_cache.json`. The ROE cache has the same failure, offline, conflict, and metadata round-trip semantics as the earnings cache. `fina_indicator_vip` fields can be used only for separate sanity checks and are not the formal ROE input.

## Output and audit

Run:

```powershell
python .\scripts\build_cycle_dataset.py --as-of 2026-09-01
```

This writes `data/cycle_dataset_v1.json`, JSON audit, and Markdown audit. The audit hard-fails on future-dated observations or duplicate months/basis dates. Re-running against unchanged sources and the same `--as-of` is deterministic except for audit `generated_at`.
