import streamlit as st
import pandas as pd
import plotly.express as px
import gspread
from google.oauth2.service_account import Credentials
import json
import os

st.set_page_config(
    page_title="IDX Signal Monitor",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─── Auth ─────────────────────────────────────────────────────────────────────

def _get_secrets():
    sa_key = st.secrets.get("GCP_SA_KEY") if hasattr(st, "secrets") else None
    sheet_id = st.secrets.get("SPREADSHEET_ID") if hasattr(st, "secrets") else None
    return (
        sa_key or os.environ["GCP_SA_KEY"],
        sheet_id or os.environ["SPREADSHEET_ID"],
    )

@st.cache_resource
def _gc():
    sa_key, _ = _get_secrets()
    creds = Credentials.from_service_account_info(
        json.loads(sa_key),
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    return gspread.authorize(creds)

@st.cache_data(ttl=300, show_spinner="Loading signals...")
def load_signals():
    _, sheet_id = _get_secrets()
    ws = _gc().open_by_key(sheet_id).worksheet("AI_log")
    rows = ws.get_all_records()
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df.columns = [c.lower().strip().replace(" ", "_") for c in df.columns]

    # parse date
    for col in ["date", "datetime", "timestamp", "time"]:
        if col in df.columns:
            df["date"] = pd.to_datetime(df[col], errors="coerce")
            break

    # numeric coercion
    for col in ["price", "change_pct", "volume_ratio", "rsi", "score"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # detect outcome/return column
    ret_col = next((c for c in ["return_pct", "return", "outcome_pct", "outcome"] if c in df.columns), None)
    if ret_col:
        df["return_pct"] = pd.to_numeric(df[ret_col], errors="coerce")
        df["win"] = df["return_pct"] > 0

    return df.sort_values("date", ascending=False) if "date" in df.columns else df


# ─── Load & filter ────────────────────────────────────────────────────────────

st.title("📈 IDX AI Signal Monitor")

try:
    df_full = load_signals()
except Exception as e:
    st.error(f"Failed to load sheet: {e}")
    st.stop()

if df_full.empty:
    st.warning("No signals logged yet.")
    st.stop()

with st.sidebar:
    st.header("Filters")

    if "date" in df_full.columns:
        min_d = df_full["date"].min().date()
        max_d = df_full["date"].max().date()
        date_range = st.date_input("Date range", value=(min_d, max_d), min_value=min_d, max_value=max_d)
    else:
        date_range = None

    conf_opts = ["ALL"] + sorted(df_full["confidence"].dropna().unique().tolist()) if "confidence" in df_full.columns else ["ALL"]
    conf_filter = st.selectbox("Confidence", conf_opts)

    ticker_opts = ["ALL"] + sorted(df_full["ticker"].dropna().unique().tolist()) if "ticker" in df_full.columns else ["ALL"]
    ticker_filter = st.selectbox("Ticker", ticker_opts)

    if st.button("🔄 Refresh data"):
        st.cache_data.clear()
        st.rerun()

df = df_full.copy()
if date_range and len(date_range) == 2 and "date" in df.columns:
    df = df[(df["date"].dt.date >= date_range[0]) & (df["date"].dt.date <= date_range[1])]
if conf_filter != "ALL" and "confidence" in df.columns:
    df = df[df["confidence"] == conf_filter]
if ticker_filter != "ALL" and "ticker" in df.columns:
    df = df[df["ticker"] == ticker_filter]

st.caption(f"Showing **{len(df)}** of {len(df_full)} signals")

has_outcome = "win" in df.columns and df["win"].notna().any()

# ─── Tabs ─────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4 = st.tabs(["Overview", "Signals", "Win Rate", "Score Analysis"])


# ── Overview ──────────────────────────────────────────────────────────────────
with tab1:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Signals", len(df))

    if has_outcome:
        evaluated = df["win"].notna().sum()
        c2.metric("Win Rate", f"{df['win'].mean() * 100:.1f}%", f"{evaluated} evaluated")
        c3.metric("Avg Return", f"{df['return_pct'].mean():+.2f}%")
    else:
        c2.metric("Win Rate", "—")
        c3.metric("Avg Return", "—")

    if "score" in df.columns:
        c4.metric("Avg Score", f"{df['score'].mean():.2f}")

    st.divider()

    col_l, col_r = st.columns(2)

    with col_l:
        if "date" in df.columns:
            daily = df.groupby(df["date"].dt.date).size().reset_index(name="count")
            fig = px.bar(daily, x="date", y="count", title="Signals per Day",
                         labels={"date": "", "count": "Signals"})
            fig.update_layout(height=300, margin=dict(t=40, b=0))
            st.plotly_chart(fig, use_container_width=True)

    with col_r:
        if "ticker" in df.columns:
            top = df["ticker"].value_counts().head(10).reset_index()
            top.columns = ["ticker", "count"]
            fig2 = px.bar(top, x="ticker", y="count", title="Top 10 Most Signalled Tickers",
                          labels={"count": "Signals"})
            fig2.update_layout(height=300, margin=dict(t=40, b=0))
            st.plotly_chart(fig2, use_container_width=True)


# ── Signals table ─────────────────────────────────────────────────────────────
with tab2:
    want = ["date", "ticker", "price", "change_pct", "volume_ratio", "rsi",
            "confidence", "score", "return_pct", "reasons"]
    show_cols = [c for c in want if c in df.columns]
    display = df[show_cols].copy()
    if "date" in display.columns:
        display["date"] = display["date"].dt.strftime("%Y-%m-%d %H:%M")

    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "change_pct":   st.column_config.NumberColumn("Change %",   format="%+.2f%%"),
            "return_pct":   st.column_config.NumberColumn("Return %",   format="%+.2f%%"),
            "score":        st.column_config.NumberColumn("Score",      format="%.2f"),
            "volume_ratio": st.column_config.NumberColumn("Vol Ratio",  format="%.1fx"),
            "rsi":          st.column_config.NumberColumn("RSI",        format="%.1f"),
        }
    )


# ── Win Rate ──────────────────────────────────────────────────────────────────
with tab3:
    if not has_outcome:
        st.info("No outcome data found. Add a `return_pct` column to your AI_log sheet to enable win rate analysis.")
    else:
        ev = df[df["win"].notna()].copy()

        col_l, col_r = st.columns(2)

        with col_l:
            if "confidence" in ev.columns:
                cs = (
                    ev.groupby("confidence")
                    .agg(trades=("win", "count"), win_rate=("win", "mean"), avg_return=("return_pct", "mean"))
                    .assign(win_rate=lambda x: x.win_rate * 100)
                    .reset_index()
                )
                fig = px.bar(cs, x="confidence", y="win_rate", color="confidence",
                             title="Win Rate by Confidence", text_auto=".1f",
                             labels={"win_rate": "Win Rate %"})
                fig.update_layout(height=350, showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

        with col_r:
            rows = []
            for _, row in ev.iterrows():
                for r in str(row.get("reasons", "")).split(","):
                    r = r.strip()
                    if r:
                        rows.append({"trigger": r, "win": row["win"], "return_pct": row.get("return_pct", 0)})
            if rows:
                tdf = pd.DataFrame(rows)
                ts = (
                    tdf.groupby("trigger")
                    .agg(trades=("win", "count"), win_rate=("win", "mean"), avg_return=("return_pct", "mean"))
                    .assign(win_rate=lambda x: x.win_rate * 100)
                    .sort_values("win_rate", ascending=True)
                    .reset_index()
                )
                fig2 = px.bar(ts, y="trigger", x="win_rate", orientation="h",
                              title="Win Rate by Trigger", text_auto=".1f",
                              labels={"win_rate": "Win Rate %", "trigger": ""})
                fig2.update_layout(height=350)
                st.plotly_chart(fig2, use_container_width=True)

        if "ticker" in ev.columns:
            st.subheader("Per-Ticker Performance")
            tk = (
                ev.groupby("ticker")
                .agg(trades=("win", "count"), win_rate=("win", "mean"), avg_return=("return_pct", "mean"))
                .assign(win_rate=lambda x: x.win_rate * 100)
                .sort_values("avg_return", ascending=False)
                .reset_index()
            )
            st.dataframe(
                tk, use_container_width=True, hide_index=True,
                column_config={
                    "win_rate":   st.column_config.NumberColumn("Win Rate %",  format="%.1f%%"),
                    "avg_return": st.column_config.NumberColumn("Avg Return %", format="%+.2f%%"),
                }
            )


# ── Score Analysis ────────────────────────────────────────────────────────────
with tab4:
    if "score" not in df.columns:
        st.info("No score data available.")
    else:
        col_l, col_r = st.columns(2)

        with col_l:
            if has_outcome:
                analyzed = df[df["return_pct"].notna()].copy()
                fig = px.scatter(
                    analyzed, x="score", y="return_pct",
                    color="confidence" if "confidence" in analyzed.columns else None,
                    hover_data=["ticker"] if "ticker" in analyzed.columns else None,
                    trendline="ols",
                    title="Score vs Actual Return",
                    labels={"score": "Signal Score", "return_pct": "Return %"}
                )
                fig.add_hline(y=0, line_dash="dash", line_color="gray")
                fig.update_layout(height=400)
                st.plotly_chart(fig, use_container_width=True)
            else:
                fig = px.histogram(df, x="score", nbins=30, title="Score Distribution",
                                   labels={"score": "Signal Score"})
                fig.update_layout(height=400)
                st.plotly_chart(fig, use_container_width=True)

        with col_r:
            if has_outcome:
                analyzed = df[df["return_pct"].notna()].copy()
                fig2 = px.histogram(analyzed, x="return_pct", nbins=30,
                                    title="Return Distribution",
                                    labels={"return_pct": "Return %"})
                fig2.add_vline(x=0, line_dash="dash", line_color="red")
                fig2.update_layout(height=400)
                st.plotly_chart(fig2, use_container_width=True)

        if has_outcome and "date" in df.columns:
            analyzed = df[df["return_pct"].notna()].sort_values("date").copy()
            analyzed["cumulative_return"] = analyzed["return_pct"].cumsum()
            fig3 = px.line(analyzed, x="date", y="cumulative_return",
                           title="Cumulative Return Over Time",
                           labels={"cumulative_return": "Cumulative Return %", "date": ""})
            fig3.add_hline(y=0, line_dash="dash", line_color="gray")
            fig3.update_layout(height=350)
            st.plotly_chart(fig3, use_container_width=True)
