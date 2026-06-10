import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import yfinance as yf

from agents.analyst import AnalystAgent
from agents.narrator import NarratorAgent
from agents.news_agent import NewsAgent
from tools.watchlist import load_watchlist
from tools.telegram import send_telegram
from tools.formatter import format_signal_message

import gspread
from google.oauth2.service_account import Credentials

# =============================
# CONFIG
# =============================
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
LOG_SHEET = "AI_log"
WIB = ZoneInfo("Asia/Jakarta")
MAX_SIGNALS = 10

LOG_HEADER = [
    "date", "ticker", "price", "change_pct", "volume_ratio",
    "avg_value_bn", "rsi", "reasons", "score", "confidence",
]


def get_gspread_client():
    creds = Credentials.from_service_account_info(
        json.loads(os.environ["GCP_SA_KEY"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds)


def already_alerted_today(ws, today_str: str) -> set:
    """Tickers already logged today — guards against duplicate alerts
    if the workflow is re-run manually (workflow_dispatch)."""
    try:
        records = ws.get_all_records()
    except Exception:
        return set()
    return {
        str(r.get("ticker", "")).upper()
        for r in records
        if str(r.get("date", "")).startswith(today_str)
    }


def log_signals(ws, signals, now_wib: datetime):
    if not signals:
        return
    stamp = now_wib.strftime("%Y-%m-%d %H:%M:%S")
    rows = [
        [
            stamp,
            s["ticker"],
            s["price"],
            s["change_pct"],
            s["volume_ratio"],
            s["avg_value_bn"],
            s["rsi"],
            s["reason"],
            s["score"],
            s["confidence"],
        ]
        for s in signals
    ]
    ws.append_rows(rows, value_input_option="USER_ENTERED")


def main():
    now_wib = datetime.now(WIB)
    today_str = now_wib.strftime("%Y-%m-%d")

    gc = get_gspread_client()
    ws_log = gc.open_by_key(SPREADSHEET_ID).worksheet(LOG_SHEET)

    watchlist = load_watchlist().drop_duplicates(subset="ticker")
    analyst = AnalystAgent()
    narrator = NarratorAgent()
    news_agent = NewsAgent()

    seen_today = already_alerted_today(ws_log, today_str)

    signals, failures = [], []

    for _, row in watchlist.iterrows():
        if not row["enabled"]:
            continue

        ticker = row["ticker"]
        if ticker in seen_today:
            continue

        vol_window = int(row.get("lookback", 20) or 20)
        vol_mult = float(row.get("vol_mult", 2.0) or 2.0)

        try:
            df = yf.download(ticker, period="4mo", progress=False, auto_adjust=True)
        except Exception as e:
            failures.append(f"{ticker}: {e}")
            continue

        if df is None or df.empty:
            failures.append(f"{ticker}: empty download")
            continue

        df.attrs["ticker"] = ticker
        signal = analyst.analyze(df, vol_window=vol_window, vol_mult=vol_mult)
        if signal:
            signals.append(signal)

    # Single, explicit quality filter (HIGH already implies MA_TREND
    # + volume confirmation + not overbought — see AnalystAgent).
    signals = [s for s in signals if s["confidence"] == "HIGH"]
    signals = sorted(signals, key=lambda x: x["score"], reverse=True)[:MAX_SIGNALS]

    if not signals:
        msg = "📭 No signal today."
        if failures:
            msg += f"\n⚠️ {len(failures)} ticker(s) failed to download."
        send_telegram(msg)
        return

    header = (
        "🚀 <b>IDX Daily Breakout Signals</b>\n"
        f"{today_str} | {len(signals)} signal(s)\n"
        "⚠️ Realistic entry = <b>next-day open</b>, not signal price.\n"
    )
    if failures:
        header += f"⚠️ {len(failures)} ticker(s) failed to download.\n"
    send_telegram(header)

    log_signals(ws_log, signals, now_wib)

    # Enrich + send only the signals that survived filtering
    for signal in signals:
        signal["news"] = news_agent.get_news(signal["ticker"])
        signal["insight"] = narrator.run(signal)
        send_telegram(format_signal_message(signal))


if __name__ == "__main__":
    main()
