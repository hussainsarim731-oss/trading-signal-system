import streamlit as st
import websocket
import json
import threading
import time
from collections import defaultdict, deque
import pandas as pd
import numpy as np
import requests

st.set_page_config(
    page_title="Live Direction Analyzer",
    page_icon="📊",
    layout="centered"
)

st.markdown("""
<style>
.main-title {
    text-align:center;
    font-size:32px;
    font-weight:800;
}
.result {
    text-align:center;
    font-size:48px;
    font-weight:900;
    padding:25px;
}
.small {
    text-align:center;
    font-size:18px;
}
</style>
""", unsafe_allow_html=True)

st.markdown(
    '<div class="main-title">📊 LIVE DIRECTION ANALYZER</div>',
    unsafe_allow_html=True
)

PAIRS = [
    "EUR/USD","GBP/USD","USD/JPY","AUD/USD",
    "USD/CAD","EUR/GBP","USD/CHF","NZD/USD",
    "EUR/JPY","GBP/JPY","AUD/JPY","EUR/AUD",
    "GBP/AUD","EUR/CAD","GBP/CAD","AUD/CAD",
    "CHF/JPY","EUR/CHF","GBP/CHF","NZD/JPY",
    "AUD/NZD","EUR/NZD","GBP/NZD","USD/SGD",
    "USD/HKD","USD/TRY","USD/MXN","USD/ZAR",
    "USD/PLN","USD/NOK","USD/SEK","USD/DKK"
]

TIMEFRAMES = {
    "5 sec": 5,
    "15 sec": 15,
    "30 sec": 30,
    "1 min": 60
}

pair = st.selectbox("PAIR", PAIRS)
timeframe = st.selectbox("TIMEFRAME", list(TIMEFRAMES.keys()))
tf = TIMEFRAMES[timeframe]

API_KEY = st.secrets["TWELVE_DATA_API_KEY"]


@st.cache_resource
def get_store():
    return {
        "ticks": defaultdict(lambda: deque(maxlen=30000)),
        "running": set(),
        "lock": threading.Lock()
    }


store = get_store()


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

        def opened(w):
            w.send(json.dumps({
                "action": "subscribe",
                "params": {
                    "symbols": symbol
                }
            }))

        ws.on_open = opened
        ws.run_forever()

    except Exception:
        pass

    finally:

        with store["lock"]:
            store["running"].discard(symbol)


def get_history(symbol):

    try:

        url = "https://api.twelvedata.com/time_series"

        params = {
            "symbol": symbol,
            "interval": "1min",
            "outputsize": 120,
            "apikey": API_KEY
        }

        response = requests.get(
            url,
            params=params,
            timeout=10
        )

        data = response.json()

        values = data.get("values", [])

        if not values:
            return pd.DataFrame()

        df = pd.DataFrame(values)

        df = df.rename(columns={
            "datetime": "timestamp"
        })

        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )

        df = df.dropna()

        df = df.sort_values("timestamp")

        return df[
            ["timestamp", "open", "high", "low", "close"]
        ].reset_index(drop=True)

    except Exception:
        return pd.DataFrame()


def live_candles(ticks, seconds):

    if len(ticks) < 2:
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


