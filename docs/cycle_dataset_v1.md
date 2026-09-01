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

## Output and audit

Run:

```powershell
python .\scripts\build_cycle_dataset.py --as-of 2026-09-01
```

This writes `data/cycle_dataset_v1.json`, JSON audit, and Markdown audit. The audit hard-fails on future-dated observations or duplicate months/basis dates. Re-running against unchanged sources and the same `--as-of` is deterministic except for audit `generated_at`.
