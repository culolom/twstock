import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import datetime

# 系統初始化與設定
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(page_title="倉鼠量化戰情室", layout="wide", page_icon="🐹")

# --- 1. 抓取當沖量前 20 名 (證交所公開資料) ---
def get_top_20_daytrade():
    """抓取證交所今日當沖成交量排行"""
    try:
        # 證交所當沖成交值統計表
        url = "https://www.twse.com.tw/exchangeReport/TWTB4U?response=json"
        res = requests.get(url, verify=False, timeout=10)
        data = res.json()
        if 'data' not in data:
            return []
        df = pd.DataFrame(data['data'], columns=data['fields'])
        # 轉換成交股數為數值
        df['成交股數'] = df['成交股數'].str.replace(',', '').astype(float)
        # 取得成交股數前 20 名的代號
        top_20 = df.sort_values(by='成交股數', ascending=False).head(20)['證券代號'].tolist()
        return top_20
    except Exception as e:
        st.error(f"當沖資料抓取失敗: {e}")
        return []

# --- 2. 自動抓取全台股清單 (Cache 一天) ---
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
            if not table: continue
            for row in table.find_all('tr')[2:]:
                cols = row.find_all('td')
                if len(cols) > 0:
                    text = cols[0].text.strip().split('\u3000')
                    if len(text) == 2 and len(text[0]) == 4:
                        all_stocks.append({
                            "ticker": f"{text[0]}{'.TW' if market=='上市' else '.TWO'}",
                            "name": text[1], "market": market, "id": text[0]
                        })
        except: pass
    return pd.DataFrame(all_stocks)

# --- 3. 核心邏輯：矽格/金居模式 + 當沖熱度 ---
def scan_logic(row, top_20_list, max_dist, only_hot):
    ticker = row['ticker']
    # 如果勾選「僅看熱門當沖」，代號不在清單內就直接跳過，省去下載時間
    if only_hot and row['id'] not in top_20_list:
        return None

    try:
        # 下載資料
        df = yf.download(ticker, period="15mo", progress=False, threads=False, auto_adjust=False)
        if len(df) < 210: return None

        close = df['Close'].squeeze()
        volume = df['Volume'].squeeze()
        
        # 指標計算
        ma5 = close.rolling(5).mean().iloc[-1]
        ma10 = close.rolling(10).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        ma200 = close.rolling(200).mean().iloc[-1]
        vma20 = volume.rolling(20).mean().iloc[-1]
        curr_p = close.iloc[-1]

        # 糾結度與距離計算
        ma_group = [ma5, ma10, ma20, ma200]
        squeeze_ratio = (max(ma_group) / min(ma_group) - 1) * 100
        dist_200 = ((ma5 / ma200) - 1) * 100

        # 條件檢查
        is_aligned = ma5 > ma10 > ma20 > ma200
        is_vol_spike = volume.iloc[-1] > vma20 * 1.5
        is_not_too_far = dist_200 <= max_dist
        is_on_top = curr_p > ma5

        if is_aligned and is_vol_spike and is_not_too_far and is_on_top:
            return {
                "代碼": row['id'], "名稱": row['name'], "現價": round(float(curr_p), 2),
                "量增倍數": round(float(volume.iloc[-1] / vma20), 2),
                "離年線%": round(dist_200, 2), "糾結度%": round(squeeze_ratio, 2),
                "當沖人氣": "🔥" if row['id'] in top_20_list else "普通"
            }
    except: return None
    return None

# --- 4. 介面與執行 ---
st.title("🐹 倉鼠量化戰情室：飆股終極掃描器")
st.markdown("專找「長期壓抑、爆量噴發、市場熱門」的超級飆股。")

df_all = get_taiwan_stock_list()
st.sidebar.header("⚙️ 篩選設定")
only_hot = st.sidebar.checkbox("僅顯示當沖量前 20 名 (飆股限定)", value=False)
max_dist = st.sidebar.slider("5MA/200MA 最大乖離 %", 2.0, 15.0, 10.0)
limit = st.sidebar.slider("掃描數量", 100, len(df_all), 500)
workers = st.sidebar.slider("並行執行緒數", 5, 20, 15)

if st.button("🚀 開始全市場戰情掃描"):
    top_20 = get_top_20_daytrade()
    target_stocks = df_all.head(limit).to_dict('records')
    results = []
    
    p = st.progress(0)
    status = st.empty()
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(scan_logic, s, top_20, max_dist, only_hot): s for s in target_stocks}
        for i, future in enumerate(as_completed(futures)):
            res = future.result()
            if res: results.append(res)
            if (i+1) % 10 == 0 or (i+1) == len(target_stocks):
                p.progress((i+1)/len(target_stocks))
                status.text(f"掃描中: {i+1}/{len(target_stocks)} (已找到 {len(results)} 檔)")

    st.success(f"✅ 掃描完成！耗時 {round(time.time()-start_time, 1)} 秒")

    if results:
        st.balloons()
        final_df = pd.DataFrame(results).sort_values("量增倍數", ascending=False)
        st.subheader(f"🔥 強力觀察清單 ({len(results)} 檔)")
        st.dataframe(final_df, use_container_width=True, hide_index=True)
    else:
        st.warning("☹️ 目前查無符合所有條件（糾結、排列、爆量、距離限制）的標的。")
