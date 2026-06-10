import os

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Screener tunables
MIN_AVG_VALUE_IDR = float(os.getenv("MIN_AVG_VALUE_IDR", 5e9))  # liquidity gate
NEAR_ARA_FRAC = float(os.getenv("NEAR_ARA_FRAC", 0.8))          # ARA proximity gate
COST_ROUNDTRIP_PCT = float(os.getenv("COST_ROUNDTRIP_PCT", 0.6))
