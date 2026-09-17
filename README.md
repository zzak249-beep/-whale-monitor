# Crowding + CISD Bot v2

Bot de **solo señales** (no opera, sin API keys). Usa endpoints públicos de BingX.

## Por qué la v1 no daba señales

1. **Las klines no traían volumen** → score CISD nunca llegaba a 4
2. Umbral CISD `score >= 4` demasiado alto
3. Retest demasiado estricto (no contaba la vela de ruptura)
4. Calentamiento 30h + 200 muestras
5. Z-basis 2.0 y EXT 80 muy restrictivos

## Qué cambia en v2

| Parámetro | v1 | v2 |
|-----------|----|----|
| Volumen en klines | No | **Sí** |
| CISD min score | 4 | **2** |
| Retest | Estricto | Flexible (incluye vela actual) |
| Z_BASIS | 2.0 | **1.6** |
| Z_OI | 1.0 | **0.8** |
| EXT_PCT | 80 | **75** |
| MIN_HORAS | 30 | **18** |
| MIN_MUESTRAS | 200 | **120** |
| TG_SIGNALS | false | **true** |

## Variables Railway recomendadas

```
TIMEFRAME=15m
SCAN_SEC=300
MIN_VOL_24H=1500000
MAX_SYMBOLS=200
HIST_HORAS=168
MIN_HORAS=18
MIN_MUESTRAS=120
OI_LOOK_H=6
Z_BASIS=1.6
Z_OI=0.8
EXT_PCT=75
ATR_LEN=14
SL_ATR=1.5
TP_R=2.0
MAX_BARS=16
MIN_ATR_PCT=0.6
COST_PCT=0.25
MAX_COST_R=0.30
CISD_MIN_SCORE=2
CISD_REQUIRE_RETEST=true
STATE=/data/crowding_state.json
CSV=/data/crowding_ops.csv
TG_TOKEN=tu_token
TG_CHAT=tu_chat_id
TG_SIGNALS=true
TG_CLOSES=true
REPORT_HOUR=7
```

## Deploy

1. Sube este repo a GitHub
2. Railway → New Project → volume en `/data`
3. Pega variables
4. Redeploy

## Calentamiento

Con v2: ~18h + 120 muestras por símbolo (antes 30h/200).
