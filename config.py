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

# ─── Modo de operación ───────────────────────────────────────
# MULTI  = escanear todas las monedas BingX y elegir la mejor
# SINGLE = operar solo el par definido en SYMBOL
BOT_MODE     = os.getenv("BOT_MODE", "MULTI").upper()
SYMBOL       = os.getenv("SYMBOL",    "BTC-USDT")   # usado solo en modo SINGLE

# ─── Trading Config ──────────────────────────────────────────
TIMEFRAME    = os.getenv("TIMEFRAME", "3m")
LEVERAGE     = int(os.getenv("LEVERAGE",     10))
TRADE_MARGIN = float(os.getenv("TRADE_MARGIN", 25.0))   # USDT por trade
DRY_RUN      = os.getenv("DRY_RUN", "true").lower() == "true"

# ─── Scanner Multi-Moneda ────────────────────────────────────
MIN_VOLUME_24H  = float(os.getenv("MIN_VOLUME_24H", 5_000_000))  # USDT/24h mínimo
TOP_N_RESULTS   = int(os.getenv("TOP_N_RESULTS", 10))             # top resultados en Telegram
MAX_OPEN_TRADES = int(os.getenv("MAX_OPEN_TRADES", 3))            # máx posiciones simultáneas
SCAN_DELAY_MS   = int(os.getenv("SCAN_DELAY_MS", 120))            # ms entre requests al escanear

# ─── Parámetros V36 Quantum Edge ─────────────────────────────
PIVOT_LEN    = 5
ADX_MIN      = 20
VOL_MULT     = 1.5
TIME_STOP    = 15   # velas máximas en posición (15 × 3m = 45 min)
