"""
config.py — Sniper Bot V35: Golden Equilibrium
FIX: VOL_MULT default 0.9 (antes 1.5 — demasiado restrictivo)
FIX: ADX_MIN default 15 (antes 20)
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ─── BingX ────────────────────────────────────────────────
BINGX_API_KEY    = os.getenv("BINGX_API_KEY", "")
BINGX_SECRET_KEY = os.getenv("BINGX_SECRET_KEY", "")
BINGX_BASE_URL   = "https://open-api.bingx.com"
BINGX_MODE       = os.getenv("BINGX_MODE", "oneway")  # "oneway" o "hedge"

# ─── Telegram ─────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ─── Estrategia V35 ───────────────────────────────────────
EMA_FAST          = 7
EMA_MID           = 17
EMA_SLOW          = 21
PIVOT_LEN         = 5
# VOL_MULT: 0.9 permite más señales (1.5 era demasiado restrictivo para 3m)
VOL_MULT          = float(os.getenv("VOL_MULT",  "0.9"))
# ADX_MIN: 15 captura tendencias moderadas (20 eliminaba la mayoría del tiempo)
ADX_MIN           = float(os.getenv("ADX_MIN",   "15"))
ATR_SL_MULT       = float(os.getenv("ATR_SL_MULT","0.5"))
CANDLE_INTERVAL   = os.getenv("CANDLE_INTERVAL", "3m")
TIME_STOP_CANDLES = 15          # 15 × 3min = 45 min

# ─── Riesgo ───────────────────────────────────────────────
CAPITAL_PCT     = float(os.getenv("CAPITAL_PCT",    "2"))
MAX_OPEN_TRADES = int(os.getenv("MAX_TRADES",       "3"))
LEVERAGE        = int(os.getenv("LEVERAGE",         "5"))
MIN_ORDER_USDT  = float(os.getenv("MIN_ORDER_USDT", "6.0"))

# ─── Scanner ──────────────────────────────────────────────
TOP_N_SYMBOLS         = 20
SCAN_INTERVAL_MINUTES = 60

# ─── Aprendizaje ──────────────────────────────────────────
DATA_DIR            = "data"
LEARNING_FILE       = "data/trades.json"
MIN_TRADES_TO_LEARN = 10
SYMBOL_BLACKLIST_WR = 30

# ─── Modo ─────────────────────────────────────────────────
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
