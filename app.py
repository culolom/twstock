import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(page_title="倉鼠量化戰情室 - 精準版", layout="wide", page_icon="🐹")

@st.cache_data(ttl=3600) # 改為一小時更新一次清單
def get_taiwan_stock_list():
    urls = {"上市": "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", "上櫃": "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"}
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
                        all_stocks.append({"ticker": f"{text[0]}{'.TW' if market=='上市' else '.TWO'}", "name": text[1], "market": market})
        except: pass
    return pd.DataFrame(all_stocks)

def scan_logic(row, max_dist):
    ticker = row['ticker']
    try:
        # 重點：auto_adjust=False 確保使用原始收盤價，與看盤軟體一致
        df = yf.download(ticker, period="15mo", progress=False, threads=False, auto_adjust=False)
        if len(df) < 210: return None

        close = df['Close'].squeeze()
        volume = df['Volume'].squeeze()
        last_date = df.index[-1].strftime('%Y-%m-%d')
        
        # 均線計算 (SMA)
        ma5 = close.rolling(5).mean()
        ma10 = close.rolling(10).mean()
        ma20 = close.rolling(20).mean()
        ma200 = close.rolling(200).mean()
        vma20 = volume.rolling(20).mean()

        c_p = close.iloc[-1]
        m5, m10, m20, m200 = ma5.iloc[-1], ma10.iloc[-1], ma20.iloc[-1], ma200.iloc[-1]
        
        # 條件檢查
        prev_5_close = close.iloc[-6:-1]
        prev_5_ma200 = ma200.iloc[-6:-1]
        was_below = (prev_5_close < prev_5_ma200).any()
        
        perfect_align = m5 > m10 > m20 > m200
        vol_ratio = float(volume.iloc[-1] / vma20.iloc[-1])
        dist = ((m5 / m200) - 1) * 100

        if was_below and c_p > m200 and perfect_align and vol_ratio > 1.5 and dist <= max_dist:
            return {
                "日期": last_date, "代碼": ticker.split('.')[0], "名稱": row['name'],
                "現價": round(float(c_p), 2), "量增倍數": round(vol_ratio, 2),
                "5MA": round(float(m5), 2), "200MA": round(float(m200), 2),
                "離年線%": round(dist, 2)
            }
    except: return None

st.title("🛡️ 倉鼠量化戰情室 (精準同步版)")
st.sidebar.header("參數調整")
max_dist = st.sidebar.slider("5MA/200MA 最大乖離 %", 2.0, 15.0, 10.0)
scan_limit = st.sidebar.slider("掃描數量", 100, 1000, 300)

if st.button("🚀 開始全市場戰情掃描"):
    stocks = get_taiwan_stock_list().head(scan_limit).to_dict('records')
    results = []
    p = st.progress(0)
    with ThreadPoolExecutor(max_workers=15) as ex:
        futures = {ex.submit(scan_logic, s, max_dist): s for s in stocks}
        for i, f in enumerate(as_completed(futures)):
            res = f.result()
            if res: results.append(res)
            p.progress((i+1)/len(stocks))
            
    if results:
        st.dataframe(pd.DataFrame(results).sort_values("量增倍數", ascending=False), hide_index=True)
    else:
        st.warning("查無標的。")
