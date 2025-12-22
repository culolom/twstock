import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed

# 基礎設定
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(page_title="倉鼠量化極速版", layout="wide")

@st.cache_data(ttl=86400)
def get_taiwan_stock_list():
    # ... (保持原有的抓取清單邏輯，此處省略以節省空間) ...
    return df_stocks # 假設回傳包含 ticker, name, market 的 DataFrame

def check_momentum_fast(row):
    """這是在多執行緒中運行的核心邏輯"""
    ticker = row['ticker']
    try:
        # 僅下載必要天數 (14個月) 以節省頻寬
        df = yf.download(ticker, period="14mo", progress=False, threads=False)
        if len(df) < 210: return None

        # 指標計算
        close = df['Close'].iloc[:, 0] if isinstance(df['Close'], pd.DataFrame) else df['Close']
        vol = df['Volume'].iloc[:, 0] if isinstance(df['Volume'], pd.DataFrame) else df['Volume']
        
        ma5 = close.rolling(5).mean()
        ma10 = close.rolling(10).mean()
        ma20 = close.rolling(20).mean()
        ma200 = close.rolling(200).mean()
        vma20 = vol.rolling(20).mean()

        # 邏輯判斷
        curr_price = close.iloc[-1]
        curr_ma200 = ma200.iloc[-1]
        past_30_close = close.iloc[-31:-1]
        past_30_ma200 = ma200.iloc[-31:-1]

        cond1 = (past_30_close < past_30_ma200).any() and (curr_price > curr_ma200)
        cond2 = ma5.iloc[-1] > ma10.iloc[-1] > ma20.iloc[-1]
        vol_ratio = float(vol.iloc[-1] / vma20.iloc[-1])
        cond3 = vol_ratio > 1.5

        if cond1 and cond2 and cond3:
            return {
                "代碼": ticker.split('.')[0], "名稱": row['name'],
                "現價": round(float(curr_price), 2), "成交量倍數": round(vol_ratio, 2),
                "市場": row['market']
            }
    except:
        return None
    return None

# --- UI 部分 ---
st.title("🚀 倉鼠極速掃描器 (多執行緒版)")

df_stocks = get_taiwan_stock_list()
limit = st.sidebar.slider("掃描數量", 100, len(df_stocks), 500)
max_workers = st.sidebar.slider("並行執行緒數", 1, 20, 10) # 建議 10-15，太高會被 Yahoo 封鎖

if st.button("開始極速掃描"):
    target_stocks = df_stocks.head(limit).to_dict('records')
    results = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # 使用 ThreadPoolExecutor 並行加速
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_stock = {executor.submit(check_momentum_fast, stock): stock for stock in target_stocks}
        
        completed = 0
        for future in as_completed(future_to_stock):
            completed += 1
            res = future.result()
            if res:
                results.append(res)
            
            # 每處理 10 檔更新一次進度條，減少 UI 負擔
            if completed % 10 == 0 or completed == limit:
                progress_bar.progress(completed / limit)
                status_text.text(f"已完成: {completed} / {limit}")

    if results:
        st.write(pd.DataFrame(results))
    else:
        st.write("查無符合條件標的")
