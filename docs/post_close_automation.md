# MyInvestMarket Post-Close Automation

Recommended schedule: trading days after market data settles, around `18:10 Asia/Shanghai`.

Use this prompt for Codex automation:

```text
Run the MyInvestMarket post-close update in C:\Users\kunpeng\Documents\MyInvestMarket.

Execute:
python .\scripts\run_post_close_update.py

Report the basis trading day, model version, market opportunity score, crowding penalty, base equity range, volatility-adjusted equity range, market regime, API verification result, and commit hash or skip reason.
```

The script is intentionally idempotent:

- It refuses to run on a dirty Git worktree by default.
- It uses the latest complete A-share trading day at or before the as-of date.
- It does not append another score when the latest score has the same basis date and the stable market snapshot content is unchanged.
- It validates `/api/index`, `/api/research/latest/market-score`, and `/api/research/latest/market-analysis`.
- When it writes new files, it commits and pushes the data/report updates to `origin main`.

Manual test command:

```powershell
python .\scripts\run_post_close_update.py --as-of 2026-06-22 --allow-dirty --no-git
```
