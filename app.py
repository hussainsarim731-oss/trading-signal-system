import streamlit as st
import websocket
import json
import threading
import time
from collections import deque
from datetime import datetime

import requests
import pandas as pd
import numpy as np


# =========================================================
# SETTINGS
# =========================================================

st.set_page_config(
    page_title="Smart 5-Second Trading Signal",
    page_icon="📊",
    layout="centered"
)

API_KEY = st.secrets.get("TWELVE_DATA_API_KEY", "")

SYMBOL = "EUR/USD"
CANDLE_SECONDS = 5

MAX_TICKS = 5000
MAX_CANDLES = 1200

store = {
    "ticks": deque(maxlen=MAX_TICKS),
    "candles": deque(maxlen=MAX_CANDLES),
    "price": None,
    "ws_started": False,
    "lock": threading.Lock()
}


# =========================================================
# TECHNICAL INDICATORS
# =========================================================

def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def sma(series, period):
    return series.rolling(period).mean()


def rsi(series, period=9):
    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)

    result = 100 - (100 / (1 + rs))

    return result


def atr(df, period=14):
    high = df["high"]
    low = df["low"]
    close = df["close"]

    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    true_range = pd.concat(
        [tr1, tr2, tr3],
        axis=1
    ).max(axis=1)

    return true_range.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()


def adx(df, period=14):
    high = df["high"]
    low = df["low"]
    close = df["close"]

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(
        np.where(
            (up_move > down_move) & (up_move > 0),
            up_move,
            0
        ),
        index=df.index
    )

    minus_dm = pd.Series(
        np.where(
            (down_move > up_move) & (down_move > 0),
            down_move,
            0
        ),
        index=df.index
    )

    tr = pd.concat(
        [
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs()
        ],
        axis=1
    ).max(axis=1)

    atr_value = tr.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    plus_di = (
        100 *
        plus_dm.ewm(alpha=1 / period, adjust=False).mean()
        / atr_value.replace(0, np.nan)
    )

    minus_di = (
        100 *
        minus_dm.ewm(alpha=1 / period, adjust=False).mean()
        / atr_value.replace(0, np.nan)
    )

    dx = (
        100 *
        (plus_di - minus_di).abs()
        /
        (plus_di + minus_di).replace(0, np.nan)
    )

    return dx.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()


def macd(series):
    fast = ema(series, 8)
    slow = ema(series, 21)

    line = fast - slow
    signal = ema(line, 5)
    histogram = line - signal

    return line, signal, histogram


# =========================================================
# CANDLE BUILDER
# =========================================================

