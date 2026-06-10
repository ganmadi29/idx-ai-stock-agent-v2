import pandas as pd
from tools.indicators import rsi as compute_rsi

# ============================================================
# IDX auto-rejection (ARA) upper limits by price tier
# (symmetric regime, effective since Sep 2023)
#   Rp 50 - 200      -> 35%
#   Rp >200 - 5,000  -> 25%
#   Rp >5,000        -> 20%
# ============================================================
ARA_TIERS = [
    (200, 35.0),
    (5000, 25.0),
    (float("inf"), 20.0),
]


def ara_limit_pct(prev_close: float) -> float:
    for cap, pct in ARA_TIERS:
        if prev_close <= cap:
            return pct
    return 20.0


class AnalystAgent:
    """
    Momentum/volume breakout screener with tradability gates.

    Key changes vs v1:
      - Liquidity gate: minimum 20-day average transaction value
        (Close * Volume). Filters out illiquid microcaps where the
        signal mostly captures bandar markups and unfillable spreads.
      - ARA-proximity gate: skips names whose daily move is already
        >= `near_ara_frac` of their tier's auto-reject limit. Those
        usually can't be entered next morning except at a gap.
      - Bounded additive score (0-100). change_pct and vol_ratio are
        capped so the most extended move no longer auto-ranks first.
      - RSI >= 70 is now a PENALTY (overbought), not a bonus.
      - `vol_window` and `vol_mult` are real parameters, wired from
        the watchlist sheet instead of being hardcoded.
    """

    def __init__(
        self,
        min_avg_value_idr: float = 5e9,   # Rp 5 bn/day min liquidity
        near_ara_frac: float = 0.8,       # skip if move >= 80% of ARA
    ):
        self.min_avg_value_idr = min_avg_value_idr
        self.near_ara_frac = near_ara_frac

    def analyze(self, df: pd.DataFrame, vol_window: int = 20, vol_mult: float = 2.0):
        # Flatten MultiIndex columns (yfinance >= 0.2.x)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        if len(df) < 55:
            return None

        close = float(df["Close"].iloc[-1])
        prev_close = float(df["Close"].iloc[-2])
        if prev_close <= 0 or close <= 0:
            return None

        volume = float(df["Volume"].iloc[-1])
        vol_avg = df["Volume"].rolling(vol_window).mean().iloc[-1]
        if pd.isna(vol_avg) or vol_avg <= 0:
            return None
        vol_ratio = volume / vol_avg

        # ---------- Liquidity gate ----------
        avg_value = (df["Close"] * df["Volume"]).rolling(vol_window).mean().iloc[-1]
        if pd.isna(avg_value) or avg_value < self.min_avg_value_idr:
            return None

        # ---------- Price change ----------
        change_pct = (close - prev_close) / prev_close * 100
        if change_pct <= 0:
            return None  # only alert on up-days

        # ---------- ARA proximity gate ----------
        ara = ara_limit_pct(prev_close)
        if change_pct >= self.near_ara_frac * ara:
            return None  # already at/near auto-reject; next-day entry = chasing a gap

        # ---------- Indicators ----------
        ma20 = df["Close"].rolling(20).mean().iloc[-1]
        ma50 = df["Close"].rolling(50).mean().iloc[-1]
        rsi_val = compute_rsi(df["Close"]).iloc[-1]
        if pd.isna(rsi_val) or pd.isna(ma20) or pd.isna(ma50):
            return None

        # ---------- Reasons ----------
        reasons = []
        if vol_ratio >= vol_mult:
            reasons.append(f"Vx{round(vol_ratio, 1)}")
        if 50 <= rsi_val < 70:
            reasons.append("RSI_OK")
        if rsi_val >= 70:
            reasons.append("RSI_OVERBOUGHT")
        if close > ma20:
            reasons.append("MA20_OK")
        if ma20 > ma50:
            reasons.append("MA_TREND")
        if close > ma50:
            reasons.append("STRONG_TREND")
        if not reasons:
            return None

        # ---------- Score: bounded, additive, 0-100 ----------
        # Volume conviction (max 35): saturates at 4x average
        vol_component = min(vol_ratio / 4.0, 1.0) * 35

        # Trend structure (max 35)
        trend_component = (
            (10 if close > ma20 else 0)
            + (15 if ma20 > ma50 else 0)
            + (10 if close > ma50 else 0)
        )

        # Momentum (max 20): capped at +6% so extension stops adding score
        momentum_component = min(change_pct / 6.0, 1.0) * 20

        # RSI regime (max 10): healthy zone rewarded, overbought penalized
        if 50 <= rsi_val < 70:
            rsi_component = 10
        elif 45 <= rsi_val < 50:
            rsi_component = 4
        else:  # < 45 or >= 70
            rsi_component = 0

        score = vol_component + trend_component + momentum_component + rsi_component
        if rsi_val >= 70:
            score *= 0.7  # explicit overbought haircut

        # ---------- Confidence ----------
        ma_trend = ma20 > ma50
        if ma_trend and vol_ratio >= vol_mult and rsi_val < 70:
            confidence = "HIGH"
        elif vol_ratio >= 0.75 * vol_mult:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        return {
            "ticker": df.attrs.get("ticker", ""),
            "price": round(close, 2),
            "change_pct": round(change_pct, 2),
            "volume_ratio": round(vol_ratio, 2),
            "avg_value_bn": round(avg_value / 1e9, 2),
            "rsi": round(float(rsi_val), 1),
            "ma20": round(float(ma20), 2),
            "ma50": round(float(ma50), 2),
            "ara_limit_pct": ara,
            "reasons": reasons,
            "reason": " + ".join(reasons),
            "score": round(score, 1),
            "confidence": confidence,
        }
