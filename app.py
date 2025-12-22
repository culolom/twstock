import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# ----------------------------------------------------------------
# 1. 系統初始化與設定
# ----------------------------------------------------------------
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(page_title="倉鼠量化戰情室", layout="wide", page_icon="🐹")

# 自定義 CSS
st.markdown("""
    <style>
    .stProgress > div > div > div > div { background-image: linear-gradient(to right, #11998e 0%, #38ef7d 100%); }
    .stDataFrame { border: 1px solid #dee2e6; border-radius: 8px; }
    </style>
    """, unsafe_allow_html=True)

# ----------------------------------------------------------------
# 2. 自動抓取台股清單 (Cache 一天)
# ----------------------------------------------------------------
@st.cache_data(ttl=86400)
def get_taiwan_stock_list():
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
            if not table: continue
            
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

# ----------------------------------------------------------------
# 3. 核心邏輯：方案 A + 四線多頭 + 乖離率控制
# ----------------------------------------------------------------
def scan_stock_logic(row, max_dist_pct):
    ticker = row['ticker']
    name = row['name']
    try:
        df = yf.download(ticker, period="14mo", progress=False, threads=False)
        if len(df) < 210: return None

        close = df['Close'].squeeze()
        volume = df['Volume'].squeeze()
        
        # 指標計算
        ma5 = close.rolling(5).mean().iloc[-1]
        ma10 = close.rolling(10).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        ma200 = close.rolling(200).mean().iloc[-1]
        vma20 = volume.rolling(20).mean().iloc[-1]

        curr_price = close.iloc[-1]
        
        # 條件 1：方案 A (最近 5 天曾低於 200MA)
        prev_5_days_close = close.iloc[-6:-1]
        prev_5_days_ma200 = close.rolling(200).mean().iloc[-6:-1]
        was_below_200 = (prev_5_days_close < prev_5_days_ma200).any()
        is_above_200 = curr_price > ma200

        # 條件 2：完全多頭排列 (5 > 10 > 20 > 200)
        ma_perfect_alignment = ma5 > ma10 > ma20 > ma200
        
        # 條件 3：成交量爆發 (今日量 > 20日均量 * 1.5)
        vol_ratio = float(volume.iloc[-1] / vma20)
        vol_spike = vol_ratio > 1.5

        # --- 條件 4：乖離率控制 (5MA 距離 200MA 不能超過 X%) ---
        dist_from_200 = ((ma5 / ma200) - 1) * 100
        not_too_far = dist_from_200 <= max_dist_pct

        if was_below_200 and is_above_200 and ma_perfect_alignment and vol_spike and not_too_far:
            return {
                "代碼": ticker.split('.')[0],
                "名稱": name,
                "現價": round(float(curr_price), 2),
                "量增倍數": round(vol_ratio, 2),
                "離年線距離%": round(dist_from_200, 2),
                "5MA": round(float(ma5), 2),
                "200MA": round(float(ma200), 2),
                "市場": row['market']
            }
    except:
        return None
    return None

# ----------------------------------------------------------------
# 4. Streamlit 介面
# ----------------------------------------------------------------
st.title("🛡️ 倉鼠量化戰情室：低乖離起漲版")
st.markdown("""
**策略目標：捕捉「年線起跳」且「尚未噴遠」的優質標的**
- **核心排列：** 5MA > 10MA > 20MA > 200MA
- **安全濾網：** 5MA 離 200MA 距離需在限制內
""")

df_all = get_taiwan_stock_list()
st.sidebar.header("⚙️ 掃描參數設定")
max_dist = st.sidebar.slider("最大乖離門檻 (5MA/200MA %)", 2.0, 15.0, 10.0)
limit = st.sidebar.slider("掃描數量", 100, len(df_all), 500)
workers = st.sidebar.slider("加速執行緒", 5, 20, 15)

if st.button(f"🚀 開始全市場戰情掃描"):
    target_stocks = df_all.head(limit).to_dict('records')
    results = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        # 將參數傳入 logic 函數
        future_to_stock = {executor.submit(scan_stock_logic, s, max_dist): s for s in target_stocks}
        for i, future in enumerate(as_completed(future_to_stock)):
            res = future.result()
            if res: results.append(res)
            if (i + 1) % 10 == 0 or (i + 1) == len(target_stocks):
                progress_bar.progress((i + 1) / len(target_stocks))
                status_text.text(f"🔍 掃描中... {i + 1} / {len(target_stocks)} (已找到 {len(results)} 檔)")

    duration = round(time.time() - start_time, 1)
    status_text.success(f"✅ 掃描完成！耗時 {duration} 秒")

    if results:
        st.balloons()
        final_df = pd.DataFrame(results).sort_values("離年線距離%")
        st.subheader(f"🔥 符合條件的潛力標的 ({len(results)} 檔)")
        st.dataframe(final_df, use_container_width=True, hide_index=True)
        
        csv = final_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 下載篩選清單", data=csv, file_name=f"hamster_low_bias_{time.strftime('%Y%m%d')}.csv")
    else:
        st.warning(f"☹️ 目前範圍內查無符合條件標的（5MA 離年線 {max_dist}% 以內）。")
