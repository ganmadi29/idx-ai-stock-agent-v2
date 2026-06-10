# IDX AI Stock Agent — v2 Upgrade Notes

## Required manual steps (do these before first run)

1. **Google Sheet `AI_log` header row** — set row 1 to exactly:
   `date | ticker | price | change_pct | volume_ratio | avg_value_bn | rsi | reasons | score | confidence`
   (one new column: `avg_value_bn`). Start a fresh tab or migrate; old rows
   with the broken/mixed schema will confuse `win_rate.py`.
2. **Delete `signals_log.csv`** from the repo — stale, malformed (5-col header,
   6–7-col rows), and superseded by the sheet.
3. Secrets are unchanged: `GROQ_API_KEY`, `SPREADSHEET_ID`, `GCP_SA_KEY`,
   `BOT_TOKEN`, `CHAT_ID`.

## What changed and why

### Signal quality (agents/analyst.py)
- **Liquidity gate**: skips names with < Rp 5bn/day 20-day average transaction
  value (tunable via `MIN_AVG_VALUE_IDR`). Filters the illiquid microcaps
  where volume-spike signals mostly capture pump/markup activity and
  unfillable spreads.
- **ARA-proximity gate**: skips names whose move is already >= 80% of their
  tiered auto-reject limit (35% / 25% / 20% by price band). Those gap at the
  next open — your realistic entry.
- **Score rebuilt**: bounded additive 0–100 (volume 35 + trend 35 +
  momentum 20 + RSI 10). `change_pct` capped at +6%, `vol_ratio` saturates at
  4x — the most extended move no longer auto-ranks first.
- **RSI >= 70 is now a penalty** (0 points + 30% score haircut + blocks HIGH
  confidence). The old formula *rewarded* overbought readings.
- `lookback` and `vol_mult` from the watchlist sheet are now actually used
  (they were dead parameters).

### Honest evaluation (analysis/win_rate.py)
- Entry = **next-day OPEN** (you cannot buy the signal-day close).
- **Win = net return > 0 after 0.6% round-trip costs** (fees + 0.1% sales
  tax; spread NOT included — results remain an upper bound).
- **Dedupes (ticker, day)** — the old 4x/day cron triple-logged signals.
- Date-anchored downloads — old signals no longer silently drop out
  (`period="1mo"` bug).
- Skips signals whose 5-day window hasn't completed (no look-shortened bias).
- Reads the sheet directly or a CSV export: `python -m analysis.win_rate`.

### Hallucination control (agents/narrator.py)
- The old narrator invented catalysts (fake Astra partnership, fake JVs) —
  they're in your own log. New system prompt forbids speculating about news/
  fundamentals, headlines are passed as untrusted context, temperature
  lowered to 0.2, and the output must end in "ACTIONABLE at next open" or
  "NO TRADE" with the biggest risk.
- Narrator + news now run only for the signals that survive filtering
  (was: every raw signal — wasted Groq calls).

### Operations
- **Single post-close run** (16:45 WIB, weekdays). The old 4x/day schedule
  compared partial-day volume against full-day averages — three semantically
  different signals from the same code. The 08:00 WIB run fired on stale data.
- **WIB timestamps** (`zoneinfo`) — runner-UTC dates were 7h off.
- **Re-run guard**: tickers already logged today are skipped on manual
  re-runs (`workflow_dispatch`).
- Download failures are counted and reported in the Telegram summary instead
  of silently skipped.
- `requirements.txt` pinned with upper bounds (the MultiIndex hack was a
  symptom of unpinned yfinance).
- **Dead code removed**: `agents/validator.py` (conflicting thresholds),
  `agents/outcome_checker.py`, `tools/storage.py`, `tools/gsheet.py`.
- `config/idx_tickers.py` deduplicated (TLKM.JK was listed twice) and marked
  as legacy — the live watchlist is the sheet.

## What this still is NOT
- Not a backtested strategy — run `win_rate.py` for 2–3 months of forward
  signals before trusting any stat, and backtest the rule on history.
- No position sizing, stops, or exit logic beyond the fixed 5-day window.
- Spread/slippage is not modeled; treat the net numbers as optimistic.
