import streamlit as st
import time
import json
import threading
from collections import defaultdict, deque
import websocket

st.set_page_config(page_title="Live Trading Signal System", page_icon="📊")
st.title("📊 Live Trading Signal System")

PAIRS = ["EUR/USD","GBP/USD","USD/JPY","AUD/USD","USD/CAD","EUR/GBP","USD/CHF","NZD/USD","EUR/JPY","GBP/JPY","AUD/JPY","EUR/AUD","GBP/AUD","EUR/CAD","GBP/CAD","AUD/CAD","CHF/JPY","EUR/CHF","GBP/CHF","NZD/JPY","AUD/NZD","EUR/NZD","GBP/NZD","USD/SGD","USD/HKD","USD/TRY","USD/MXN","USD/ZAR","USD/PLN","USD/NOK","USD/SEK","USD/DKK"]

if "prices" not in st.session_state:
    st.session_state.prices = defaultdict(lambda: deque(maxlen=10000))

if "running" not in st.session_state:
    st.session_state.running = False

pair = st.selectbox("Pair", PAIRS)
candle_seconds = st.selectbox("Candle", [5, 15, 30, 60], format_func=lambda x: "1 min" if x == 60 else f"{x} sec")

API_KEY = st.secrets["TWELVE_DATA_API_KEY"]

def receive(ws, message):
    try:
        data = json.loads(message)
        if data.get("event") == "price":
            symbol = data.get("symbol")
            price = data.get("price")
            timestamp = data.get("timestamp", time.time())
            if symbol and price:
                st.session_state.prices[symbol].append((float(timestamp), float(price)))
    except:
        pass

def stream(symbol):
    url = "wss://ws.twelvedata.com/v1/quotes/price?apikey=" + API_KEY
    ws = websocket.WebSocketApp(url, on_message=receive)
    ws.on_open = lambda w: w.send(json.dumps({"action":"subscribe","params":{"symbols":symbol}}))
    ws.run_forever()

if st.button("▶️ Start Live Data"):
    if not st.session_state.running:
        st.session_state.running = True
        threading.Thread(target=stream, args=(pair,), daemon=True).start()

data = list(st.session_state.prices[pair])

if data:
    latest = data[-1][1]
    st.metric("Live Price", latest)

    now = time.time()
    current = [(t,p) for t,p in data if t >= now-candle_seconds]

    if len(current) >= 2:
        prices = [p for t,p in current]
        open_price = prices[0]
        high_price = max(prices)
        low_price = min(prices)
        close_price = prices[-1]

        st.write("Open:", open_price)
        st.write("High:", high_price)
        st.write("Low:", low_price)
        st.write("Close:", close_price)

        if close_price > open_price:
            signal = "UP / CALL"
            st.success("🟢 " + signal)
        elif close_price < open_price:
            signal = "DOWN / PUT"
            st.error("🔴 " + signal)
        else:
            signal = "NO TRADE"
            st.warning("⚪ " + signal)

        st.caption("Signal is based on live Twelve Data price movement. It is not a guaranteed prediction.")

    time.sleep(1)
    st.rerun()
else:
    st.info("▶️ Start Live Data dabao.")