def build_candles():
    with store["lock"]:
        ticks = list(store["ticks"])

    if len(ticks) < 2:
        return

    rows = []

    for ts, price in ticks:
        bucket = int(ts // CANDLE_SECONDS) * CANDLE_SECONDS
        rows.append(
            {
                "bucket": bucket,
                "price": float(price)
            }
        )

    if not rows:
        return

    df = pd.DataFrame(rows)

    grouped = df.groupby("bucket")

    candles = []

    for bucket, group in grouped:
        prices = group["price"].values

        candles.append(
            {
                "time": bucket,
                "open": prices[0],
                "high": prices.max(),
                "low": prices.min(),
                "close": prices[-1]
            }
        )

    candles = sorted(
        candles,
        key=lambda x: x["time"]
    )

    with store["lock"]:
        store["candles"] = deque(
            candles[-MAX_CANDLES:],
            maxlen=MAX_CANDLES
        )


# =========================================================
# WEBSOCKET
# =========================================================

def websocket_worker():
    if not API_KEY:
        return

    url = "wss://ws.twelvedata.com/v1/quotes/price"

    try:
        ws = websocket.create_connection(
            url,
            timeout=10
        )

        ws.send(
            json.dumps(
                {
                    "action": "subscribe",
                    "params": {
                        "symbols": SYMBOL
                    }
                }
            )
        )

        while True:
            message = ws.recv()

            if not message:
                continue

            data = json.loads(message)

            price = None

            if isinstance(data, dict):
                if "price" in data:
                    price = data["price"]

                elif "close" in data:
                    price = data["close"]

            if price is None:
                continue

            try:
                price = float(price)
            except:
                continue

            now = time.time()

            with store["lock"]:
                store["price"] = price
                store["ticks"].append(
                    (now, price)
                )

            build_candles()

    except Exception:
        pass


def start_websocket():
    with store["lock"]:
        if store["ws_started"]:
            return

        store["ws_started"] = True

    thread = threading.Thread(
        target=websocket_worker,
        daemon=True
    )

    thread.start()


# =========================================================
# ANALYSIS ENGINE
# =========================================================

def analyze_market():

    with store["lock"]:
        candles = list(store["candles"])

    if len(candles) < 80:
        return {
            "signal": "NO TRADE",
            "confidence": 0,
            "bullish": 0,
            "bearish": 0,
            "reason": "5-second candle history is still collecting."
        }

    df = pd.DataFrame(candles)

    close = df["close"]

    df["ema9"] = ema(close, 9)
    df["ema21"] = ema(close, 21)
    df["ema50"] = ema(close, 50)

    df["rsi"] = rsi(close, 9)

    macd_line, macd_signal, macd_hist = macd(close)

    df["macd"] = macd_line
    df["macd_signal"] = macd_signal
    df["macd_hist"] = macd_hist

    df["atr"] = atr(df, 14)
    df["adx"] = adx(df, 14)

    df["sma20"] = sma(close, 20)

    latest = df.iloc[-1]
    previous = df.iloc[-2]

    bullish = 0
    bearish = 0

    reasons_up = []
    reasons_down = []

    # -----------------------------------------------------
    # 1. TREND
    # -----------------------------------------------------

    if (
        latest["ema9"] > latest["ema21"]
        and latest["ema21"] > latest["ema50"]
    ):
        bullish += 2
        reasons_up.append("EMA trend")

    elif (
        latest["ema9"] < latest["ema21"]
        and latest["ema21"] < latest["ema50"]
    ):
        bearish += 2
        reasons_down.append("EMA trend")

    # -----------------------------------------------------
    # 2. MOMENTUM
    # -----------------------------------------------------

    if latest["close"] > previous["close"]:
        bullish += 1
        reasons_up.append("Momentum")

    elif latest["close"] < previous["close"]:
        bearish += 1
        reasons_down.append("Momentum")

    # -----------------------------------------------------
    # 3. RSI
    # -----------------------------------------------------

    rsi_value = latest["rsi"]

    if 52 <= rsi_value <= 68:
        bullish += 1
        reasons_up.append("RSI")

    elif 32 <= rsi_value <= 48:
        bearish += 1
        reasons_down.append("RSI")

    # -----------------------------------------------------
    # 4. MACD
    # -----------------------------------------------------

    if (
        latest["macd_hist"] > 0
        and latest["macd_hist"] > previous["macd_hist"]
    ):
        bullish += 2
        reasons_up.append("MACD")

    elif (
        latest["macd_hist"] < 0
        and latest["macd_hist"] < previous["macd_hist"]
    ):
        bearish += 2
        reasons_down.append("MACD")

    # -----------------------------------------------------
    # 5. ADX TREND STRENGTH
    # -----------------------------------------------------

    adx_value = latest["adx"]

    if adx_value >= 20:

        if latest["ema9"] > latest["ema21"]:
            bullish += 1
            reasons_up.append("ADX trend")

        elif latest["ema9"] < latest["ema21"]:
            bearish += 1
            reasons_down.append("ADX trend")

    # -----------------------------------------------------
    # 6. BREAKOUT
    # -----------------------------------------------------

    recent = df.iloc[-21:-1]

    resistance = recent["high"].max()
    support = recent["low"].min()

    if latest["close"] > resistance:
        bullish += 2
        reasons_up.append("Breakout")

    elif latest["close"] < support:
        bearish += 2
        reasons_down.append("Breakdown")

    # -----------------------------------------------------
    # 7. CANDLE PRICE ACTION
    # -----------------------------------------------------

    body = abs(
        latest["close"] - latest["open"]
    )

    candle_range = (
        latest["high"] - latest["low"]
    )

    if candle_range > 0:

        body_ratio = body / candle_range

        if body_ratio >= 0.60:

            if latest["close"] > latest["open"]:
                bullish += 1
                reasons_up.append("Strong bullish candle")

            elif latest["close"] < latest["open"]:
                bearish += 1
                reasons_down.append("Strong bearish candle")

    # -----------------------------------------------------
    # 8. SWING STRUCTURE
    # -----------------------------------------------------

    swing_window = df.iloc[-10:-2]

    swing_high = swing_window["high"].max()
    swing_low = swing_window["low"].min()

    if latest["close"] > swing_high:
        bullish += 1
        reasons_up.append("Swing breakout")

    elif latest["close"] < swing_low:
        bearish += 1
        reasons_down.append("Swing breakdown")

    # -----------------------------------------------------
    # 9. VOLATILITY FILTER
    # -----------------------------------------------------

    atr_value = latest["atr"]

    if pd.isna(atr_value) or atr_value <= 0:
        return {
            "signal": "NO TRADE",
            "confidence": 0,
            "bullish": bullish,
            "bearish": bearish,
            "reason": "Volatility data unavailable."
        }

    # Detect extreme single-candle spike
    if candle_range > atr_value * 3:

        return {
            "signal": "NO TRADE",
            "confidence": 0,
            "bullish": bullish,
            "bearish": bearish,
            "reason": "Extreme volatility spike."
        }

    # -----------------------------------------------------
    # FINAL FILTER
    # -----------------------------------------------------

    total = bullish + bearish

    if total == 0:
        confidence = 0
    else:
        confidence = int(
            max(bullish, bearish) /
            total *
            100
        )

    # Require strong agreement
    if bullish >= 7 and bullish >= bearish + 3:

        signal = "UP"
        reason = ", ".join(reasons_up)

    elif bearish >= 7 and bearish >= bullish + 3:

        signal = "DOWN"
        reason = ", ".join(reasons_down)

    else:

        signal = "NO TRADE"

        reason = (
            "Strategies are not sufficiently aligned."
        )

    return {
        "signal": signal,
        "confidence": confidence,
        "bullish": bullish,
        "bearish": bearish,
        "reason": reason
    }


# =========================================================
# UI
# =========================================================

st.title("📊 Smart 5-Second Trading Signal")

st.caption(
    "Real market data • Multi-strategy analysis • "
    "No forced signals"
)

pair = st.selectbox(
    "Pair",
    ["EUR/USD"]
)

timeframe = st.selectbox(
    "Timeframe",
    ["5 Seconds"]
)

start = st.button(
    "🚀 START ANALYZE",
    use_container_width=True
)

start_websocket()

if start:

    progress = st.empty()

    for remaining in range(5, 0, -1):

        progress.markdown(
            f"# ⏱️ {remaining}"
        )

        time.sleep(1)

    progress.empty()

    result = analyze_market()

    st.divider()

    if result["signal"] == "UP":

        st.success(
            "# 🟢 UP"
        )

    elif result["signal"] == "DOWN":

        st.error(
            "# 🔴 DOWN"
        )

    else:

        st.warning(
            "# ⚪ NO TRADE"
        )

    st.write(
        f"Strategy agreement: "
        f"**Bullish {result['bullish']}** | "
        f"**Bearish {result['bearish']}**"
    )

    st.write(
        f"Internal agreement score: "
        f"**{result['confidence']}%**"
    )

    st.caption(
        f"Reason: {result['reason']}"
    )

    st.caption(
        "Agreement score is NOT a guaranteed probability "
        "of winning."
    )


# =========================================================
# LIVE STATUS
# =========================================================

with store["lock"]:
    live_price = store["price"]
    candle_count = len(store["candles"])

if live_price is not None:

    st.divider()

    st.metric(
        "Live Price",
        f"{live_price:.6f}"
    )

st.caption(
    f"5-second candles collected: {candle_count}"
)
