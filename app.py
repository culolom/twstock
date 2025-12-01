###############################################################
# app.py — LRS 回測（Plotly  · 價格 + MA + 資金曲線% + 時間縮放）
###############################################################

import os
import datetime as dt
import numpy as np
import pandas as pd
import yfinance as yf
import streamlit as st
import matplotlib
import matplotlib.font_manager as fm
import plotly.graph_objects as go


###############################################################
# 字型設定
###############################################################

font_path = "./NotoSansTC-Bold.ttf"
if os.path.exists(font_path):
    fm.fontManager.addfont(font_path)
    matplotlib.rcParams["font.family"] = "Noto Sans TC"
else:
    matplotlib.rcParams["font.sans-serif"] = [
        "Microsoft JhengHei",
        "PingFang TC",
        "Heiti TC",
    ]

matplotlib.rcParams["axes.unicode_minus"] = False


###############################################################
# Streamlit 頁面設定
###############################################################

st.set_page_config(page_title="LRS 回測系統", page_icon="📈", layout="wide")
st.markdown(
    "<h1 style='margin-bottom:0.5em;'>📊 LRS策略回測系統</h1>",
    unsafe_allow_html=True,
)


###############################################################
# 工具：台股 or 美股判斷
###############################################################

def normalize_for_yfinance(raw_symbol: str) -> str:
    s = raw_symbol.strip().upper()
    return s + ".TW" if s.isdigit() else s


###############################################################
# yfinance 下載資料
###############################################################

