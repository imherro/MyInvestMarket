# Cycle Engine v1 Phase 3.1

This research-only artifact applies a fixed two-hit confirmation rule with one ambiguous grace month to the frozen Phase 3.0 Candidate Historical Replay. It does not alter the candidate rules and does not produce numeric scores, execution instructions, or portfolio outputs.

After initialization, an ambiguous raw observation holds the current stable state. A pending target may survive one ambiguous month, expires after two, and is replaced by a competing non-ambiguous target. Confirmation requires two identical raw candidate states; state families are not merged.

The runtime reads only the Phase 3.0 candidate JSON and its audit. The frozen candidate byte SHA256 is `9764e56c8b094d7d5927964bfdee20ba62efb98da55edbb9a2e50cbfc87e161a` (the Git blob SHA is `6db7ec85953cd7f5b6c6045df93eac2b4cd183f2`).

The final audit contract independently verifies top-level artifact fields,
historical window extracts, transition-event metadata, stable run statistics,
and the exact pending-cancellation count. Sentiment fields are extracted
without the production overlay helper, and mutations after a cutoff month
must leave the historical prefix unchanged.
