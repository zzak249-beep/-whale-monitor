# 🤖 Sniper Bot V36 — Quantum Edge (BingX + Telegram + Railway)

Bot de trading automático 24/7 para futuros en BingX con notificaciones completas vía Telegram.

---

## 📁 Estructura del Proyecto

```
sniper-bot-v36/
├── main.py               ← Cerebro del bot (arrancar esto)
├── config.py             ← Configuración centralizada
├── indicators.py         ← Motor Quantum Edge V36
├── bingx.py              ← API BingX (órdenes, datos, firmas)
├── telegram_notifier.py  ← Todas las notificaciones Telegram
├── requirements.txt      ← Dependencias Python
├── Procfile              ← Comando de arranque para Railway
├── .env.example          ← Plantilla de variables (COPIAR a .env)
└── .gitignore            ← Excluye .env del repositorio
```

---

## 🚀 Despliegue en Railway (paso a paso)

### 1. Crear tu Bot de Telegram
1. Abre Telegram y busca `@BotFather`
2. Envía `/newbot` y sigue los pasos → obtendrás el **TELEGRAM_TOKEN**
3. Busca `@userinfobot` → te enviará tu **TELEGRAM_CHAT_ID**

### 2. Subir a GitHub
```bash
git init
git add .
git commit -m "Sniper Bot V36 inicial"
git remote add origin https://github.com/TU_USUARIO/sniper-bot-v36.git
git push -u origin main
```
> ⚠️ Nunca subas el archivo `.env` — está en `.gitignore`

### 3. Conectar Railway
1. Ve a [railway.app](https://railway.app) → **New Project → Deploy from GitHub repo**
2. Selecciona tu repositorio
3. En la pestaña **Variables**, añade todas estas:

| Variable | Valor |
|---|---|
| `BINGX_API_KEY` | Tu API Key de BingX |
| `BINGX_SECRET_KEY` | Tu Secret Key de BingX |
| `TELEGRAM_TOKEN` | Token del bot de Telegram |
| `TELEGRAM_CHAT_ID` | Tu Chat ID de Telegram |
| `SYMBOL` | `BTC-USDT` |
| `TIMEFRAME` | `3m` |
| `LEVERAGE` | `10` |
| `TRADE_MARGIN` | `25` |
| `DRY_RUN` | `true` (simulación) o `false` (real) |

4. Railway detecta el `Procfile` y arranca automáticamente.

---

## 📲 Notificaciones Telegram que recibirás

| Evento | Cuándo |
|---|---|
| 🤖 **Bot iniciado** | Al arrancar Railway |
| 🟢 **Señal LONG** | Cuando se detecta entrada alcista |
| 🔴 **Señal SHORT** | Cuando se detecta entrada bajista |
| ✅ **Orden ejecutada** | Confirmación de BingX (modo real) |
| ⚠️ **Error de orden** | Si BingX rechaza la orden |
| ⏳ **Time Stop** | Al cerrar por límite de velas |
| 💓 **Heartbeat** | Cada ~1 hora (bot vivo) |
| ❌ **Error del loop** | Cualquier excepción inesperada |
| 🛑 **Bot detenido** | Si Railway reinicia o hay fallo fatal |

---

## ⚙️ Parámetros Ajustables (en config.py)

| Parámetro | Default | Descripción |
|---|---|---|
| `PIVOT_LEN` | 5 | Longitud del ZigZag para niveles |
| `ADX_MIN` | 20 | Fuerza mínima de tendencia |
| `VOL_MULT` | 1.5 | Multiplicador de volumen institucional |
| `TIME_STOP` | 15 | Velas máximas por posición (45 min) |

---

## 🔒 Modo Seguro

Por defecto `DRY_RUN=true` → El bot **analiza y notifica** pero **NO coloca órdenes reales**.

Para operar con dinero real, cambia en Railway:
```
DRY_RUN=false
```

---

## ⚠️ Advertencia

El trading de futuros con apalancamiento conlleva riesgo de pérdida total del capital.
Prueba siempre en modo `DRY_RUN=true` antes de activar dinero real.
