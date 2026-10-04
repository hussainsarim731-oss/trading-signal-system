import streamlit as st
import websocket
import json
import threading
import time
from collections import defaultdict, deque
import pandas as pd
import numpy as np

st.set_page_config(page_title="Live Trading Signal System", page_icon="📊")
st.title("📊 Live Trading Signal System")

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

pair = st.selectbox("Pair", PAIRS)
timeframe_name = st.selectbox("Candle", list(TIMEFRAMES.keys()))
TF = TIMEFRAMES[timeframe_name]

api_key = st.secrets["TWELVE_DATA_API_KEY"]


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
            + api_key
        )

        ws = websocket.WebSocketApp(
            url,
            on_message=on_message
        )

        def opened(w):
            w.send(json.dumps({
                "action": "subscribe",
                "params": {"symbols": symbol}
            }))

        ws.on_open = opened
        ws.run_forever()

    except Exception:
        pass

    finally:
        with store["lock"]:
            store["running"].discard(symbol)


def make_candles(ticks, seconds):
    if len(ticks) < 2:
        return pd.DataFrame()

    df = pd.DataFrame(ticks, columns=["timestamp", "price"])

    df["timestamp"] = pd.to_datetime(
        df["timestamp"],
        unit="s",
        utc=True
    )

    df["bucket"] = (
        df["timestamp"].astype("int64") // 1_000_000_000
    ) // seconds * seconds

    candles = df.groupby("bucket")["price"].agg(
        open="first",
        high="max",
        low="min",
        close="last"
    ).reset_index()

    candles["timestamp"] = pd.to_datetime(
        candles["bucket"],
        unit="s",
        utc=True
    )

    return candles


def analyze(candles):

    if len(candles) < 30:
        return None

    c = candles["close"].astype(float)
    h = candles["high"].astype(float)
    l = candles["low"].astype(float)

    result = []

    # 1. TREND
    ema20 = c.ewm(span=20, adjust=False).mean()

    if c.iloc[-1] > ema20.iloc[-1] and ema20.iloc[-1] > ema20.iloc[-2]:
        result.append(("Trend", "BULLISH"))
    elif c.iloc[-1] < ema20.iloc[-1] and ema20.iloc[-1] < ema20.iloc[-2]:
        result.append(("Trend", "BEARISH"))
    else:
        result.append(("Trend", "NEUTRAL"))

    # 2. MOVING AVERAGES
    sma5 = c.rolling(5).mean()
    sma10 = c.rolling(10).mean()
    sma20 = c.rolling(20).mean()

    if sma5.iloc[-1] > sma10.iloc[-1] > sma20.iloc[-1]:
        result.append(("Moving Average", "BULLISH"))
    elif sma5.iloc[-1] < sma10.iloc[-1] < sma20.iloc[-1]:
        result.append(("Moving Average", "BEARISH"))
    else:
        result.append(("Moving Average", "NEUTRAL"))

    # 3. RSI
    delta = c.diff()

    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()

    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    if rsi.iloc[-1] >= 55:
        result.append(("RSI", "BULLISH"))
    elif rsi.iloc[-1] <= 45:
        result.append(("RSI", "BEARISH"))
    else:
        result.append(("RSI", "NEUTRAL"))

    # 4. MACD
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()

    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()

    if macd.iloc[-1] > signal.iloc[-1]:
        result.append(("MACD", "BULLISH"))
    elif macd.iloc[-1] < signal.iloc[-1]:
        result.append(("MACD", "BEARISH"))
    else:
        result.append(("MACD", "NEUTRAL"))

    # 5. SUPPORT / RESISTANCE
    support = l.rolling(20).min().iloc[-1]
    resistance = h.rolling(20).max().iloc[-1]
    price = c.iloc[-1]

    middle = (support + resistance) / 2

    if price > middle:
        result.append(("Support/Resistance", "BULLISH"))
    elif price < middle:
        result.append(("Support/Resistance", "BEARISH"))
    else:
        result.append(("Support/Resistance", "NEUTRAL"))

    # 6. CANDLESTICK
    last_open = candles["open"].iloc[-1]
    last_close = candles["close"].iloc[-1]

    if last_close > last_open:
        result.append(("Candlestick", "BULLISH"))
    elif last_close < last_open:
        result.append(("Candlestick", "BEARISH"))
    else:
        result.append(("Candlestick", "NEUTRAL"))

    # 7. MOMENTUM / VOLATILITY
    change = c.diff().iloc[-1]

    ranges = h - l
    current_range = ranges.iloc[-1]
    average_range = ranges.rolling(10).mean().iloc[-1]

    if current_range > average_range:
        if change > 0:
            result.append(("Momentum/Volatility", "BULLISH"))
        elif change < 0:
            result.append(("Momentum/Volatility", "BEARISH"))
        else:
            result.append(("Momentum/Volatility", "NEUTRAL"))
    else:
        result.append(("Momentum/Volatility", "NEUTRAL"))

    bullish = sum(x[1] == "BULLISH" for x in result)
    bearish = sum(x[1] == "BEARISH" for x in result)

    if bullish >= 5 and bullish > bearish:
        direction = "🟢 UP / CALL"
    elif bearish >= 5 and bearish > bullish:
        direction = "🔴 DOWN / PUT"
    else:
        direction = "⚪ NO TRADE"

    return result, bullish, bearish, direction, rsi.iloc[-1]


# Start live stream
threading.Thread(
    target=start_stream,
    args=(pair,),
    daemon=True
).start()


with store["lock"]:
    ticks = list(store["ticks"][pair])


if ticks:

    latest_price = ticks[-1][1]

    st.metric(
        "Live Price",
        f"{latest_price:.6f}"
    )

    candles = make_candles(ticks, TF)

    if len(candles) >= 30:

        analysis = analyze(candles)

        if analysis:

            results, bullish, bearish, direction, rsi_value = analysis

            st.subheader("🎯 LIVE DIRECTION")

            if "UP" in direction:
                st.success(direction)
            elif "DOWN" in direction:
                st.error(direction)
            else:
                st.warning(direction)

            st.write(
                f"**Strategy Agreement:** "
                f"🟢 {bullish}/7 Bullish | "
                f"🔴 {bearish}/7 Bearish"
            )

            st.write(
                f"**RSI:** {rsi_value:.2f}"
            )

            st.subheader("📊 Strategy Analysis")

            for name, value in results:

                if value == "BULLISH":
                    st.write(f"🟢 **{name}:** BULLISH")

                elif value == "BEARISH":
                    st.write(f"🔴 **{name}:** BEARISH")

                else:
                    st.write(f"⚪ **{name}:** NEUTRAL")

            last = candles.iloc[-1]

            st.subheader("🕯️ Latest Candle")

            st.write(
                f"Open: {last['open']:.6f} | "
                f"High: {last['high']:.6f} | "
                f"Low: {last['low']:.6f} | "
                f"Close: {last['close']:.6f}"
            )

        else:
            st.info("Analysis prepare ho rahi hai...")

    else:

        remaining = 30 - len(candles)

        st.info(
            f"Live market data aa raha hai. "
            f"Analysis ke liye {remaining} candles aur collect ho rahi hain..."
        )

else:

    st.info("Live market data connect ho rahi hai...")


time.sleep(2)
st.rerun()
