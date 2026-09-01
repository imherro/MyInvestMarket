# Cycle Engine v1 Walk-Forward Diagnostics

This research-only layer asks what could have been observed at each historical
`as_of_month`. Only targets whose natural `target_month <= as_of_month` are
included. It requires the Evidence, Evaluation, and Phase 3 audit gates and
does not alter any upstream artifact.

Run `python scripts/cycle_engine_walk_forward_diagnostics.py --generate`.
The output is descriptive only: no score, ranking, selection, label, signal,
weight, position, or strategy backtest is produced.
