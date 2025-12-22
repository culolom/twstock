import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import time
import urllib3

# 1. 初始化設定與忽略 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="倉鼠量化戰情室", layout="wide", page_icon="🐹")

# 自定義 CSS 讓介面更專業
st.markdown("""
    <style>
    .stProgress > div > div > div > div { background-image: linear-gradient(to right, #4facfe 0%, #00f2fe 100%); }
    .stDataFrame { border: 1px solid #e6e9ef; border-radius: 10px; }
    </style>
    """, unsafe_allow_html=True)

# --- 第一部分：自動抓取全台股清單 (修正 SSL 與 編碼問題) ---
@st.cache_data(ttl=86400)
def get_taiwan_stock_list():
    """從證交所抓取所有上市與上櫃股票代碼"""
    urls = {
        "上市": "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2",
        "上櫃": "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"
    }
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    
    all_tickers = []
    
    for market, url in urls.items():
        try:
            # 加入 verify=False 解決 SSL 錯誤
            response = requests.get(url, verify=False, headers=headers)
            response.encoding = 'big5' 
            soup = BeautifulSoup(response.text, 'html.parser')
            table = soup.find('table', {'class': 'h4'})
            
            if not table: continue
            
            rows = table.find_all('tr')
            for row in rows[2:]:
                cols = row.find_all('td')
                if len(cols) > 0:
                    text = cols[0].text.strip()
                    parts = text.split('\u3000') # 處理全形空格
                    if len(parts) == 2 and len(parts[0]) == 4:
                        ticker = parts[0]
                        name = parts[1]
                        suffix = ".TW" if market == "上市" else ".TWO"
                        all_tickers.append({"ticker": f"{ticker}{suffix}", "name": name, "market": market})
        except Exception as e:
            st.error(f"抓取 {market} 清單失敗: {e}")
            
    return pd.DataFrame(all_tickers)

# --- 第二部分：量化篩選邏輯 ---
def check_momentum(ticker_row):
    ticker = ticker_row['ticker']
    name = ticker_row['name']
    try:
        # 下載足以計算 200MA 的資料
        df = yf.download(ticker, period="14mo", progress=False)
        if len(df) < 210: return None

        # 計算均線
        df['MA5'] = df['Close'].rolling(window=5).mean()
        df['MA10'] = df['Close'].rolling(window=10).mean()
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['MA200'] = df['Close'].rolling(window=200).mean()
        df['VMA20'] = df['Volume'].rolling(window=20).mean()

        curr = df.iloc[-1]
        prev_30_days = df.iloc[-31:-1]

        # 條件 1: 過去30天曾低於 200MA，且現在高於 200MA (剛突破)
        was_below_200 = (prev_30_days['Close'] < prev_30_days['MA200']).any()
        is_above_200 = curr['Close'] > curr['MA200']

        # 條件 2: 5MA > 10MA > 20MA (多頭排列)
        ma_aligned = curr['MA5'] > curr['MA10'] > curr['MA20']

        # 條件 3: 成交量爆發 (今日量 > 20日均量 * 1.5)
        vol_ratio = float(curr['Volume'] / curr['VMA20'])
        vol_spike = vol_ratio > 1.5

        if was_below_200 and is_above_200 and ma_aligned and vol_spike:
            return {
                "代碼": ticker.replace(".TW", "").replace(".TWO", ""),
                "名稱": name,
                "現價": round(float(curr['Close']), 2),
                "成交量倍數": round(vol_ratio, 2),
                "5MA": round(float(curr['MA5']), 2),
                "200MA": round(float(curr['MA200']), 2),
                "市場": ticker_row['market']
            }
    except:
        return None
    return None

# --- 第三部分：Streamlit UI 介面 ---
st.title("🛡️ 倉鼠量化戰情室")
st.subheader("台股「初升段」動能篩選器")

with st.expander("📌 策略說明"):
    st.write("""
    1. **新突破**：過去 30 天曾跌破 200 日線，確保不是漲很久的股票，而是新轉強的。
    2. **多頭排列**：短、中、長期均線依序排列，動能正在加速。
    3. **量能增溫**：今日成交量大於過去 20 日平均的 1.5 倍，代表大戶開始進場。
    """)

# 側邊欄控制
df_stocks = get_taiwan_stock_list()
st.sidebar.header("搜尋範圍")
market_choice = st.sidebar.multiselect("選擇市場", ["上市", "上櫃"], default=["上市", "上櫃"])
limit = st.sidebar.slider("掃描前 N 檔 (節省時間)", 100, len(df_stocks), 300)

if st.button("🚀 開始掃描全市場"):
    filtered_list = df_stocks[df_stocks['market'].isin(market_choice)].head(limit)
    
    results = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    start_time = time.time()
    
    for i, (_, row) in enumerate(filtered_list.iterrows()):
        status_text.text(f"正在分析 {row['ticker']} {row['name']}...")
        res = check_momentum(row)
        if res:
            results.append(res)
        progress_bar.progress((i + 1) / len(filtered_list))
        
    end_time = time.time()
    status_text.success(f"掃描完成！耗時 {round(end_time - start_time, 1)} 秒")
    
    if results:
        res_df = pd.DataFrame(results)
        st.success(f"🔥 篩選結果：發現 {len(results)} 檔符合條件")
        # 依成交量倍數排序
        st.dataframe(res_df.sort_values(by="成交量倍數", ascending=False), use_container_width=True, hide_index=True)
        
        # 下載功能
        csv = res_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 下載篩選清單", csv, "hamster_report.csv", "text/csv")
    else:
        st.warning("☹️ 目前市場沒有符合條件的標的。")
