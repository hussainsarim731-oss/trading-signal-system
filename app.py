
import streamlit as st
import websocket
import json
import threading
import time
from collections import defaultdict, deque
from datetime import datetime

st.set_page_config(page_title="Live Trading Signal System", page_icon="📊")
st.title("📊 Live Trading Signal System")

PAIRS = [
    "EUR/USD","GBP/USD","USD/JPY","AUD/USD","USD/CAD","EUR/GBP","USD/CHF",
    "NZD/USD","EUR/JPY","GBP/JPY","AUD/JPY","EUR/AUD","GBP/AUD","EUR/CAD",
    "GBP/CAD","AUD/CAD","CHF/JPY","EUR/CHF","GBP/CHF","NZD/JPY","AUD/NZD",
    "EUR/NZD","GBP/NZD","USD/SGD","USD/HKD","USD/TRY","USD/MXN","USD/ZAR",
    "USD/PLN","USD/NOK","USD/SEK","USD/DKK"
]

if "ticks" not in st.session_state:
    st.session_state.ticks = defaultdict(lambda: deque(maxlen=5000))

pair = st.selectbox("Pair", PAIRS)
seconds = st.selectbox("Candle", [5, 15, 30])

api_key = st.secrets["TWELVE_DATA_API_KEY"]

def on_message(ws, message):
    try:
        data = json.loads(message)
        if data.get("event") == "price":
            symbol = data.get("symbol")
            price = float(data.get("price"))
            ts = float(data.get("timestamp", time.time()))
            st.session_state.ticks[symbol].append((ts, price))
    except Exception:
        pass

def on_error(ws, error):
    pass

def start_stream(symbol):
    url = f"wss://ws.twelvedata.com/v1/quotes/price?apikey={api_key}"
    ws = websocket.WebSocketApp(
        url,
        on_message=on_message,
        on_error=on_error
    )
    ws.on_open = lambda ws: ws.send(json.dumps({
        "action": "subscribe",
        "params": {"symbols": symbol}
    }))
    ws.run_forever()

if st.button("▶️ Start Live Data"):
    if "stream_started" not in st.session_state:
        threading.Thread(target=start_stream, args=(pair,), daemon=True).start()
        st.session_state.stream_started = True
        st.success("Live stream started")

ticks = list(st.session_state.ticks[pair])

if ticks:
    latest = ticks[-1][1]
    st.metric("Live Price", latest)

    now = time.time()
    start = now - seconds
    candle_ticks = [(t, p) for t, p in ticks if t >= start]

    if candle_ticks:
        prices = [p for t, p in candle_ticks]
        st.write("Open:", prices[0])
        st.write("High:", max(prices))
        st.write("Low:", min(prices))
        st.write("Close:", prices[-1])
        st.info(f"{seconds}-second candle is building...")

    time.sleep(1)
    st.rerun()
else:
    st.info("Start Live Data dabao.")
