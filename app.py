###############################################################
# app.py — 台股加權指數 + 個股 200SMA 回測
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
# 常數
###############################################################

TAIEX_SYMBOL = "^TWII"  # 台股加權指數
WINDOW = 200  # 固定 200 日 SMA

###############################################################
# Streamlit 頁面設定
###############################################################

st.set_page_config(
    page_title="台股 200SMA 回測系統",
    page_icon="📈",
    layout="wide",
)

st.markdown(
    "<h1 style='margin-bottom:0.5em;'>📊 台股加權指數 + 個股 200SMA 回測</h1>",
    unsafe_allow_html=True,
)

st.markdown(
    """
<b>進出場邏輯：</b><br>
✅ <b>買進</b>：台股加權指數 (>200SMA) 且 個股 (>200SMA)<br>
❌ <b>賣出</b>：台股加權指數 (<200SMA) 且 個股 (<200SMA)<br>
<small>（價格採 yfinance 調整後收盤價）</small>
""",
    unsafe_allow_html=True,
)

###############################################################
# 輔助函式
###############################################################


def calc_metrics(series: pd.Series):
    """計算年化波動率、Sharpe、Sortino"""
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


def fmt_money(v):
    try:
        return f"{v:,.0f} 元"
    except:  # noqa: E722
        return "—"


def fmt_pct(v, d=2):
    try:
        return f"{v:.{d}%}"
    except:  # noqa: E722
        return "—"


def fmt_num(v, d=2):
    try:
        return f"{v:.{d}f}"
    except:  # noqa: E722
        return "—"


def fmt_int(v):
    try:
        return f"{int(v):,}"
    except:  # noqa: E722
        return "—"


def nz(x, default=0.0):
    return float(np.nan_to_num(x, nan=default))


def format_currency(v):
    try:
        return f"{v:,.0f} 元"
    except:  # noqa: E722
        return "—"


def format_percent(v, d=2):
    try:
        return f"{v*100:.{d}f}%"
    except:  # noqa: E722
        return "—"


def format_number(v, d=2):
    try:
        return f"{v:.{d}f}"
    except:  # noqa: E722
        return "—"


