import streamlit as st
import websocket
import json
import threading
import time
from collections import deque

import pandas as pd
import numpy as np


# =========================================================
# SETTINGS
# =========================================================

st.set_page_config(
    page_title="Smart Live Trading Signal",
    page_icon="📊",
    layout="centered"
)

API_KEY = st.secrets.get(
    "TWELVE_DATA_API_KEY",
    ""
)

PAIRS = [
    "EUR/USD",
    "GBP/USD",
    "USD/JPY",
    "USD/CHF",
    "AUD/USD",
    "USD/CAD",
    "NZD/USD",
    "EUR/GBP",
    "EUR/JPY",
    "GBP/JPY",
    "GBP/CHF",
    "AUD/JPY",
    "EUR/CHF",
    "CAD/JPY"
]

TIMEFRAMES = {
    "5 Seconds": 5,
    "10 Seconds": 10,
    "15 Seconds": 15,
    "30 Seconds": 30,
    "1 Minute": 60
}

MAX_TICKS = 12000
MAX_CANDLES = 1500


# =========================================================
# GLOBAL LIVE DATA STORE
# =========================================================

store = {
    "ticks": {},
    "candles": {},
    "price": {},
    "connections": {},
    "lock": threading.Lock()
}


def initialize_pair(symbol):

    with store["lock"]:

        if symbol not in store["ticks"]:

            store["ticks"][symbol] = deque(
                maxlen=MAX_TICKS
            )

        if symbol not in store["candles"]:

            store["candles"][symbol] = deque(
                maxlen=MAX_CANDLES
            )

        if symbol not in store["price"]:

            store["price"][symbol] = None


# =========================================================
# INDICATORS
# =========================================================

def ema(series, period):

    return series.ewm(
        span=period,
        adjust=False
    ).mean()


def sma(series, period):

    return series.rolling(
        period
    ).mean()


def rsi(series, period=9):

    delta = series.diff()

    gain = delta.clip(
        lower=0
    )

    loss = -delta.clip(
        upper=0
    )

    avg_gain = gain.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    rs = (
        avg_gain
        / avg_loss.replace(
            0,
            np.nan
        )
    )

    return 100 - (
        100 / (1 + rs)
    )


def atr(df, period=14):

    high = df["high"]
    low = df["low"]
    close = df["close"]

    previous_close = close.shift(1)

    tr1 = high - low

    tr2 = (
        high - previous_close
    ).abs()

    tr3 = (
        low - previous_close
    ).abs()

    true_range = pd.concat(
        [
            tr1,
            tr2,
            tr3
        ],
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
            (
                (up_move > down_move)
                & (up_move > 0)
            ),
            up_move,
            0
        ),
        index=df.index
    )

    minus_dm = pd.Series(
        np.where(
            (
                (down_move > up_move)
                & (down_move > 0)
            ),
            down_move,
            0
        ),
        index=df.index
    )

    tr = pd.concat(
        [
            high - low,
            (
                high
                - close.shift()
            ).abs(),
            (
                low
                - close.shift()
            ).abs()
        ],
        axis=1
    ).max(axis=1)

    atr_value = tr.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    plus_di = (
        100
        * plus_dm.ewm(
            alpha=1 / period,
            adjust=False
        ).mean()
        / atr_value.replace(
            0,
            np.nan
        )
    )

    minus_di = (
        100
        * minus_dm.ewm(
            alpha=1 / period,
            adjust=False
        ).mean()
        / atr_value.replace(
            0,
            np.nan
        )
    )

    denominator = (
        plus_di
        + minus_di
    ).replace(
        0,
        np.nan
    )

    dx = (
        100
        * (
            plus_di
            - minus_di
        ).abs()
        / denominator
    )

    return dx.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()


def macd(series):

    fast = ema(
        series,
        8
    )

    slow = ema(
        series,
        21
    )

    line = fast - slow

    signal = ema(
        line,
        5
    )

    histogram = (
        line - signal
    )

    return (
        line,
        signal,
        histogram
    )


