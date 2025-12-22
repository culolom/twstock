import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

st.set_page_config(page_title="台股動能突破搜尋器", layout="wide")

st.title("🐹 倉鼠量化戰情室：台股強勢動能篩選器")
st.write("篩選條件：1. 過去30天曾低於200SMA 2. 現價突破200SMA 3. 5MA > 10MA > 20MA")

# 1. 定義要掃描的標的 (範例：台灣50與中型100成分股，或手動輸入)
# 建議實務上可以從公開資訊觀測站抓取全台股清單
default_tickers = ["2330.TW", "2317.TW", "2454.TW", "2308.TW", "2382.TW", "2357.TW", "3231.TW", "6669.TW", "2603.TW", "2609.TW"]

tickers_input = st.text_area("輸入台股代碼 (以逗號分隔，需加 .TW 或 .TWO)", value=",".join(default_tickers))
target_list = [t.strip() for t in tickers_input.split(",")]

def check_momentum(ticker):
    try:
        # 下載至少 250 天的資料以計算 200MA
        end_date = datetime.now()
        start_date = end_date - timedelta(days=400)
        df = yf.download(ticker, start=start_date, end=end_date, progress=False)
        
        if len(df) < 200:
            return None

        # 計算均線
        df['MA5'] = df['Close'].rolling(window=5).mean()
        df['MA10'] = df['Close'].rolling(window=10).mean()
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['MA200'] = df['Close'].rolling(window=200).mean()

        # 取最新一筆資料
        current = df.iloc[-1]
        
        # 取得過去 30 天的資料 (不含今天)
        past_30_days = df.iloc[-31:-1]

        # 條件檢查
        # 1. 過去 30 天內，收盤價曾低於 200MA (證明是從底部上來的)
        cond1 = (past_30_days['Close'] < past_30_days['MA200']).any()
        
        # 2. 現在收盤價高於 200MA
        cond2 = current['Close'] > current['MA200']
        
        # 3. 5MA > 10MA > 20MA (多頭排列)
        cond3 = current['MA5'] > current['MA10'] and current['MA10'] > current['MA20']

        if cond1 and cond2 and cond3:
            return {
                "代碼": ticker,
                "收盤價": round(float(current['Close']), 2),
                "5MA": round(float(current['MA5']), 2),
                "20MA": round(float(current['MA20']), 2),
                "200MA": round(float(current['MA200']), 2)
            }
    except Exception as e:
        return None
    return None

if st.button("開始掃描"):
    results = []
    progress_bar = st.progress(0)
    
    for i, ticker in enumerate(target_list):
        res = check_momentum(ticker)
        if res:
            results.append(res)
        progress_bar.progress((i + 1) / len(target_list))
    
    if results:
        st.success(f"找到 {len(results)} 檔符合條件的標的！")
        res_df = pd.DataFrame(results)
        st.dataframe(res_df, use_container_width=True)
    else:
        st.warning("目前沒有符合條件的標的。")
