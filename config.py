import os
from dotenv import load_dotenv

load_dotenv()

# ─── BingX API ───────────────────────────────────────────────
BINGX_API_KEY    = os.getenv("BINGX_API_KEY", "")
BINGX_SECRET_KEY = os.getenv("BINGX_SECRET_KEY", "")
BASE_URL         = "https://open-api.bingx.com"

# ─── Telegram ────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ─── Trading Config ──────────────────────────────────────────
SYMBOL       = os.getenv("SYMBOL",    "BTC-USDT")
TIMEFRAME    = os.getenv("TIMEFRAME", "3m")
LEVERAGE     = int(os.getenv("LEVERAGE",     10))
TRADE_MARGIN = float(os.getenv("TRADE_MARGIN", 25.0))   # USDT por trade
DRY_RUN      = os.getenv("DRY_RUN", "true").lower() == "true"

# ─── Parámetros V36 Quantum Edge ─────────────────────────────
PIVOT_LEN    = 5
ADX_MIN      = 20
VOL_MULT     = 1.5
TIME_STOP    = 15   # velas máximas en posición (15 × 3m = 45 min)