# =========================================================
# LIVE CANDLE BUILDER
# =========================================================

def build_candles(
    symbol,
    seconds
):

    initialize_pair(symbol)

    with store["lock"]:

        ticks = list(
            store["ticks"][symbol]
        )

    if len(ticks) < 2:
        return

    rows = []

    for timestamp, price in ticks:

        bucket = (
            int(timestamp / seconds)
            * seconds
        )

        rows.append(
            {
                "bucket": bucket,
                "price": float(price)
            }
        )

    if not rows:
        return

    df = pd.DataFrame(rows)

    candles = []

    for bucket, group in df.groupby(
        "bucket",
        sort=True
    ):

        prices = (
            group["price"]
            .values
        )

        candles.append(
            {
                "time": bucket,
                "open": float(
                    prices[0]
                ),
                "high": float(
                    prices.max()
                ),
                "low": float(
                    prices.min()
                ),
                "close": float(
                    prices[-1]
                )
            }
        )

    candles = candles[
        -MAX_CANDLES:
    ]

    with store["lock"]:

        store["candles"][symbol] = deque(
            candles,
            maxlen=MAX_CANDLES
        )


# =========================================================
# TWELVE DATA WEBSOCKET
# =========================================================

def websocket_worker(
    symbol,
    seconds
):

    initialize_pair(symbol)

    if not API_KEY:
        return

    url = (
        "wss://ws.twelvedata.com/"
        "v1/quotes/price"
    )

    while True:

        try:

            ws = websocket.create_connection(
                url,
                timeout=15
            )

            ws.send(
                json.dumps(
                    {
                        "action": "subscribe",
                        "params": {
                            "symbols": symbol
                        }
                    }
                )
            )

            while True:

                message = ws.recv()

                if not message:
                    continue

                try:

                    data = json.loads(
                        message
                    )

                except Exception:
                    continue

                price = None

                if isinstance(
                    data,
                    dict
                ):

                    if "price" in data:

                        price = data[
                            "price"
                        ]

                    elif "close" in data:

                        price = data[
                            "close"
                        ]

                if price is None:
                    continue

                try:

                    price = float(
                        price
                    )

                except Exception:
                    continue

                now = time.time()

                with store["lock"]:

                    store["price"][
                        symbol
                    ] = price

                    store["ticks"][
                        symbol
                    ].append(
                        (
                            now,
                            price
                        )
                    )

                build_candles(
                    symbol,
                    seconds
                )

        except Exception:

            time.sleep(2)


def start_connection(
    symbol,
    seconds
):

    initialize_pair(symbol)

    key = (
        f"{symbol}_{seconds}"
    )

    with store["lock"]:

        if store[
            "connections"
        ].get(
            key,
            False
        ):

            return

        store[
            "connections"
        ][key] = True

    thread = threading.Thread(
        target=websocket_worker,
        args=(
            symbol,
            seconds
        ),
        daemon=True
    )

    thread.start()


# =========================================================
# MARKET ANALYSIS ENGINE
# =========================================================

