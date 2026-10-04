import streamlit as st
import websocket
import json
import threading
import time
from collections import defaultdict, deque
import pandas as pd
import numpy as np

st.set_page_config(
    page_title="Live Direction Analyzer",
    page_icon="📊"
)

st.title("📊 Live Direction Analyzer")

PAIRS = [
    "EUR/USD","GBP/USD","USD/JPY","AUD/USD","USD/CAD","EUR/GBP",
    "USD/CHF","NZD/USD","EUR/JPY","GBP/JPY","AUD/JPY","EUR/AUD",
    "GBP/AUD","EUR/CAD","GBP/CAD","AUD/CAD","CHF/JPY","EUR/CHF",
    "GBP/CHF","NZD/JPY","AUD/NZD","EUR/NZD","GBP/NZD","USD/SGD",
    "USD/HKD","USD/TRY","USD/MXN","USD/ZAR","USD/PLN","USD/NOK",
    "USD/SEK","USD/DKK"
]

TIMEFRAMES = {
    "5 sec": 5,
    "15 sec": 15,
    "30 sec": 30,
    "1 min": 60
}

@st.cache_resource
def get_store():
    return {
        "ticks": defaultdict(lambda: deque(maxlen=30000)),
        "running": set(),
        "lock": threading.Lock()
    }

store = get_store()

pair = st.selectbox("Select Pair", PAIRS)
timeframe = st.selectbox("Select Timeframe", list(TIMEFRAMES.keys()))
tf = TIMEFRAMES[timeframe]

API_KEY = st.secrets["TWELVE_DATA_API_KEY"]


def on_message(ws, message):
    try:
        data = json.loads(message)

        if data.get("event") == "price":
            symbol = data.get("symbol")
            price = data.get("price")
            timestamp = data.get("timestamp", time.time())

            if symbol and price:
                with store["lock"]:
                    store["ticks"][symbol].append(
                        (float(timestamp), float(price))
                    )

    except Exception:
        pass


def start_stream(symbol):

    with store["lock"]:
        if symbol in store["running"]:
            return
        store["running"].add(symbol)

    try:
        url = (
            "wss://ws.twelvedata.com/v1/quotes/price?apikey="
            + API_KEY
        )

        ws = websocket.WebSocketApp(
            url,
            on_message=on_message
        )

        def on_open(w):
            w.send(json.dumps({
                "action": "subscribe",
                "params": {
                    "symbols": symbol
                }
            }))

        ws.on_open = on_open
        ws.run_forever()

    except Exception:
        pass

    finally:
        with store["lock"]:
            store["running"].discard(symbol)


def build_candles(ticks, seconds):

    if len(ticks) < 10:
        return pd.DataFrame()

    df = pd.DataFrame(
        ticks,
        columns=["timestamp", "price"]
    )

    df["bucket"] = (
        df["timestamp"].astype(int) // seconds
    ) * seconds

    candles = df.groupby("bucket")["price"].agg(
        open="first",
        high="max",
        low="min",
        close="last"
    ).reset_index()

    return candles


def market_analysis(candles):

    if len(candles) < 20:
        return None

    close = candles["close"].astype(float)
    high = candles["high"].astype(float)
    low = candles["low"].astype(float)

    bullish = 0
    bearish = 0

    # TREND
    ema20 = close.ewm(span=20, adjust=False).mean()

    if close.iloc[-1] > ema20.iloc[-1]:
        bullish += 1
    elif close.iloc[-1] < ema20.iloc[-1]:
        bearish += 1

    # MOVING AVERAGE
    sma5 = close.rolling(5).mean()
    sma10 = close.rolling(10).mean()

    if sma5.iloc[-1] > sma10.iloc[-1]:
        bullish += 1
    elif sma5.iloc[-1] < sma10.iloc[-1]:
        bearish += 1

    # RSI
    delta = close.diff()

    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()

    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    if rsi.iloc[-1] > 55:
        bullish += 1
    elif rsi.iloc[-1] < 45:
        bearish += 1

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()

    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()

    if macd.iloc[-1] > signal.iloc[-1]:
        bullish += 1
    elif macd.iloc[-1] < signal.iloc[-1]:
        bearish += 1

    # SUPPORT / RESISTANCE
    support = low.rolling(10).min().iloc[-1]
    resistance = high.rolling(10).max().iloc[-1]
    price = close.iloc[-1]

    middle = (support + resistance) / 2

    if price > middle:
        bullish += 1
    elif price < middle:
        bearish += 1

    # CANDLE DIRECTION
    last_open = candles["open"].iloc[-1]
    last_close = candles["close"].iloc[-1]

    if last_close > last_open:
        bullish += 1
    elif last_close < last_open:
        bearish += 1

    # MOMENTUM
    momentum = close.iloc[-1] - close.iloc[-4]

    if momentum > 0:
        bullish += 1
    elif momentum < 0:
        bearish += 1

    # FINAL DECISION
    if bullish >= 5 and bullish > bearish:
        return "UP", bullish, bearish

    if bearish >= 5 and bearish > bullish:
        return "DOWN", bullish, bearish

    return "NO TRADE", bullish, bearish


# Start live data automatically
threading.Thread(
    target=start_stream,
    args=(pair,),
    daemon=True
).start()


if st.button(
    "▶️ START ANALYZE",
    use_container_width=True
):

    # 5 second countdown
    box = st.empty()

    for n in range(5, 0, -1):
        box.markdown(
            f"""
            <div style="
                text-align:center;
                font-size:70px;
                font-weight:bold;">
                {n}
            </div>
            """,
            unsafe_allow_html=True
        )
        time.sleep(1)

    box.empty()

    # Get latest real market ticks
    with store["lock"]:
        ticks = list(store["ticks"][pair])

    candles = build_candles(ticks, tf)

    result = market_analysis(candles)

    if result is None:

        st.warning(
            "Real market data abhi analysis ke liye kam hai. "
            "Signal generate nahi kiya gaya."
        )

    else:

        direction, bullish, bearish = result

        if direction == "UP":

            st.success(
                f"# 🟢 UP / CALL"
            )

            st.write(
                f"Strategy agreement: {bullish}/7 bullish"
            )

        elif direction == "DOWN":

            st.error(
                f"# 🔴 DOWN / PUT"
            )

            st.write(
                f"Strategy agreement: {bearish}/7 bearish"
            )

        else:

            st.warning(
                "# ⚪ NO TRADE"
            )

            st.write(
                f"Bullish: {bullish}/7 | Bearish: {bearish}/7"
            )

st.caption(
    "Real-time market data • Multi-strategy analysis • "
    "No guaranteed profit"
                    )
