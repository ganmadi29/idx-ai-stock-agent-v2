"""
Cost-adjusted forward-return evaluation of logged signals.

Fixes vs v1:
  - Loads from the AI_log Google Sheet (or a CSV export) with the
    actual column names written by main.py.
  - Deduplicates on (ticker, date): the old 4x/day cron triple-logged
    the same signal, inflating trade counts (pseudo-replication).
  - Entry = NEXT trading day's OPEN (the signal is generated after the
    close — you cannot buy the signal-day close). Exit = close of the
    LOOKAHEAD-th trading day after entry.
  - Downloads a date window anchored on each signal's date instead of
    `period="1mo"`, so old signals no longer silently drop out.
  - Win = net return > 0 AFTER round-trip costs (default 0.6%:
    ~0.15-0.25% buy fee + ~0.25-0.35% sell fee incl. 0.1% sales tax).
    Spread/slippage on less liquid names is extra — treat results as
    an upper bound.

Usage:
    python -m analysis.win_rate                # from Google Sheet
    python -m analysis.win_rate export.csv     # from a CSV export
"""

import json
import os
import sys
from datetime import timedelta

import pandas as pd
import yfinance as yf

LOOKAHEAD = 5           # trading days held after entry
COST_ROUNDTRIP = 0.6    # % — broker fees + 0.1% sales tax, excl. spread

_price_cache = {}


def _load_from_gsheet():
    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_info(
        json.loads(os.environ["GCP_SA_KEY"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(os.environ["SPREADSHEET_ID"]).worksheet("AI_log")
    return pd.DataFrame(ws.get_all_records())


def _get_prices(ticker: str, start, end) -> pd.DataFrame:
    """Per-ticker download covering the full span of its signals."""
    key = (ticker, start, end)
    if key not in _price_cache:
        df = yf.download(
            ticker,
            start=start,
            end=end,
            progress=False,
            auto_adjust=True,
        )
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.index = pd.to_datetime(df.index).tz_localize(None)
        _price_cache[key] = df
    return _price_cache[key]


def forward_return(ticker: str, signal_date: pd.Timestamp):
    """Gross % return: next-day open -> close LOOKAHEAD trading days later.
    Returns (gross_return, entry_slippage_pct_available) or None if the
    holding window hasn't completed yet."""
    start = (signal_date - timedelta(days=7)).date()
    end = (signal_date + timedelta(days=LOOKAHEAD * 3 + 10)).date()
    df = _get_prices(ticker, start, end)
    if df.empty:
        return None

    future = df[df.index > signal_date]
    if len(future) < LOOKAHEAD + 1:
        return None  # holding period not complete yet — skip, don't bias

    entry = float(future.iloc[0]["Open"])     # realistic fill
    exit_ = float(future.iloc[LOOKAHEAD]["Close"])
    if entry <= 0:
        return None
    return (exit_ - entry) / entry * 100


def analyze(source: str | None = None) -> dict:
    # ---------- Load ----------
    if source:
        raw = pd.read_csv(source)
    else:
        raw = _load_from_gsheet()

    if raw.empty:
        raise SystemExit("No logged signals found.")

    raw.columns = [c.lower().strip() for c in raw.columns]
    required = {"date", "ticker"}
    missing = required - set(raw.columns)
    if missing:
        raise SystemExit(f"Log is missing columns: {missing}")

    raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    raw = raw.dropna(subset=["date", "ticker"])
    raw["day"] = raw["date"].dt.normalize()

    # ---------- Dedupe (ticker, day) ----------
    n_before = len(raw)
    raw = raw.sort_values("date").drop_duplicates(subset=["ticker", "day"], keep="first")
    n_dupes = n_before - len(raw)

    # ---------- Forward returns ----------
    rows, pending = [], 0
    for _, r in raw.iterrows():
        gross = forward_return(r["ticker"], r["day"])
        if gross is None:
            pending += 1
            continue
        net = gross - COST_ROUNDTRIP
        rows.append({
            "ticker": r["ticker"],
            "day": r["day"].date(),
            "confidence": r.get("confidence", ""),
            "reasons": str(r.get("reasons", r.get("reason", ""))),
            "gross": gross,
            "net": net,
            "win": net > 0,
        })

    if not rows:
        raise SystemExit(
            f"No evaluable signals ({pending} still inside the "
            f"{LOOKAHEAD}-day holding window)."
        )

    res = pd.DataFrame(rows)

    # ---------- Aggregates ----------
    def _agg(g):
        return pd.Series({
            "trades": len(g),
            "win_rate_%": g["win"].mean() * 100,
            "avg_net_%": g["net"].mean(),
            "median_net_%": g["net"].median(),
            "expectancy_%": g["net"].mean(),  # per-trade edge after costs
        })

    overall = _agg(res).to_frame("ALL").T

    by_conf = (
        res.groupby("confidence").apply(_agg, include_groups=False)
        if res["confidence"].astype(bool).any() else pd.DataFrame()
    )

    reason_rows = []
    for _, r in res.iterrows():
        for reason in [x.strip() for x in r["reasons"].split("+") if x.strip()]:
            if reason.startswith("Vx"):
                reason = "VOLUME_SPIKE"
            reason_rows.append({"reason": reason, "net": r["net"], "win": r["win"]})
    by_reason = (
        pd.DataFrame(reason_rows)
        .groupby("reason")
        .agg(trades=("win", "count"), win_rate_pct=("win", "mean"), avg_net_pct=("net", "mean"))
        .assign(win_rate_pct=lambda x: x.win_rate_pct * 100)
        .sort_values("avg_net_pct", ascending=False)
    )

    print(f"\nDeduplicated {n_dupes} repeated (ticker, day) rows.")
    print(f"Evaluated {len(res)} trades | {pending} pending (window incomplete)")
    print(f"Costs applied: {COST_ROUNDTRIP}% round-trip (spread NOT included)\n")
    print("=== OVERALL ===");        print(overall.round(2))
    if not by_conf.empty:
        print("\n=== BY CONFIDENCE ==="); print(by_conf.round(2))
    print("\n=== BY TRIGGER ===");    print(by_reason.round(2))

    return {"overall": overall, "by_confidence": by_conf, "by_reason": by_reason, "trades": res}


if __name__ == "__main__":
    analyze(sys.argv[1] if len(sys.argv) > 1 else None)