def analyze_market(
    symbol,
    seconds
):

    initialize_pair(symbol)

    build_candles(
        symbol,
        seconds
    )

    with store["lock"]:

        candles = list(
            store["candles"][symbol]
        )

    if len(candles) < 80:

        return {
            "signal": "UP",
            "confidence": 50,
            "bullish": 0,
            "bearish": 0,
            "reason":
                "Live history is still collecting. "
                "Direction is provisional."
        }

    df = pd.DataFrame(
        candles
    )

    close = df[
        "close"
    ]

    # =====================================================
    # INDICATORS
    # =====================================================

    df["ema9"] = ema(
        close,
        9
    )

    df["ema21"] = ema(
        close,
        21
    )

    df["ema50"] = ema(
        close,
        50
    )

    df["sma20"] = sma(
        close,
        20
    )

    df["rsi"] = rsi(
        close,
        9
    )

    macd_line, macd_signal, macd_hist = macd(
        close
    )

    df["macd"] = macd_line
    df["macd_signal"] = macd_signal
    df["macd_hist"] = macd_hist

    df["atr"] = atr(
        df,
        14
    )

    df["adx"] = adx(
        df,
        14
    )

    # =====================================================
    # REMOVE INVALID ROWS
    # =====================================================

    df = df.replace(
        [
            np.inf,
            -np.inf
        ],
        np.nan
    )

    df = df.dropna(
        subset=[
            "ema9",
            "ema21",
            "ema50",
            "sma20",
            "rsi",
            "macd_hist",
            "atr",
            "adx"
        ]
    )

    if len(df) < 60:

        return {
            "signal": "UP",
            "confidence": 50,
            "bullish": 0,
            "bearish": 0,
            "reason":
                "Indicator history is still building."
        }

    latest = df.iloc[-1]
    previous = df.iloc[-2]

    bullish = 0
    bearish = 0

    reasons_up = []
    reasons_down = []

    # =====================================================
    # 1 EMA TREND
    # =====================================================

    if (
        latest["ema9"]
        > latest["ema21"]
        > latest["ema50"]
    ):

        bullish += 3

        reasons_up.append(
            "EMA trend UP"
        )

    elif (
        latest["ema9"]
        < latest["ema21"]
        < latest["ema50"]
    ):

        bearish += 3

        reasons_down.append(
            "EMA trend DOWN"
        )

    # =====================================================
    # 2 PRICE VS SMA
    # =====================================================

    if (
        latest["close"]
        > latest["sma20"]
    ):

        bullish += 1

        reasons_up.append(
            "Price above SMA20"
        )

    elif (
        latest["close"]
        < latest["sma20"]
    ):

        bearish += 1

        reasons_down.append(
            "Price below SMA20"
        )

    # =====================================================
    # 3 MOMENTUM
    # =====================================================

    if (
        latest["close"]
        > previous["close"]
    ):

        bullish += 1

        reasons_up.append(
            "Momentum UP"
        )

    elif (
        latest["close"]
        < previous["close"]
    ):

        bearish += 1

        reasons_down.append(
            "Momentum DOWN"
        )

    # =====================================================
    # 4 RSI
    # =====================================================

    rsi_value = float(
        latest["rsi"]
    )

    if (
        52
        <= rsi_value
        <= 68
    ):

        bullish += 2

        reasons_up.append(
            "RSI bullish zone"
        )

    elif (
        32
        <= rsi_value
        <= 48
    ):

        bearish += 2

        reasons_down.append(
            "RSI bearish zone"
        )

    elif rsi_value > 70:

        # Very high RSI can mean
        # exhaustion, so give only
        # a small bearish weight.

        bearish += 1

        reasons_down.append(
            "RSI overbought"
        )

    elif rsi_value < 30:

        bullish += 1

        reasons_up.append(
            "RSI oversold"
        )

    # =====================================================
    # 5 MACD
    # =====================================================

    if (
        latest["macd_hist"] > 0
        and latest["macd_hist"]
        > previous["macd_hist"]
    ):

        bullish += 3

        reasons_up.append(
            "MACD bullish"
        )

    elif (
        latest["macd_hist"] < 0
        and latest["macd_hist"]
        < previous["macd_hist"]
    ):

        bearish += 3

        reasons_down.append(
            "MACD bearish"
        )

    # =====================================================
    # 6 ADX + DIRECTION
    # =====================================================

    adx_value = float(
        latest["adx"]
    )

    if adx_value >= 20:

        if (
            latest["ema9"]
            > latest["ema21"]
        ):

            bullish += 2

            reasons_up.append(
                "ADX confirms trend"
            )

        elif (
            latest["ema9"]
            < latest["ema21"]
        ):

            bearish += 2

            reasons_down.append(
                "ADX confirms trend"
            )

    # =====================================================
    # 7 BREAKOUT / BREAKDOWN
    # =====================================================

    recent = df.iloc[
        -21:-1
    ]

    resistance = recent[
        "high"
    ].max()

    support = recent[
        "low"
    ].min()

    if (
        latest["close"]
        > resistance
    ):

        bullish += 3

        reasons_up.append(
            "Resistance breakout"
        )

    elif (
        latest["close"]
        < support
    ):

        bearish += 3

        reasons_down.append(
            "Support breakdown"
        )

    # =====================================================
    # 8 CANDLE PRICE ACTION
    # =====================================================

    body = abs(
        latest["close"]
        - latest["open"]
    )

    candle_range = (
        latest["high"]
        - latest["low"]
    )

    if candle_range > 0:

        body_ratio = (
            body
            / candle_range
        )

        if body_ratio >= 0.60:

            if (
                latest["close"]
                > latest["open"]
            ):

                bullish += 2

                reasons_up.append(
                    "Strong bullish candle"
                )

            elif (
                latest["close"]
                < latest["open"]
            ):

                bearish += 2

                reasons_down.append(
                    "Strong bearish candle"
                )

    # =====================================================
    # 9 SWING STRUCTURE
    # =====================================================

    swing_window = df.iloc[
        -12:-2
    ]

    swing_high = swing_window[
        "high"
    ].max()

    swing_low = swing_window[
        "low"
    ].min()

    if (
        latest["close"]
        > swing_high
    ):

        bullish += 2

        reasons_up.append(
            "Swing structure UP"
        )

    elif (
        latest["close"]
        < swing_low
    ):

        bearish += 2

        reasons_down.append(
            "Swing structure DOWN"
        )

    # =====================================================
    # 10 SHORT-TERM TREND
    # =====================================================

    last_5 = df[
        "close"
    ].iloc[-5:]

    if (
        last_5.iloc[-1]
        > last_5.iloc[0]
    ):

        bullish += 1

        reasons_up.append(
            "Short-term trend UP"
        )

    elif (
        last_5.iloc[-1]
        < last_5.iloc[0]
    ):

        bearish += 1

        reasons_down.append(
            "Short-term trend DOWN"
        )

    # =====================================================
    # 11 VOLATILITY
    # =====================================================

    atr_value = float(
        latest["atr"]
    )

    if atr_value > 0:

        if (
            candle_range
            <= atr_value * 3
        ):

            # Normal volatility:
            # no penalty.

            if (
                bullish
                > bearish
            ):

                bullish += 1

            elif (
                bearish
                > bullish
            ):

                bearish += 1

    # =====================================================
    # FINAL DIRECTION
    # =====================================================

    total = (
        bullish
        + bearish
    )

    if total <= 0:

        signal = "UP"
        confidence = 50

        reason = (
            "No clear score difference; "
            "UP selected as forced direction."
        )

    else:

        if bullish >= bearish:

            signal = "UP"

            confidence = int(
                bullish
                / total
                * 100
            )

            reason = ", ".join(
                reasons_up
            )

            if not reason:

                reason = (
                    "Bullish side has "
                    "higher live-market score."
                )

        else:

            signal = "DOWN"

            confidence = int(
                bearish
                / total
                * 100
            )

            reason = ", ".join(
                reasons_down
            )

            if not reason:

                reason = (
                    "Bearish side has "
                    "higher live-market score."
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

st.title(
    "📊 Smart Live Trading Signal"
)

st.caption(
    "Live market data • "
    "Trend • Momentum • RSI • MACD • "
    "ADX • Breakout • Price Action • "
    "Swing Structure"
)


# =========================================================
# PAIR
# =========================================================

pair = st.selectbox(
    "Pair",
    PAIRS
)


# =========================================================
# TIMEFRAME
# =========================================================

timeframe_name = st.selectbox(
    "Timeframe",
    list(
        TIMEFRAMES.ke
