###############################################################
# app.py — 個股強勢策略回測（0050 SMA + 個股 SMA + 相對報酬）
###############################################################

import pandas as pd
import numpy as np
import yfinance as yf
import datetime as dt
import streamlit as st
import plotly.graph_objects as go

st.set_page_config(page_title="強勢股回測系統", page_icon="📈", layout="wide")

st.markdown("<h1>📊 強勢股三因子回測（200SMA + 相對六個月報酬）</h1>", unsafe_allow_html=True)

###############################################################
# 輔助函式
###############################################################

def fetch_price(symbol, start, end):
    df = yf.download(symbol, start=start, end=end, auto_adjust=True)
    if df.empty:
        return pd.DataFrame()
    df = df.rename(columns={"Close": "Price"})
    return df[["Price"]]

def CAGR(eq, years):
    if years <= 0:
        return np.nan
    return (eq[-1] / eq[0]) ** (1 / years) - 1

def max_drawdown(series):
    cummax = np.maximum.accumulate(series)
    dd = series / cummax - 1
    return dd.min()

###############################################################
# UI 設定
###############################################################

def normalize_symbol(symbol: str) -> str:
    symbol = symbol.strip()
    if symbol and not symbol.upper().endswith(".TW"):
        symbol = f"{symbol}.TW"
    return symbol


col1, col2 = st.columns(2)
with col1:
    market_symbol_input = st.text_input("大盤代號（預設 0050，系統自動補 .TW）", "0050")
    market_symbol = normalize_symbol(market_symbol_input)

with col2:
    stock_symbol_input = st.text_input("個股代號（例如：2330，系統自動補 .TW）", "2330")
    stock_symbol = normalize_symbol(stock_symbol_input)

start = st.date_input("開始日期", dt.date(2010,1,1))
end   = st.date_input("結束日期", dt.date.today())

capital = st.number_input("投入本金（元）", 10000, 10000000, 100000)

if st.button("開始回測 🚀"):

    ###############################################################
    # 下載資料
    ###############################################################
    st.write("⏳ 下載資料中...")

    data_fetch_start = dt.date(1990, 1, 1)

    mkt = fetch_price(market_symbol, data_fetch_start, end)
    stk = fetch_price(stock_symbol, data_fetch_start, end)

    if mkt.empty or stk.empty:
        st.error("⚠️ 資料下載失敗，請確認股票代號")
        st.stop()

    df = pd.DataFrame(index = mkt.index)
    df["Mkt"] = mkt["Price"]
    df = df.join(stk["Price"].rename("Stock"), how="inner")

    ###############################################################
    # 計算指標：200SMA + 6M 報酬
    ###############################################################

    df["Mkt_SMA200"] = df["Mkt"].rolling(200).mean()
    df["Stk_SMA200"] = df["Stock"].rolling(200).mean()

    df["Mkt_6m"] = df["Mkt"].pct_change(126)
    df["Stk_6m"] = df["Stock"].pct_change(126)

    df = df.dropna()

    if df.empty:
        st.error("⚠️ 無足夠資料進行回測，請確認股票代號")
        st.stop()

    earliest_backtest_date = df.index.min()

    st.info(f"最早可回測日期：{earliest_backtest_date.date()}")

    df = df[df.index >= pd.to_datetime(start)]

    if df.empty:
        st.error("⚠️ 無足夠資料進行回測，請調整開始日期或股票代號")
        st.stop()

    ###############################################################
    # 三條件訊號
    ###############################################################

    cond_buy = (
        (df["Mkt"] > df["Mkt_SMA200"]) &
        (df["Stock"] > df["Stk_SMA200"]) &
        (df["Stk_6m"] > df["Mkt_6m"])
    )

    df["Position"] = 0
    df.loc[cond_buy, "Position"] = 1

    # 只要任何一條不滿足 → 變成 0（賣出）
    df["Position"] = df["Position"].astype(int)

    ###############################################################
    # 找出買賣點
    ###############################################################

    df["Signal"] = df["Position"].diff().fillna(0)

    buys = df[df["Signal"] == 1]
    sells = df[df["Signal"] == -1]

    ###############################################################
    # 資金曲線
    ###############################################################

    df["Return"] = df["Stock"].pct_change().fillna(0)
    df["Strategy_Ret"] = df["Return"] * df["Position"]

    df["Eq"] = (1 + df["Strategy_Ret"]).cumprod()
    df["Eq_BH"] = (1 + df["Return"]).cumprod()

    years = (df.index[-1] - df.index[0]).days / 365

    cagr = CAGR(df["Eq"].values, years)
    mdd = max_drawdown(df["Eq"].values)

    ###############################################################
    # 結果呈現
    ###############################################################

    st.subheader("📌 買賣訊號圖")

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df.index, y=df["Stock"],
        mode="lines", name=f"{stock_symbol} 收盤價"
    ))

    fig.add_trace(go.Scatter(
        x=df.index, y=df["Stk_SMA200"],
        mode="lines", name="個股 200SMA"
    ))

    if not buys.empty:
        fig.add_trace(go.Scatter(
            x=buys.index, y=buys["Stock"],
            mode="markers", marker=dict(color="green", size=10),
            name="買點"
        ))

    if not sells.empty:
        fig.add_trace(go.Scatter(
            x=sells.index, y=sells["Stock"],
            mode="markers", marker=dict(color="red", size=10),
            name="賣點"
        ))

    fig.update_layout(height=450, template="plotly_white")
    st.plotly_chart(fig, use_container_width=True)

    ###############################################################
    # 資金曲線
    ###############################################################

    st.subheader("📈 資金曲線")

    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=df.index, y=df["Eq"], name="策略", mode="lines"))
    fig2.add_trace(go.Scatter(x=df.index, y=df["Eq_BH"], name="Buy & Hold", mode="lines"))
    fig2.update_layout(height=400, template="plotly_white")
    st.plotly_chart(fig2, use_container_width=True)

    ###############################################################
    # KPI
    ###############################################################

    st.subheader("🏆 回測績效（KPI）")

    st.write(f"**期末資產（策略）：** {capital * df['Eq'].iloc[-1]:,.0f} 元")
    st.write(f"**期末資產（買進持有）：** {capital * df['Eq_BH'].iloc[-1]:,.0f} 元")
    st.write(f"**CAGR（策略）：** {cagr:.2%}")
    st.write(f"**最大回撤 MDD：** {mdd:.2%}")
    st.write(f"**交易次數：** {int(df['Signal'].abs().sum())}")

