def format_signal_message(signal):
    return (
        f"🔥 <b>{signal['ticker']}</b>\n"
        f"Price: {signal['price']} ({signal['change_pct']:+.2f}%)\n"
        f"RSI(14): {signal['rsi']} | Volume: {signal['volume_ratio']}x\n"
        f"Liquidity: Rp {signal['avg_value_bn']} bn/day (20d avg)\n"
        f"MA20 / MA50: {signal['ma20']} / {signal['ma50']}\n"
        f"Confidence: <b>{signal['confidence']}</b> | Score: <b>{signal['score']}/100</b>\n\n"
        f"Triggers: {signal['reason']}\n"
        f"⚠️ Entry basis: next-day open (gap risk applies)\n\n"
        f"Insight:\n{signal['insight']}"
    )
