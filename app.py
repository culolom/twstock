import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import time

# 設定頁面資訊
st.set_page_config(page_title="倉鼠量化戰情室", layout="wide", page_icon="🐹")

# --- CSS 樣式美化 ---
st.markdown("""
    <style>
    .main { background-color: #f5f7f9; }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; background-color: #ff4b4b; color: white; }
    </style>
    """, unsafe_allow_html=True)

st.title("🐹 倉鼠量化戰情室：動能突破搜尋器")
st.info("策略邏輯：過去30天曾低於200MA + 今日站上200MA + 均線多頭(5>10>20) + 成交量爆發(>1.5倍)")

# --- 核心功能：抓取全台股清單 ---
@st.cache_data(ttl=86400)
def get_all_taiwan_stock_tickers():
    """從證交所抓取所有上市與上櫃股票代碼"""
    urls = {
        "上市": "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2",
        "上櫃": "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"
    }
    all_tickers = []
    for market, url in urls.items():
        try:
            response = requests.get(url)
            soup = BeautifulSoup(response.text, 'html.parser')
            table = soup.find('table', {'class': 'h4'})
            for row in table.find_all('tr')[2:]:
                cols = row.find_all('td')
                if len(cols) > 0:
                    text = cols[0].text.strip()
                    parts = text.split('\u3000')
                    # 篩選標準 4 位數股票代碼
                    if len(parts) == 2 and len(parts[0]) == 4:
                        ticker = parts[0]
                        suffix = ".TW" if market == "上市" else ".TWO"
                        all_tickers.append(f"{ticker}{suffix}")
        except Exception as e:
            st.error(f"抓取{market}清單失敗: {e}")
    return all_tickers

# --- 核心功能：分析單一股票動能 ---
def analyze_stock(ticker):
    try:
        # 下載 1.5 年的數據以確保 200MA 計算準確
        df = yf.download(ticker, period="14mo", progress=False)
        if len(df) < 210:
            return None

        # 計算技術指標
        df['MA5'] = df['Close'].rolling(window=5).mean()
        df['MA10'] = df['Close'].rolling(window=10).mean()
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['MA200'] = df['Close'].rolling(window=200).mean()
        df['VMA20'] = df['Volume'].rolling(window=20).mean()

        # 取得最新與歷史數據
        current = df.iloc[-1]
        prev_30_days = df.iloc[-31:-1] # 過去 30 個交易日

        # 條件 1：底部突破 (過去30天曾低於 200MA，且現在高於 200MA)
        was_below_200 = (prev_30_days['Close'] < prev_30_days['MA200']).any()
        is_above_200 = current['Close'] > current['MA200']

        # 條件 2：均線多頭排列 (5MA > 10MA > 20MA)
        ma_alignment = current['MA5'] > current['MA10'] > current['MA20']

        # 條件 3：成交量爆發 (今日量 > 20日均量 * 1.5)
        volume_spike = current['Volume'] > (current['VMA20'] * 1.5)

        if was_below_200 and is_above_200 and ma_alignment and volume_spike:
            return {
                "代碼": ticker.split('.')[0],
                "現價": round(float(current['Close']), 2),
                "5MA": round(float(current['MA5']), 2),
                "20MA": round(float(current['MA20']), 2),
                "200MA": round(float(current['MA200']), 2),
                "成交量倍數": round(float(current['Volume'] / current['VMA20']), 2),
                "今日成交量": int(current['Volume'])
            }
    except:
        return None
    return None

# --- UI 側邊欄 ---
st.sidebar.header("⚙️ 掃描設定")
all_stocks = get_all_taiwan_stock_tickers()
st.sidebar.success(f"已更新全台股清單：共 {len(all_stocks)} 檔")

# 為了防止 Demo 跑太久，可以讓用戶選範圍
sample_size = st.sidebar.slider("掃描樣本數", 50, len(all_stocks), 200)
sort_by = st.sidebar.selectbox("排序方式", ["成交量倍數", "現價"])

# --- 執行掃描 ---
if st.button("🚀 開始全市場掃描 (倉鼠出擊)"):
    results = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # 執行掃描
    target_list = all_stocks[:sample_size]
    start_time = time.time()
    
    for i, ticker in enumerate(target_list):
        status_text.text(f"🔍 正在分析: {ticker} ({i+1}/{len(target_list)})")
        data = analyze_stock(ticker)
        if data:
            results.append(data)
        progress_bar.progress
