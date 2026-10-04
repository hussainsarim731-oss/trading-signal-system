import streamlit as st

st.set_page_config(page_title="Trading Signal System")

st.title("📊 Trading Signal System")

pair = st.selectbox("Pair", ["EUR/USD","GBP/USD","USD/JPY","AUD/USD","USD/CAD"])
timeframe = st.selectbox("Timeframe", ["1 min","5 min","15 min","30 min"])

st.write("Selected Pair:", pair)
st.write("Selected Timeframe:", timeframe)

st.info("System Ready")
