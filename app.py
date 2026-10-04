import streamlit as st
import websocket
import json
import threading
import time
from collections import defaultdict, deque

st.set_page_config(page_title="Live Trading Signal System", page_icon="📊")
st.title("📊 Live Trading Signal System")

PAIRS = ["EUR/USD","GBP/USD","USD/JPY","AUD/USD","USD/CAD","EUR/GBP","USD/CHF","NZD/USD","EUR/JPY","GBP/JPY","AUD/JPY","EUR/AUD","GBP/AUD","EUR/CAD","GBP/CAD","AUD/CAD","CHF/JPY","EUR/CHF","GBP/CHF","NZD/JPY","AUD/NZD","EUR/NZD","GBP/NZD","USD/SGD","USD/HKD","USD/TRY","USD/MXN","USD/ZAR","USD/PLN","USD/NOK","USD/SEK","USD/DKK"]

@st.cache_resource
def get_store():
    return {"ticks": defaultdict(lambda: deque(maxlen=20000)), "running": set()}

store = get_store()

pair = st.selectbox("Pair", PAIRS)
candle = st.selectbox("Candle", [5, 15, 30, 60], format_func=lambda x: "1 min" if x == 60 else f"{x} sec")

api_key = st.secrets["TWELVE_DATA_API_KEY"]

def on_message(ws, message):
    try:
        data = json.loads(message)
        if data.get("event") == "price":
            symbol = data.get("symbol")
            price = data.get("price")
            ts = data.get("timestamp", time.time())
            if symbol and price:
                store["ticks"][symbol].append((float(ts), float(price)))
    except Exception:
        pass

def start_stream(symbol):
    if symbol in store["running"]:
        return
    store["running"].add(symbol)
    url = "wss://ws.twelvedata.com/v1/quotes/price?apikey=" + api_key
    ws = websocket.WebSocketApp(url, on_message=on_message)
    ws.on_open = lambda w: w.send(json.dumps({"action":"subscribe","params":{"symbols":symbol}}))
    ws.run_forever()
    store["running"].discard(symbol)

if st.button("▶️ Start Live Data"):
    threading.Thread(target=start_stream, args=(pair,), daemon=True).start()
    st.success("Live stream started")

ticks = list(store["ticks"][pair])

if ticks:
    latest = ticks[-1][1]
    st.metric("Live Price", f"{latest:.6f}")

    now = time.time()
    candle_ticks = [(t,p) for t,p in ticks if t >= now - candle]

    if len(candle_ticks) >= 2:
        prices = [p for t,p in candle_ticks]
        o = prices[0]
        h = max(prices)
        l = min(prices)
        c = prices[-1]

        st.write("Open:", o)
        st.write("High:", h)
        st.write("Low:", l)
        st.write("Close:", c)

        if c > o:
            st.success("🟢 UP / CALL")
        elif c < o:
            st.error("🔴 DOWN / PUT")
        else:
            st.warning("⚪ NO TRADE")

        st.caption("Real-time Twelve Data price stream. Signal is not guaranteed.")
    else:
        st.info("Candle data collect ho raha hai...")
else:
    st.info("▶️ Start Live Data dabao.")

time.sleep(2)
st.rerun()