@st.cache_data(show_spinner=False)
def fetch_history(symbol: str, start: dt.date, end: dt.date):
    df = yf.download(symbol, start=start, end=end, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.empty:
        return df
    df = df.sort_index()
    df = df[~df.index.duplicated()]

    if "Close" in df.columns:
        df["Price"] = df["Close"]
    elif "Adj Close" in df.columns:
        df["Price"] = df["Adj Close"]
    else:
        df["Price"] = df[df.columns[0]]

    return df[["Price"]]


@st.cache_data(show_spinner=False)
def load_price(symbol: str, start: dt.date, end: dt.date):
    df = fetch_history(symbol, start, end)
    return df[["Price"]] if not df.empty else df


@st.cache_data(show_spinner=False)
def get_symbol_range(symbol: str):
    hist = yf.Ticker(symbol).history(period="max", auto_adjust=True)
    if hist.empty:
        return None, None
    hist = hist.sort_index()
    return hist.index.min().date(), hist.index.max().date()


###############################################################
# UI 輸入
###############################################################

col1, col2 = st.columns([2, 1])
with col1:
    stock_code = st.text_input("輸入股票代號（不含 .TW）", value="2330", max_chars=6)
with col2:
    capital = st.number_input(
        "投入本金（元）",
        1000,
        5_000_000,
        100_000,
        step=10_000,
    )

stock_symbol = f"{stock_code.strip()}.TW" if stock_code.strip() else ""
taiex_min, taiex_max = get_symbol_range(TAIEX_SYMBOL)
stock_min, stock_max = get_symbol_range(stock_symbol) if stock_symbol else (None, None)

if taiex_min and stock_min:
    start_min = max(taiex_min, stock_min)
    end_max = min(taiex_max, stock_max)
    st.info(f"📌 可回測區間：{start_min} ~ {end_max}")
else:
    st.info("請先輸入有效的股票代號以取得可回測區間")

col3, col4 = st.columns(2)
with col3:
    start = st.date_input(
        "開始日期",
        value=dt.date.today() - dt.timedelta(days=5 * 365),
    )
with col4:
    end = st.date_input("結束日期", value=dt.date.today())

###############################################################
# 主程式開始
###############################################################

if st.button("開始回測 🚀"):

    if not stock_symbol:
        st.error("⚠️ 請輸入股票代號")
        st.stop()

    if start >= end:
        st.error("⚠️ 開始日期需早於結束日期")
        st.stop()

    start_early = start - dt.timedelta(days=365)

    with st.spinner("下載資料中…"):
        df_index_raw = load_price(TAIEX_SYMBOL, start_early, end)
        df_stock_raw = load_price(stock_symbol, start_early, end)

    if df_index_raw.empty or df_stock_raw.empty:
        st.error("⚠️ 資料抓取失敗，請確認代號是否正確")
        st.stop()

    df = pd.DataFrame(index=df_index_raw.index)
    df["Price_index"] = df_index_raw["Price"]
    df = df.join(df_stock_raw["Price"].rename("Price_stock"), how="inner")
    df = df.sort_index()
    df = df[(df.index >= pd.to_datetime(start_early)) & (df.index <= pd.to_datetime(end))]

    # 200 SMA
    df["MA_index"] = df["Price_index"].rolling(WINDOW).mean()
    df["MA_stock"] = df["Price_stock"].rolling(WINDOW).mean()
    df = df.dropna(subset=["MA_index", "MA_stock"])

    df = df.loc[pd.to_datetime(start): pd.to_datetime(end)].copy()
    if df.empty:
        st.error("⚠️ 有效回測區間不足")
        st.stop()

    # 報酬
    df["Return_stock"] = df["Price_stock"].pct_change().fillna(0)

    ###############################################################
    # 訊號：指數與個股皆站上/跌破 200SMA
    ###############################################################

    df["Signal"] = 0
    above_both_prev = False
    below_both_prev = False
    for i in range(len(df)):
        above_both = (df["Price_index"].iloc[i] > df["MA_index"].iloc[i]) and (
            df["Price_stock"].iloc[i] > df["MA_stock"].iloc[i]
        )
        below_both = (df["Price_index"].iloc[i] < df["MA_index"].iloc[i]) and (
            df["Price_stock"].iloc[i] < df["MA_stock"].iloc[i]
        )

        if above_both and not above_both_prev:
            df.iloc[i, df.columns.get_loc("Signal")] = 1
        elif below_both and not below_both_prev:
            df.iloc[i, df.columns.get_loc("Signal")] = -1

        above_both_prev = above_both
        below_both_prev = below_both

    ###############################################################
    # Position
    ###############################################################

    current_pos = 1 if (df["Price_index"].iloc[0] > df["MA_index"].iloc[0]) and (
        df["Price_stock"].iloc[0] > df["MA_stock"].iloc[0]
    ) else 0

    positions = [current_pos]
    for s in df["Signal"].iloc[1:]:
        if s == 1:
            current_pos = 1
        elif s == -1:
            current_pos = 0
        positions.append(current_pos)

    df["Position"] = positions

    ###############################################################
    # 資金曲線
    ###############################################################

    equity_strategy = [1.0]
    for i in range(1, len(df)):
        if df["Position"].iloc[i] == 1 and df["Position"].iloc[i - 1] == 1:
            r = df["Price_stock"].iloc[i] / df["Price_stock"].iloc[i - 1]
            equity_strategy.append(equity_strategy[-1] * r)
        else:
            equity_strategy.append(equity_strategy[-1])

    df["Equity_Strategy"] = equity_strategy
    df["Return_Strategy"] = df["Equity_Strategy"].pct_change().fillna(0)
    df["Equity_BH"] = (1 + df["Return_stock"]).cumprod()

    df["Pct_BH"] = df["Equity_BH"] - 1
    df["Pct_Strategy"] = df["Equity_Strategy"] - 1

    buys = df[df["Signal"] == 1]
    sells = df[df["Signal"] == -1]

    ###############################################################
    # 指標計算
    ###############################################################

    years_len = (df.index[-1] - df.index[0]).days / 365 if len(df) > 1 else 0

    def calc_core(eq, rets):
        final_eq = eq.iloc[-1]
        final_ret = final_eq - 1
        cagr = (1 + final_ret) ** (1 / years_len) - 1 if years_len > 0 else np.nan
        mdd = 1 - (eq / eq.cummax()).min()
        vol, sharpe, sortino = calc_metrics(rets)
        calmar = cagr / mdd if mdd > 0 else np.nan
        return final_eq, final_ret, cagr, mdd, vol, sharpe, sortino, calmar

    (
        eq_strategy_final,
        final_ret_strategy,
        cagr_strategy,
        mdd_strategy,
        vol_strategy,
        sharpe_strategy,
        sortino_strategy,
        calmar_strategy,
    ) = calc_core(df["Equity_Strategy"], df["Return_Strategy"])
    eq_bh_final, final_ret_bh, cagr_bh, mdd_bh, vol_bh, sharpe_bh, sortino_bh, calmar_bh = calc_core(
        df["Equity_BH"], df["Return_stock"]
    )

    capital_strategy_final = eq_strategy_final * capital
    capital_bh_final = eq_bh_final * capital
    trade_count = int((df["Signal"] != 0).sum())

    ###############################################################
    # 價格圖（含買賣點）
    ###############################################################

    st.markdown("<h3>📌 股價與台股加權指數 200SMA</h3>", unsafe_allow_html=True)

    fig_price = go.Figure()

    fig_price.add_trace(
        go.Scatter(
            x=df.index,
            y=df["Price_stock"],
            name=f"{stock_code} 收盤價",
            mode="lines",
            line=dict(color="#1f77b4", width=2),
        )
    )

    fig_price.add_trace(
        go.Scatter(
            x=df.index,
            y=df["MA_stock"],
            name="個股 200 日 SMA",
            mode="lines",
            line=dict(color="#7f7f7f", width=2),
        )
    )

    fig_price.add_trace(
        go.Scatter(
            x=df.index,
            y=df["Price_index"],
            name="加權指數",
            mode="lines",
            line=dict(color="#ff7f0e", width=1.8, dash="dash"),
            yaxis="y2",
        )
    )

    fig_price.add_trace(
        go.Scatter(
            x=df.index,
            y=df["MA_index"],
            name="加權指數 200 日 SMA",
            mode="lines",
            line=dict(color="#d62728", width=1.5, dash="dot"),
            yaxis="y2",
        )
    )

    if not buys.empty:
        fig_price.add_trace(
            go.Scatter(
                x=buys.index,
                y=buys["Price_stock"],
                mode="markers",
                name="買進 Buy",
                marker=dict(symbol="circle-open", size=12, line=dict(width=2, color="#2ca02c")),
                hovertemplate=(
                    "📈 <b>買進訊號</b><br>"
                    "日期: %{x|%Y-%m-%d}<br>"
                    + stock_code + ": %{y:.2f}<br>"
                    "<extra></extra>"
                ),
            )
        )

    if not sells.empty:
        fig_price.add_trace(
            go.Scatter(
                x=sells.index,
                y=sells["Price_stock"],
                mode="markers",
                name="賣出 Sell",
                marker=dict(symbol="circle-open", size=12, line=dict(width=2, color="#d62728")),
                hovertemplate=(
                    "📉 <b>賣出訊號</b><br>"
                    "日期: %{x|%Y-%m-%d}<br>"
                    + stock_code + ": %{y:.2f}<br>"
                    "<extra></extra>"
                ),
            )
        )

    fig_price.update_layout(
        template="plotly_white",
        height=520,
        margin=dict(l=40, r=60, t=40, b=40),
        legend=dict(orientation="h"),
        yaxis=dict(title="股價"),
        yaxis2=dict(title="加權指數", overlaying="y", side="right", showgrid=False),
    )
    st.plotly_chart(fig_price, use_container_width=True)

    ###############################################################
    # Tabs：資金曲線 / 回撤 / 雷達圖 / 日報酬分佈
    ###############################################################

    st.markdown("<h3>📊 策略資金曲線與風險解析</h3>", unsafe_allow_html=True)
    tab_equity, tab_dd, tab_radar, tab_hist = st.tabs(["資金曲線", "回撤比較", "風險雷達", "日報酬分佈"])

    # ============================
    # 資金曲線
    # ============================
    with tab_equity:
        fig_equity = go.Figure()
        fig_equity.add_trace(go.Scatter(x=df.index, y=df["Pct_BH"], mode="lines", name="Buy & Hold"))
        fig_equity.add_trace(go.Scatter(x=df.index, y=df["Pct_Strategy"], mode="lines", name="200SMA 雙濾網"))

        fig_equity.update_layout(
            template="plotly_white",
            height=420,
            legend=dict(orientation="h"),
            yaxis=dict(tickformat=".0%"),
        )
        st.plotly_chart(fig_equity, use_container_width=True)

    # ============================
    # 回撤
    # ============================
    with tab_dd:
        dd_bh = (df["Equity_BH"] / df["Equity_BH"].cummax() - 1) * 100
        dd_strategy = (df["Equity_Strategy"] / df["Equity_Strategy"].cummax() - 1) * 100

        fig_dd = go.Figure()
        fig_dd.add_trace(
            go.Scatter(
                x=df.index,
                y=dd_bh,
                name="Buy & Hold",
            )
        )
        fig_dd.add_trace(
            go.Scatter(
                x=df.index,
                y=dd_strategy,
                name="200SMA 雙濾網",
                fill="tozeroy",
                fillcolor="rgba(231, 126, 34, 0.08)",
            )
        )
        fig_dd.update_layout(template="plotly_white", height=420)
        st.plotly_chart(fig_dd, use_container_width=True)

    # ============================
    # 風險雷達圖
    # ============================
    with tab_radar:
        radar_categories = ["CAGR", "Sharpe", "Sortino", "-MDD", "波動率(反轉)"]

        radar_strategy = [nz(cagr_strategy), nz(sharpe_strategy), nz(sortino_strategy), nz(-mdd_strategy), nz(-vol_strategy)]
        radar_bh = [nz(cagr_bh), nz(sharpe_bh), nz(sortino_bh), nz(-mdd_bh), nz(-vol_bh)]

        fig_radar = go.Figure()
        fig_radar.add_trace(go.Scatterpolar(r=radar_strategy, theta=radar_categories, fill="toself", name="200SMA 雙濾網"))
        fig_radar.add_trace(go.Scatterpolar(r=radar_bh, theta=radar_categories, fill="toself", name="Buy & Hold"))
        fig_radar.update_layout(template="plotly_white", height=480)

        st.plotly_chart(fig_radar, use_container_width=True)

    # ============================
    # 日報酬直方圖
    # ============================
    with tab_hist:
        fig_hist = go.Figure()
        fig_hist.add_trace(go.Histogram(x=df["Return_stock"] * 100, name="Buy & Hold", opacity=0.6))
        fig_hist.add_trace(go.Histogram(x=df["Return_Strategy"] * 100, name="200SMA 雙濾網", opacity=0.7))
        fig_hist.update_layout(barmode="overlay", template="plotly_white", height=480)

        st.plotly_chart(fig_hist, use_container_width=True)

    ###############################################################
    # KPI Summary Cards（策略 vs Buy & Hold）
    ###############################################################

    asset_gap = ((capital_strategy_final / capital_bh_final) - 1) * 100
    cagr_gap = (cagr_strategy - cagr_bh) * 100
    vol_gap = (vol_strategy - vol_bh) * 100
    mdd_gap = (mdd_strategy - mdd_bh) * 100

    row1 = st.columns(4)
    with row1[0]:
        st.metric(
            label="期末資產（策略）",
            value=format_currency(capital_strategy_final),
            delta=f"較 Buy & Hold {asset_gap:+.2f}%",
        )

    with row1[1]:
        st.metric(
            label="年化報酬（CAGR, 策略）",
            value=format_percent(cagr_strategy),
            delta=f"較 Buy & Hold {cagr_gap:+.2f}%",
        )

    with row1[2]:
        st.metric(
            label="年化波動（策略）",
            value=format_percent(vol_strategy),
            delta=f"較 Buy & Hold {vol_gap:+.2f}%",
            delta_color="inverse",
        )

    with row1[3]:
        st.metric(
            label="最大回撤（策略）",
            value=format_percent(mdd_strategy),
            delta=f"較 Buy & Hold {mdd_gap:+.2f}%",
            delta_color="inverse",
        )

    ###############################################################
    # 表格（策略完整比較）
    ###############################################################

    metrics_table = pd.DataFrame(
        [
            {
                "策略": "200SMA 雙濾網",
                "期末資產": capital_strategy_final,
                "總報酬率": final_ret_strategy,
                "CAGR（年化）": cagr_strategy,
                "Calmar Ratio": calmar_strategy,
                "最大回撤（MDD）": mdd_strategy,
                "年化波動": vol_strategy,
                "Sharpe": sharpe_strategy,
                "Sortino": sortino_strategy,
                "交易次數": trade_count,
            },
            {
                "策略": "Buy & Hold",
                "期末資產": capital_bh_final,
                "總報酬率": final_ret_bh,
                "CAGR（年化）": cagr_bh,
                "Calmar Ratio": calmar_bh,
                "最大回撤（MDD）": mdd_bh,
                "年化波動": vol_bh,
                "Sharpe": sharpe_bh,
                "Sortino": sortino_bh,
                "交易次數": np.nan,
            },
        ]
    )

    raw_table = metrics_table.copy()

    formatted = metrics_table.copy()
    formatted["期末資產"] = formatted["期末資產"].apply(fmt_money)
    formatted["總報酬率"] = formatted["總報酬率"].apply(fmt_pct)
    formatted["CAGR（年化）"] = formatted["CAGR（年化）"].apply(fmt_pct)
    formatted["Calmar Ratio"] = formatted["Calmar Ratio"].apply(fmt_num)
    formatted["最大回撤（MDD）"] = formatted["最大回撤（MDD）"].apply(fmt_pct)
    formatted["年化波動"] = formatted["年化波動"].apply(fmt_pct)
    formatted["Sharpe"] = formatted["Sharpe"].apply(fmt_num)
    formatted["Sortino"] = formatted["Sortino"].apply(fmt_num)
    formatted["交易次數"] = formatted["交易次數"].apply(fmt_int)

    styled = formatted.style.set_properties(subset=["策略"], **{"font-weight": "bold", "color": "#2c7be5"})

    highlight_rules = {
        "期末資產": "high",
        "總報酬率": "high",
        "CAGR（年化）": "high",
        "Calmar Ratio": "high",
        "最大回撤（MDD）": "low",
        "年化波動": "low",
        "Sharpe": "high",
        "Sortino": "high",
    }

    for col, direction in highlight_rules.items():
        valid = raw_table[col].dropna()
        if valid.empty:
            continue
        best = valid.max() if direction == "high" else valid.min()

        def style_col(_):
            styles = []
            for idx in raw_table.index:
                val = raw_table.loc[idx, col]
                is_best = (not np.isnan(val)) and (val == best)
                styles.append("color: #28a745; font-weight: bold;" if is_best else "color: #d9534f;")
            return styles

        styled = styled.apply(style_col, subset=[col], axis=0)

    st.write(styled.to_html(), unsafe_allow_html=True)

    ###############################################################
    # Footer：指標說明
    ###############################################################

    st.markdown(
        """
<div style="
    margin-top: 20px;
    padding: 18px 22px;
    border-left: 4px solid #4A90E2;
    background: rgba(0,0,0,0.03);
    border-radius: 6px;
    font-size: 15px;
    line-height: 1.7;
">

<h4>📘 指標怎麼看？（快速理解版）</h4>

<b>CAGR（年化報酬）</b>：一年平均賺多少，是長期投資最重要的指標。<br>
<b>總報酬率</b>：整段時間一共賺多少。<br>
<b>Sharpe Ratio</b>：承受一單位波動，能換到多少報酬。越高越穩定。<br>
<b>Sortino Ratio</b>：只看「跌」的波動，越高越抗跌。<br>
<b>最大回撤（MDD）</b>：最慘跌到多深。越小越好。<br>
<b>年化波動</b>：每天跳來跳去的程度。越低越舒服。<br>
<b>Calmar Ratio</b>：把報酬和回撤放一起看，越高代表越有效率。<br>

</div>
        """,
        unsafe_allow_html=True,
    )
