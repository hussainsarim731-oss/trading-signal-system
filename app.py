import streamlit as st
import requests
import pandas as pd

st.set_page_config(page_title="Trading Signal System", page_icon="📊")
st.title("📊 Trading Signal System")

pairs = ["EUR/USD","GBP/USD","USD/JPY","AUD/USD","USD/CAD","EUR/GBP","USD/CHF","NZD/USD","EUR/JPY","GBP/JPY","AUD/JPY","EUR/AUD","GBP/AUD","EUR/CAD","GBP/CAD","AUD/CAD","CHF/JPY","EUR/CHF","GBP/CHF","NZD/JPY","AUD/NZD","EUR/NZD","GBP/NZD","USD/SGD","USD/HKD","USD/TRY","USD/MXN","USD/ZAR","USD/PLN","USD/NOK","USD/SEK","USD/DKK"]

pair = st.selectbox("Pair", pairs)
timeframe = st.selectbox("Timeframe", ["1 min","5 min","15 min","30 min"])

interval = {"1 min":"1min","5 min":"5min","15 min":"15min","30 min":"30min"}[timeframe]

if st.button("🔄 Get Signal"):
    try:
        api_key = st.secrets["TWELVE_DATA_API_KEY"]
        url = "https://api.twelvedata.com/time_series"
        params = {"symbol":pair,"interval":interval,"outputsize":100,"apikey":api_key}
        r = requests.get(url, params=params, timeout=20)
        data = r.json()

        if "values" not in data:
            st.error("Market data nahi mili: " + str(data.get("message","Unknown error")))
        else:
            df = pd.DataFrame(data["values"])
            for c in ["open","high","low","close"]:
                df[c] = pd.to_numeric(df[c])

            df = df.iloc[::-1].reset_index(drop=True)
            close = df["close"]
            high = df["high"]
            low = df["low"]

            df["sma5"] = close.rolling(5).mean()
            df["sma10"] = close.rolling(10).mean()
            df["sma20"] = close.rolling(20).mean()

            delta = close.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / loss.replace(0, pd.NA)
            df["rsi"] = 100 - (100 / (1 + rs))

            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            df["macd"] = ema12 - ema26
            df["signal_line"] = df["macd"].ewm(span=9, adjust=False).mean()

            bull = 0
            bear = 0

            if close.iloc[-1] > df["sma20"].iloc[-1]: bull += 1
            else: bear += 1

            if close.iloc[-1] > df["sma5"].iloc[-1] and df["sma5"].iloc[-1] > df["sma20"].iloc[-1]: bull += 1
            elif close.iloc[-1] < df["sma5"].iloc[-1] and df["sma5"].iloc[-1] < df["sma20"].iloc[-1]: bear += 1

            if df["rsi"].iloc[-1] > 55: bull += 1
            elif df["rsi"].iloc[-1] < 45: bear += 1

            if df["macd"].iloc[-1] > df["signal_line"].iloc[-1]: bull += 1
            else: bear += 1

            support = low.tail(20).min()
            resistance = high.tail(20).max()

            if close.iloc[-1] > support and close.iloc[-1] > (support + resistance) / 2: bull += 1
            elif close.iloc[-1] < resistance and close.iloc[-1] < (support + resistance) / 2: bear += 1

            prev = df.iloc[-2]
            last = df.iloc[-1]

            if last["close"] > last["open"] and prev["close"] <= prev["open"]: bull += 1
            elif last["close"] < last["open"] and prev["close"] >= prev["open"]: bear += 1

            volatility = close.pct_change().tail(20).std()
            if volatility > close.pct_change().tail(50).std(): bull += 1
            else: bear += 1

            if bull >= 5 and bull > bear:
                signal = "CALL"
            elif bear >= 5 and bear > bull:
                signal = "PUT"
            else:
                signal = "NO TRADE"

            st.subheader("📈 Signal")
            if signal == "CALL":
                st.success("CALL")
            elif signal == "PUT":
                st.error("PUT")
            else:
                st.warning("NO TRADE")

            st.write("Bullish strategies:", bull, "/ 7")
            st.write("Bearish strategies:", bear, "/ 7")
            st.write("Current Price:", close.iloc[-1])
            st.write("RSI:", round(df["rsi"].iloc[-1], 2))

            st.caption("Signal is based on real Twelve Data market data. It is not a guarantee of profit or accuracy.")

    except Exception as e:
        st.error("Error: " + str(e))
