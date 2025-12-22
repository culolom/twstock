import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# 系統初始化
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(page_title="倉鼠戰情室 - 金居糾結模式", layout="wide", page_icon="🐹")

# --- 抓取台股清單 (Cache 24小時) ---
@st.cache_data(ttl=86400)
def get_taiwan_stock_list():
    urls = {"上市": "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", 
            "上櫃": "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"}
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

# --- 核心邏輯：均線糾結突破 (金居模式) ---
def scan_squeeze_logic(row, squeeze_threshold, vol_threshold):
    ticker = row['ticker']
    try:
        # 下載 15 個月資料以計算 240MA
        df = yf.download(ticker, period="15mo", progress=False, threads=False, auto_adjust=False)
        if len(df) < 240: return None

        close = df['Close'].squeeze()
        volume = df['Volume'].squeeze()
        
        # 指標計算
        ma5 = close.rolling(5).mean().iloc[-1]
        ma10 = close.rolling(10).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1]
        ma200 = close.rolling(200).mean().iloc[-1]
        vma20 = volume.rolling(20).mean().iloc[-1]
        curr_p = close.iloc[-1]

        # 1. 計算均線糾結度 (5, 10, 20, 60MA 的最大差距百分比)
        ma_group = [ma5, ma10, ma20, ma60]
        # 公式：(Max / Min - 1) * 100
        squeeze_ratio = (max(ma_group) / min(ma_group) - 1) * 100
        
        # --- 判斷條件 ---
        # A. 均線高度糾結
        cond_squeeze = squeeze_ratio <= squeeze_threshold
        # B. 股價剛突破糾結區 (收盤價大於所有短期均線)
        cond_breakout = curr_p > max(ma_group)
        # C. 帶量突破 (今日成交量 > 20日均量 * 門檻)
        vol_ratio = float(volume.iloc[-1] / vma20)
        cond_volume = vol_ratio >= vol_threshold
        # D. 長期趋势守護 (要在年線 200MA 之上)
        cond_trend = curr_p > ma200

        if cond_squeeze and cond_breakout and cond_volume and cond_trend:
            return {
                "代碼": ticker.split('.')[0],
                "名稱": row['name'],
                "現價": round(float(curr_p), 2),
                "糾結度%": round(squeeze_ratio, 2),
                "量增倍數": round(vol_ratio, 2),
                "離季線%": round(((curr_p/ma60)-1)*100, 2),
                "市場": row['market']
            }
    except: return None
    return None

# --- Streamlit UI ---
st.title("🐹 倉鼠戰情室：金居起漲(均線糾結)版")
st.markdown("針對**「橫盤許久、均線糾結、帶量噴發」**的標的進行全自動掃描。")

df_all = get_taiwan_stock_list()
st.sidebar.header("⚙️ 戰情參數設定")
squeeze_input = st.sidebar.slider("均線糾結門檻 % (愈小愈擠)", 1.0, 10.0, 5.0)
vol_input = st.sidebar.slider("成交量爆發門檻 (倍數)", 1.2, 5.0, 1.5)
scan_limit = st.sidebar.slider("掃描數量 (建議全市場)", 100, len(df_all), 1000)

if st.button("🚀 啟動全市場動能掃描"):
    target_stocks = df_all.head(scan_limit).to_dict('records')
    results = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = {executor.submit(scan_squeeze_logic, s, squeeze_input, vol_input): s for s in target_stocks}
        for i, future in enumerate(as_completed(futures)):
            res = future.result()
            if res: results.append(res)
            if (i+1) % 10 == 0 or (i+1) == len(target_stocks):
                progress_bar.progress((i+1)/len(target_stocks))
                status_text.text(f"已掃描 {i+1} 檔，目前發現 {len(results)} 檔符合糾結突破...")

    st.success(f"✅ 掃描完成！耗時 {round(time.time()-start_time, 1)} 秒")

    if results:
        st.balloons()
        final_df = pd.DataFrame(results).sort_values("糾結度%")
        st.subheader(f"🔥 今日糾結突破標的 ({len(results)} 檔)")
        st.dataframe(final_df, use_container_width=True, hide_index=True)
        st.info("💡 倉鼠提醒：找『糾結度%』最小的標的，那代表力量壓縮最極致！")
    else:
        st.warning("☹️ 目前市場中沒有符合高度糾結且帶量突破的標的。")
