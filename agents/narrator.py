from groq import Groq
from config.settings import GROQ_API_KEY

_TRIGGER_LABELS = {
    "MA_TREND":       "MA20 > MA50 (uptrend confirmed)",
    "MA20_OK":        "Price above MA20",
    "RSI_OK":         "RSI in healthy zone (50-70)",
    "RSI_OVERBOUGHT": "RSI >= 70 (overbought — caution)",
    "STRONG_TREND":   "Price above MA50 (strong trend)",
}


class NarratorAgent:
    """
    Hardened vs v1: the old version invented fundamental catalysts
    (fake partnerships, fake joint ventures) that ended up in the
    signal log. The model is now restricted to interpreting ONLY the
    supplied numbers, news headlines are passed as untrusted context
    that must be quoted-or-ignored, and the output format forces a
    verdict tied to the data.
    """

    def __init__(self):
        self._client = Groq(api_key=GROQ_API_KEY)

    def run(self, signal):
        ma20 = signal["ma20"]
        ma50 = signal["ma50"]
        close = signal["price"]
        rsi = signal["rsi"]
        vol_ratio = signal["volume_ratio"]
        change_pct = signal["change_pct"]

        trend = "bullish" if ma20 > ma50 else "bearish"
        rsi_state = "overbought" if rsi >= 70 else ("oversold" if rsi <= 30 else "neutral")
        ma20_dist = round((close - ma20) / ma20 * 100, 2)

        readable_triggers = "\n".join(
            f"  - {_TRIGGER_LABELS.get(r, r)}"
            for r in signal.get("reasons", [])
            if not r.startswith("Vx")
        )

        news_section = (
            f"\nHeadlines (may be irrelevant — only reference if clearly about this ticker):\n{signal['news']}\n"
            if signal.get("news") and signal["news"] != "No recent news."
            else ""
        )

        system_msg = (
            "You are a quantitative analyst covering the Indonesian Stock Exchange (IDX). "
            "STRICT RULES: (1) Interpret ONLY the numbers provided. "
            "(2) NEVER invent, assume, or speculate about news, partnerships, "
            "corporate actions, fundamentals, or catalysts. If no headline is "
            "provided, do not mention news at all. "
            "(3) Never invent price levels or figures not given. "
            "(4) The realistic entry is the NEXT day's open, not today's close — "
            "factor in gap risk when judging actionability. "
            "(5) IDX context: T+2 settlement, tiered auto-rejection limits, retail-driven flows."
        )

        user_msg = f"""Review this IDX momentum signal using ONLY the data below:

Ticker: {signal['ticker']}
Price: {close} ({change_pct:+.2f}% today, {ma20_dist:+.2f}% above MA20)
Volume: {vol_ratio}x 20-day average | Avg daily value: Rp {signal.get('avg_value_bn', '?')} bn
RSI(14): {rsi} ({rsi_state})
Trend: MA20 {ma20} vs MA50 {ma50} -> {trend}{news_section}

Signal triggers:
{readable_triggers}

Write 2-3 sentences: (a) trend strength per the MAs, (b) what this volume/price combination implies, (c) verdict — "ACTIONABLE at next open" or "NO TRADE" — with the single biggest risk. No short recommendations."""

        try:
            r = self._client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.2,
                max_tokens=300,
            )
            return r.choices[0].message.content.strip()
        except Exception as e:
            print(f"[NarratorAgent] API error for {signal.get('ticker')}: {e}")
            return "AI insight unavailable."