@st.cache_data(show_spinner=False)
def fetch_history(symbol: str, start: dt.date, end: dt.date):
    df = yf.download(symbol, start=start, end=end, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.empty:
        return df
    df = df.sort_index()
    df = df[~df.index.duplicated()]
    if "Adj Close" not in df.columns and "Close" in df.columns:
        df["Adj Close"] = df["Close"]
    return df


###############################################################
# 自動拆股再次平滑（保險）
###############################################################

def adjust_for_splits(df: pd.DataFrame, price_col="Adj Close", threshold=0.3):
    df = df.copy()
    df["Price_raw"] = df[price_col]
    df["Price_adj"] = df["Price_raw"].copy()

    pct = df["Price_raw"].pct_change()
    candidates = pct[abs(pct) >= threshold].dropna()

    for date, r in candidates.items():
        ratio = 1 + r
        if ratio <= 0 or ratio >= 1:
            continue
        df.loc[df.index < date, "Price_adj"] *= ratio

    return df


###############################################################
# 統一資料載入
###############################################################

@st.cache_data(show_spinner=False)
def load_price_data(symbol: str, start: dt.date, end: dt.date):
    df = fetch_history(symbol, start, end)
    if df.empty:
        return df

    price_col = "Adj Close" if "Adj Close" in df.columns else "Close"
    df = adjust_for_splits(df, price_col)

    return df


###############################################################
# 取得最完整起訖區間
###############################################################

@st.cache_data(show_spinner=False)
def get_full_range(symbol):
    hist = yf.Ticker(symbol).history(period="max", auto_adjust=True)
    if hist.empty:
        return dt.date(1990, 1, 1), dt.date.today()
    hist = hist.sort_index()
    hist = hist[~hist.index.duplicated()]
    return hist.index.min().date(), hist.index.max().date()


###############################################################
# UI：輸入區
###############################################################

col1, col2, col3 = st.columns(3)
with col1:
    raw_symbol = st.text_input("輸入代號（例：0050 / QQQ）", "0050")

yf_symbol = normalize_for_yfinance(raw_symbol)

if "last_symbol" not in st.session_state or st.session_state.last_symbol != yf_symbol:
    st.session_state.last_symbol = yf_symbol
    s_min, s_max = get_full_range(yf_symbol)
    st.session_state.s_min = s_min
    st.session_state.s_max = s_max

s_min = st.session_state.s_min
s_max = st.session_state.s_max

st.info(f"📌 {yf_symbol} 可用資料：{s_min} ~ {s_max}")

with col2:
    start = st.date_input(
        "開始日期",
        value=max(s_min, dt.date(2013, 1, 1)),
        min_value=s_min,
        max_value=s_max,
    )
with col3:
    end = st.date_input(
        "結束日期",
        value=s_max,
        min_value=s_min,
        max_value=s_max,
    )

col4, col5, col6 = st.columns(3)
with col4:
    ma_type = st.selectbox("均線種類", ["SMA", "EMA"])
with col5:
    window = st.slider("均線天數", 10, 200, 200)
with col6:
    initial_capital = st.number_input(
        "投入本金（元）", 1000, 1_000_000, 10000, step=1000
    )


###############################################################
# 主程式
###############################################################

if st.button("開始回測 🚀"):

    start_early = pd.to_datetime(start) - pd.Timedelta(days=365)

    with st.spinner("資料下載 ＋ 拆股調整..."):
        df_all = load_price_data(yf_symbol, start_early.date(), end)

    if df_all.empty:
        st.error("⚠️ 無法下載資料，請確認代號與時間區間。")
        st.stop()

    df = df_all.copy()
    df = df[
        (df.index >= pd.to_datetime(start_early))
        & (df.index <= pd.to_datetime(end))
    ].sort_index()

    df["Price"] = df["Price_adj"]

    if ma_type == "SMA":
        df["MA"] = df["Price"].rolling(window).mean()
    else:
        df["MA"] = df["Price"].ewm(span=window, adjust=False).mean()

    df = df.dropna(subset=["MA"])

    if df.empty:
        st.error("⚠️ 均線可用資料不足，請調整起訖日期或均線天數。")
        st.stop()

    df["Signal"] = 0
    df.iloc[0, df.columns.get_loc("Signal")] = 1

    for i in range(1, len(df)):
        p, m = df["Price"].iloc[i], df["MA"].iloc[i]
        prev_p, prev_m = df["Price"].iloc[i - 1], df["MA"].iloc[i - 1]
        if p > m and prev_p <= prev_m:
            df.iloc[i, df.columns.get_loc("Signal")] = 1
        elif p < m and prev_p >= prev_m:
            df.iloc[i, df.columns.get_loc("Signal")] = -1

    pos = []
    current = 1
    for sig in df["Signal"]:
        if sig == 1:
            current = 1
        elif sig == -1:
            current = 0
        pos.append(current)
    df["Position"] = pos

    df["Return"] = df["Price"].pct_change().fillna(0)
    df["Strategy_Return"] = df["Return"] * df["Position"]

    df["Equity_LRS"] = 1.0
    for i in range(1, len(df)):
        prev = df["Equity_LRS"].iloc[i - 1]
        r = df["Return"].iloc[i]
        df.iloc[i, df.columns.get_loc("Equity_LRS")] = prev * (1 + r) if df[
            "Position"
        ].iloc[i - 1] == 1 else prev

    df["Equity_BuyHold"] = (1 + df["Return"]).cumprod()

    df = df.loc[pd.to_datetime(start) : pd.to_datetime(end)].copy()
    df["LRS_Capital"] = df["Equity_LRS"] * initial_capital
    df["BH_Capital"] = df["Equity_BuyHold"] * initial_capital
    df["Equity_LRS_Pct"] = df["Equity_LRS"] - 1
    df["Equity_BH_Pct"] = df["Equity_BuyHold"] - 1

    buy_points = [
        (d, df["Price"].loc[d]) for d in df.index[1:] if df["Signal"].loc[d] == 1
    ]
    sell_points = [
        (d, df["Price"].loc[d]) for d in df.index[1:] if df["Signal"].loc[d] == -1
    ]

    last_date = df.index.max()
    one_year_ago = last_date - pd.Timedelta(days=365)
    three_years_ago = last_date - pd.Timedelta(days=365 * 3)
    five_years_ago = last_date - pd.Timedelta(days=365 * 5)
    year_start = pd.Timestamp(last_date.year, 1, 1)

    range_buttons = [
        dict(label="1Y", method="relayout", args=[{"xaxis.range": [one_year_ago, last_date]}]),
        dict(label="3Y", method="relayout", args=[{"xaxis.range": [three_years_ago, last_date]}]),
        dict(label="5Y", method="relayout", args=[{"xaxis.range": [five_years_ago, last_date]}]),
        dict(label="YTD", method="relayout", args=[{"xaxis.range": [year_start, last_date]}]),
        dict(label="全部", method="relayout", args=[{"xaxis.autorange": True}]),
    ]

    ###############################################################
    # 📈 圖表 1
    ###############################################################

    st.markdown("<h3>📈 價格與均線（含買賣點）</h3>", unsafe_allow_html=True)

    fig_price = go.Figure()

    fig_price.add_trace(go.Scatter(x=df.index, y=df["Price"], name="收盤價",
                                   mode="lines", line=dict(color="#1f77b4", width=2)))

    fig_price.add_trace(go.Scatter(x=df.index, y=df["MA"], name=f"{ma_type}{window}",
                                   mode="lines", line=dict(color="#ff7f0e", width=2)))

    if buy_points:
        bx, by = zip(*buy_points)
        fig_price.add_trace(go.Scatter(
            x=bx, y=by, mode="markers", name="買進",
            marker=dict(color="#2ca02c", symbol="triangle-up", size=10)
        ))

    if sell_points:
        sx, sy = zip(*sell_points)
        fig_price.add_trace(go.Scatter(
            x=sx, y=sy, mode="markers", name="賣出",
            marker=dict(color="#d62728", symbol="x", size=10)
        ))

    fig_price.update_layout(
        template="plotly_white",
        height=500,
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
        ),
        margin=dict(l=40, r=20, t=80, b=40),
        xaxis=dict(title="日期"),
        yaxis=dict(title="價格"),
        updatemenus=[
            dict(
                type="buttons",
                direction="left",
                buttons=range_buttons,
                x=0.5, y=1.18,
                xanchor="center", yanchor="top",
                bgcolor="white",
                bordercolor="#ccc", borderwidth=1,
                pad=dict(t=6, r=6),
            )
        ],
    )

    st.plotly_chart(fig_price, use_container_width=True)

    ###############################################################
    # 📊 圖表 2
    ###############################################################

    st.markdown("<h3>📊 資金曲線（報酬百分比）</h3>", unsafe_allow_html=True)

    fig_equity = go.Figure()

    fig_equity.add_trace(go.Scatter(
        x=df.index, y=df["Equity_LRS_Pct"], name="LRS 策略",
        mode="lines", line=dict(color="#2ca02c", width=2)
    ))

    fig_equity.add_trace(go.Scatter(
        x=df.index, y=df["Equity_BH_Pct"], name="Buy & Hold",
        mode="lines", line=dict(color="#d62728", width=2, dash="dot")
    ))

    fig_equity.update_layout(
        template="plotly_white",
        height=450,
        margin=dict(l=40, r=20, t=80, b=40),
        xaxis=dict(title="日期"),
        yaxis=dict(title="報酬率", tickformat=".0%"),
        legend=dict(orientation="h", y=1.02),
        updatemenus=[
            dict(
                type="buttons",
                direction="left",
                buttons=range_buttons,
                x=0.5, y=1.18,
                xanchor="center", yanchor="top",
                bgcolor="white",
                bordercolor="#ccc", borderwidth=1,
                pad=dict(t=6, r=6),
            )
        ],
    )

    st.plotly_chart(fig_equity, use_container_width=True)

    ###############################################################
    # 指標計算
    ###############################################################

    final_return_lrs = df["Equity_LRS"].iloc[-1] - 1
    final_return_bh = df["Equity_BuyHold"].iloc[-1] - 1

    years_len = (df.index[-1] - df.index[0]).days / 365
    cagr_lrs = (1 + final_return_lrs)**(1/years_len) - 1 if years_len > 0 else np.nan
    cagr_bh = (1 + final_return_bh)**(1/years_len) - 1 if years_len > 0 else np.nan

    mdd_lrs = 1 - (df["Equity_LRS"] / df["Equity_LRS"].cummax()).min()
    mdd_bh = 1 - (df["Equity_BuyHold"] / df["Equity_BuyHold"].cummax()).min()

    def calc_metrics(series):
        daily = series.dropna()
        if len(daily) <= 1:
            return np.nan, np.nan, np.nan
        avg = daily.mean()
        std = daily.std()
        downside = daily[daily < 0].std()
        vol = std * np.sqrt(252)
        sharpe = (avg / std) * np.sqrt(252) if std > 0 else np.nan
        sortino = (avg / downside) * np.sqrt(252) if downside > 0 else np.nan
        return vol, sharpe, sortino

    vol_lrs, sharpe_lrs, sortino_lrs = calc_metrics(df["Strategy_Return"])
    vol_bh, sharpe_bh, sortino_bh = calc_metrics(df["Return"])

    equity_lrs_final = df["LRS_Capital"].iloc[-1]
    equity_bh_final = df["BH_Capital"].iloc[-1]

    ###############################################################
    # 美化表格（白底）
    ###############################################################

    st.markdown(
        """
    <style>
    .custom-table { width:100%; border-collapse:collapse; margin-top:1.2em; }
    .custom-table th {
        background:#ffffff; padding:12px; font-weight:700;
        border-bottom:2px solid #ddd;
    }
    .custom-table td {
        text-align:center; padding:10px;
        border-bottom:1px solid #eee; font-size:15px;
    }
    .custom-table tr:nth-child(even) td { background-color:#fafafa; }
    .custom-table tr:hover td { background-color:#f1f7ff; }
    .section-title td {
        background:#e8f2ff; color:#0a47a1; font-weight:700;
        font-size:16px; text-align:left; padding:10px 15px;
    }
    </style>
    """,
        unsafe_allow_html=True,
    )

    html_table = f"""
    <table class='custom-table'>
    <thead><tr><th>指標名稱</th><th>LRS 策略</th><th>Buy & Hold</th></tr></thead>
    <tbody>
    <tr><td>最終資產</td><td>{equity_lrs_final:,.0f} 元</td><td>{equity_bh_final:,.0f} 元</td></tr>
    <tr><td>總報酬</td><td>{final_return_lrs:.2%}</td><td>{final_return_bh:.2%}</td></tr>
    <tr><td>年化報酬</td><td>{cagr_lrs:.2%}</td><td>{cagr_bh:.2%}</td></tr>
    <tr><td>最大回撤</td><td>{mdd_lrs:.2%}</td><td>{mdd_bh:.2%}</td></tr>
    <tr><td>年化波動率</td><td>{vol_lrs:.2%}</td><td>{vol_bh:.2%}</td></tr>
    <tr><td>夏普值</td><td>{sharpe_lrs:.2f}</td><td>{sharpe_bh:.2f}</td></tr>
    <tr><td>索提諾值</td><td>{sortino_lrs:.2f}</td><td>{sortino_bh:.2f}</td></tr>

    <tr class='section-title'><td colspan='3'>💹 交易統計</td></tr>

    <tr><td>買進次數</td><td>{len(buy_points)}</td><td>—</td></tr>
    <tr><td>賣出次數</td><td>{len(sell_points)}</td><td>—</td></tr>
    </tbody>
    </table>
    """

    st.markdown(html_table, unsafe_allow_html=True)
    st.success("✅ 回測完成！（Plotly 白底版）")
