# A-FEAR v1 Design Contract

## Purpose

`A-FEAR v1` is a daily, end-of-day A-share fear indicator. It measures current
fear intensity from `0` to `100`; it is not a buy score and does not directly
change the official stock-account position recommendation in v1.

The model answers a separate question from the existing trend and valuation
layers:

- trend: where is the market moving;
- valuation: how expensive is the market;
- fear: how strongly is downside risk being priced and experienced.

## Components

The official score is:

```text
A-FEAR = implied_volatility * 0.40
       + downside_volatility * 0.20
       + market_breadth * 0.25
       + tail_loss * 0.15
```

All component scores are trailing empirical percentiles on a `0..100` scale.
The default lookback is 750 trading days and the minimum publishable sample is
250 observations. A historical score may only use observations dated on or
before its basis trade date.

### Implied volatility

- Instruments: CFFEX CSI 300 index options (`IO`) and CSI 1000 index options
  (`MO`).
- Quote: settlement price first, close price as fallback.
- Expiry: calculate ATM IV for the expiries immediately before and after 30
  calendar days, then interpolate total variance to a fixed 30-day maturity.
- Forward: infer from matched call/put prices with put-call parity.
- ATM strike: the liquid matched strike closest to inferred forward.
- Solver: Black-76 implied volatility with bounded bisection.
- Rate: one-month SHIBOR at or before the basis date; a documented fallback is
  allowed only with reduced confidence.
- Invalid quotes, expired contracts, zero open interest, and unsolvable prices
  are excluded with explicit quality warnings.
- IO and MO percentiles are equal weighted when both are available.

### Downside volatility

For CSI 300 (`000300.SH`) and CSI 1000 (`000852.SH`):

```text
downside_vol_20d = sqrt(252 * mean(min(daily_return, 0) ** 2))
```

The two index percentiles are equal weighted.

### Market breadth

```text
decliner_ratio_percentile          * 0.40
decline_beyond_3pct_ratio_percentile * 0.40
limit_down_ratio_percentile        * 0.20
```

Ratios, rather than absolute counts, are required so that history remains
comparable as the number of listed companies changes.

### Tail loss

For CSI 300 and CSI 1000, calculate the empirical loss percentile of one-day
and five-day returns. Positive returns have zero loss severity.

```text
index_tail = one_day_loss_percentile * 0.50
           + five_day_loss_percentile * 0.50
tail_loss = mean(CSI300 index_tail, CSI1000 index_tail)
```

## Outputs

Every stored record includes:

- `version`, `basis_trade_date`, `generated_at`, and deterministic `run_id`;
- official `fear_score`, `change_1d`, and `change_3d`;
- `level`, `phase`, and `confidence`;
- raw values, percentile scores, weights, sample counts, and source dates for
  every component;
- `fear_300`, `fear_1000`, and `small_cap_fear_spread` when available;
- quality warnings and missing fields.

Level bands are `calm` (0-20), `normal` (20-40), `watch` (40-60), `high`
(60-80), and `extreme` (80-100). Phase additionally describes whether fear is
rising, accelerating, stable, or easing.

## Missing data and safety

- If both IO and MO IV are valid, publish the official score with normal
  confidence rules.
- If only one option family is valid, publish using it and reduce confidence.
- If both option families are invalid, do not publish an official A-FEAR score.
  Publish a clearly named `realized_fear_proxy` instead.
- Partial non-IV components may be renormalized only when at least two realized
  components remain; confidence must be reduced.
- Stale data never creates a new official history record.
- A-FEAR v1 is read-only decision support. It does not trigger trading,
  synchronization, score recomputation through GET requests, or automatic
  position changes.

## Persistence and API

Files:

- `data/a_fear_history.json`: immutable daily records with same-day dedupe;
- `data/a_fear_latest.json`: latest successfully calculated result;
- `data/a_fear_source_cache.json`: reusable raw daily observations for
  reproducible backfills.

Initial history creation may use the explicit `--bootstrap-rebuild` command
line switch while earlier source gaps are being filled. Normal daily runs never
enable it and retain immutable same-day conflict protection.

Read-only endpoints:

- `GET /api/fear/latest`
- `GET /api/fear/history`
- `GET /api/fear/history?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD`
- `GET /api/fear/components/latest`
- `GET /api/fear/status`

The endpoints must also appear in `GET /api` and the latest research bundle.

## Acceptance criteria

- Synthetic Black-76 prices recover their input volatility within tolerance.
- Fixed-30-day interpolation is continuous across expiry rolls.
- Historical percentiles contain no future observations.
- Missing IV follows the official/proxy boundary above.
- Re-running the same basis date does not duplicate history.
- The daily update can fail A-FEAR independently without losing the existing
  market score and report.
- Web and API clearly state that fear is not a buy score.
