import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# 1. 初始化設定
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(page_title="倉鼠量化戰情室 - 方案A", layout="wide", page_icon="🐹")

# --- 抓取台股清單 (Cache 一天) ---
@st.cache_data(ttl=86400)
def get_stock_list():
    urls = {
        "上市": "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2",
        "上櫃": "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"
    }
    headers = {'User-Agent': 'Mozilla/5.0'}
    all_stocks = []
    for market, url in urls.items():
        try:
            response = requests.get(url, verify=False, headers=headers)
            response.encoding = 'big5'
            soup = BeautifulSoup(response.text, 'html.parser')
            table = soup.find('table', {'class': 'h4'})
            for row in table.find_all('tr')[2:]:
                cols = row.find_all('td')
                if len(cols) > 0:
                    text = cols[0].text.strip().split('\u3000')
                    if len(text) == 2 and len(text[0]) == 4:
                        all_stocks.append({
                            "ticker": f"{text[0]}{'.TW' if market=='上市' else '.TWO'}",
                            "name": text[1],
                            "market": market
                        })
        except: pass
    return pd.DataFrame(all_stocks)

# --- 核心邏輯：方案 A (5日回測突破) ---
def check_momentum_a(row):
    ticker = row['ticker']
    try:
        # 下載 14 個月資料
        df = yf.download(ticker, period="14mo", progress=False, threads=False)
        if len(df) < 210: return None

        # 計算指標 (處理 yfinance 可能回傳的多層索引)
        close = df['Close'].squeeze()
        volume = df['Volume'].squeeze()
        
        ma5 = close.rolling(5).mean()
        ma10 = close.rolling(10).mean()
        ma20 = close.rolling(20).mean()
        ma200 = close.rolling(200).mean()
        vma20 = volume.rolling(20).mean()

        curr_price = close.iloc[-1]
        curr_ma200 = ma200.iloc[-1]
        
        # --- 方案 A 邏輯修改處 ---
        # 過去 5 個交易日(不含今天) 只要有一天收盤價 < 200MA
        prev_5_days_close = close.iloc[-6:-1]
        prev_5_days_ma200 = ma200.iloc[-6:-1]
        was_below_200 = (prev_5_days_close < prev_5_days_ma200).any()
        
        # 現在必須站在 200MA 之上
        is_above_200 = curr_price > curr_ma200
        # ------------------------

        # 均線多頭排列 (5 > 10 > 20)
        ma_aligned = ma5.iloc[-1] > ma10.iloc[-1] > ma20.iloc[-1]
        
        # 成交量增溫 (> 1.5倍)
        vol_ratio = float(volume.iloc[-1] / vma20.iloc[-1])
        vol_spike = vol_ratio > 1.5

        if was_below_200 and is_above_200 and ma_aligned and vol_spike:
            return {
                "代碼": ticker.split('.')[0],
                "名稱": row['name'],
                "現價": round(float(curr_price), 2),
                "量增倍數": round(vol_ratio, 2),
                "200MA": round(float(curr_ma200), 2),
                "市場": row['market']
            }
    except: return None
    return None

# --- UI 介面 ---
st.title("🛡️ 倉鼠量化戰情室 (方案A：極速版)")
st.markdown("### 聚焦「年線回測」後的強力噴發股")

# 側邊欄
df_all = get_stock_list()
st.sidebar.header("掃描設定")
limit = st.sidebar.slider("掃描數量", 100, len(df_all), 300)
workers = st.sidebar.slider("加速執行緒", 5, 20, 10)

if st.button(f"🚀 開始掃描前 {limit} 檔"):
    target_stocks = df_all.head(limit).to_dict('records')
    results = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    start_time = time.time()

    # 使用多執行緒加速
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(check_momentum_a, s): s for s in target_stocks}
        for i, future in enumerate(as_completed(futures)):
            res = future.result()
            if res: results.append(res)
            # 每 5 檔更新一次介面，兼顧效能
            if (i+1) % 5 == 0:
                progress_bar.progress((i + 1) / limit)
                status_text.text(f"已掃描 {i+1} / {limit} 檔...")

    duration = round(time.time() - start_time, 1)
    status_text.success(f"✅ 掃描完成！耗時 {duration} 秒")

    if results:
        st.balloons()
        res_df = pd.DataFrame(results).sort_values("量增倍數", ascending=False)
        st.dataframe(res_df, use_container_width=True, hide_index=True)
    else:
        st.warning("☹️ 前段班暫無符合「回測 200MA」之標的，建議擴大掃描範圍。")
