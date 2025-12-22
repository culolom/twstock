import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(page_title="倉鼠戰情室 - 金居模式", layout="wide", page_icon="🐹")

# --- 抓取台股清單 ---
@st.cache_data(ttl=86400)
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

# --- 核心邏輯：金居起漲模式 ---
def scan_jinju_pattern(row, max_dist_60):
    ticker = row['ticker']
    try:
        # 下載足以計算 200MA 與 240MA 的資料
        df = yf.download(ticker, period="18mo", progress=False, threads=False, auto_adjust=False)
        if len(df) < 240: return None

        close = df['Close'].squeeze()
        volume = df['Volume'].squeeze()
        
        # 技術指標計算
        ma5 = close.rolling(5).mean().iloc[-1]
        ma10 = close.rolling(10).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1] # 季線
        ma200 = close.rolling(200).mean().iloc[-1] # 年線
        vma20 = volume.rolling(20).mean().iloc[-1]

        curr_p = close.iloc[-1]
        
        # 條件 1：全均線多頭排列 (5 > 10 > 20 > 60 > 200)
        # 這是金居 2025/7/8 之後噴發的標準型態
        is_aligned = ma5 > ma10 > ma20 > ma60 > ma200
        
        # 條件 2：帶量突破 (今日量 > 20日均量 1.5倍)
        vol_spike = (volume.iloc[-1] / vma20) > 1.5
        
        # 條件 3：距離季線不要太遠 (確保還在起漲段)
        dist_from_60 = ((curr_p / ma60) - 1) * 100
        near_60 = dist_from_60 <= max_dist_60

        # 條件 4：過去 5 天曾靠近或低於年線 (符合你之前的方案 A 突破邏輯)
        prev_5_low = close.iloc[-6:-1].min()
        was_near_200 = prev_5_low < (ma200 * 1.02) # 只要跌破或靠近年線 2% 內

        if is_aligned and vol_spike and near_60 and was_near_200:
            return {
                "代碼": ticker.split('.')[0],
                "名稱": row['name'],
                "現價": round(float(curr_p), 2),
                "量增倍數": round(float(volume.iloc[-1] / vma20), 2),
                "季線距離%": round(dist_from_60, 2),
                "季線價格": round(float(ma60), 2),
                "年線價格": round(float(ma200), 2)
            }
    except: return None
    return None

# --- UI 介面 ---
st.title("🛡️ 倉鼠量化戰情室 - 金居起漲模式")
st.markdown("### 標的特徵：均線全排列 + 季線上方起跳")

df_all = get_taiwan_stock_list()
st.sidebar.header("⚙️ 戰情參數")
max_dist_60 = st.sidebar.slider("離季線最大距離 % (起漲門檻)", 2.0, 15.0, 8.0)
scan_num = st.sidebar.slider("掃描數量", 100, len(df_all), 500)

if st.button("🚀 執行全市場掃描"):
    stocks = df_all.head(scan_num).to_dict('records')
    results = []
    p = st.progress(0)
    status = st.empty()
    
    with ThreadPoolExecutor(max_workers=15) as ex:
        futures = {ex.submit(scan_jinju_pattern, s, max_dist_60): s for s in stocks}
        for i, f in enumerate(as_completed(futures)):
            res = f.result()
            if res: results.append(res)
            if (i+1) % 10 == 0:
                p.progress((i+1)/len(stocks))
                status.text(f"已分析 {i+1} 檔... 找到 {len(results)} 檔標的")

    if results:
        st.balloons()
        st.subheader(f"🔥 發現 {len(results)} 檔符合「金居模式」標的")
        res_df = pd.DataFrame(results).sort_values("量增倍數", ascending=False)
        st.dataframe(res_df, use_container_width=True, hide_index=True)
        st.info("💡 策略提示：此清單標的皆為全均線多頭排列。如你所說，跌破季線 ($60MA$) 可考慮出場。")
    else:
        st.warning("查無符合金居模式之標的。")