def analyze_market(df):

    if len(df) < 30:
        return None

    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)

    bullish = 0
    bearish = 0

    # 1 TREND
    ema20 = close.ewm(
        span=20,
        adjust=False
    ).mean()

    if close.iloc[-1] > ema20.iloc[-1]:
        bullish += 1
    elif close.iloc[-1] < ema20.iloc[-1]:
        bearish += 1

    # 2 MOVING AVERAGE
    sma5 = close.rolling(5).mean()
    sma10 = close.rolling(10).mean()
    sma20 = close.rolling(20).mean()

    if (
        sma5.iloc[-1]
        > sma10.iloc[-1]
        > sma20.iloc[-1]
    ):
        bullish += 1

    elif (
        sma5.iloc[-1]
        < sma10.iloc[-1]
        < sma20.iloc[-1]
    ):
        bearish += 1

    # 3 RSI
    delta = close.diff()

    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()

    rs = gain / loss.replace(0, np.nan)

    rsi = 100 - (
        100 / (1 + rs)
    )

    if rsi.iloc[-1] > 55:
        bullish += 1

    elif rsi.iloc[-1] < 45:
        bearish += 1

    # 4 MACD
    ema12 = close.ewm(
        span=12,
        adjust=False
    ).mean()

    ema26 = close.ewm(
        span=26,
        adjust=False
    ).mean()

    macd = ema12 - ema26

    macd_signal = macd.ewm(
        span=9,
        adjust=False
    ).mean()

    if macd.iloc[-1] > macd_signal.iloc[-1]:
        bullish += 1

    elif macd.iloc[-1] < macd_signal.iloc[-1]:
        bearish += 1

    # 5 SUPPORT / RESISTANCE
    support = low.rolling(20).min().iloc[-1]
    resistance = high.rolling(20).max().iloc[-1]

    price = close.iloc[-1]

    middle = (
        support + resistance
    ) / 2

    if price > middle:
        bullish += 1

    elif price < middle:
        bearish += 1

    # 6 CANDLESTICK
    last_open = df["open"].iloc[-1]
    last_close = df["close"].iloc[-1]

    body = abs(
        last_close - last_open
    )

    candle_range = (
        df["high"].iloc[-1]
        - df["low"].iloc[-1]
    )

    if candle_range > 0:

        body_ratio = (
            body / candle_range
        )

        if body_ratio > 0.35:

            if last_close > last_open:
                bullish += 1

            elif last_close < last_open:
                bearish += 1

    # 7 MOMENTUM / VOLATILITY
    if len(close) >= 5:

        momentum = (
            close.iloc[-1]
            - close.iloc[-5]
        )

        ranges = high - low

        current_range = ranges.iloc[-1]

        avg_range = (
            ranges
            .rolling(10)
            .mean()
            .iloc[-1]
        )

        if current_range >= avg_range:

            if momentum > 0:
                bullish += 1

            elif momentum < 0:
                bearish += 1

    if bullish >= 5 and bullish > bearish:
        signal = "UP"

    elif bearish >= 5 and bearish > bullish:
        signal = "DOWN"

    else:
        if bullish > bearish:
            signal = "UP"
        elif bearish > bullish:
            signal = "DOWN"
        else:
            signal = "NO TRADE"

    return signal, bullish, bearish


# Start live stream automatically

threading.Thread(
    target=start_stream,
    args=(pair,),
    daemon=True
).start()


if st.button(
    "🚀 START ANALYZE",
    use_container_width=True
):

    countdown = st.empty()

    # 5-second live analysis window
    start_time = time.time()

    for n in range(5, 0, -1):

        countdown.markdown(
            f"""
            <div class="result">
                {n}
            </div>
            """,
            unsafe_allow_html=True
        )

        time.sleep(1)

    countdown.empty()

    # Historical market data
    history = get_history(pair)

    # Latest live ticks
    with store["lock"]:
        ticks = list(
            store["ticks"][pair]
        )

    live = live_candles(
        ticks,
        tf
    )

    # Combine historical data with live data
    if not history.empty:

        analysis_df = history[
            ["open", "high", "low", "close"]
        ].copy()

        if not live.empty:

            live = live[
                ["open", "high", "low", "close"]
            ]

            analysis_df = pd.concat(
                [
                    analysis_df,
                    live
                ],
                ignore_index=True
            )

    else:

        analysis_df = live[
            ["open", "high", "low", "close"]
        ].copy() if not live.empty else pd.DataFrame()

    result = analyze_market(
        analysis_df
    )

    if result is None:

        st.warning(
            "Market data abhi sufficient nahi hai."
        )

    else:

        signal, bullish, bearish = result

        st.markdown("---")

        if signal == "UP":

            st.markdown(
                """
                <div class="result">
                    🟢 UP
                </div>
                """,
                unsafe_allow_html=True
            )

            st.markdown(
                f'<div class="small">CALL • Bullish {bullish}/7</div>',
                unsafe_allow_html=True
            )

        elif signal == "DOWN":

            st.markdown(
                """
                <div class="result">
                    🔴 DOWN
                </div>
                """,
                unsafe_allow_html=True
            )

            st.markdown(
                f'<div class="small">PUT • Bearish {bearish}/7</div>',
                unsafe_allow_html=True
            )

        else:

            st.markdown(
                """
                <div class="result">
                    ⚪ NO TRADE
                </div>
                """,
                unsafe_allow_html=True
            )

            st.markdown(
                f'<div class="small">Bullish {bullish}/7 • Bearish {bearish}/7</div>',
                unsafe_allow_html=True
            )

st.caption(
    "Real market data • Multi-strategy analysis • "
    "Signals are not guaranteed"
)
