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

# 自定義 CSS 美化進度條與介面
st.markdown("""
    <style>
    .stProgress > div > div > div > div { background-color: #f63366; }
    .reportview-container .main { color: #2c3e50; }
    </style>
    """, unsafe_allow_html=True)

# ----------------------------------------------------------------
# 2. 自動抓取全台股清單 (Cache 一天)
# ----------------------------------------------------------------
@st.cache_data(ttl=86400)
def get_taiwan_stock_list():
    urls = {
        "上市": "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2",
        "上櫃": "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"
    }
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    all_stocks = []
    
    for market, url in urls.items():
        try:
            # 使用 verify=False 解決 SSL 問題
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
        except Exception as e:
            st.error(f"無法獲取{market}資料清單: {e}")
            
    return pd.DataFrame(all_stocks)

# ----------------------------------------------------------------
# 3. 方案 A 核心邏輯函數 (多執行緒運行)
# ----------------------------------------------------------------
def scan_stock_logic(row):
    ticker = row['ticker']
    name = row['name']
    try:
        # 下載足以計算 200MA 的資料
        df = yf.download(ticker, period="14mo", progress=False, threads=False)
        if len(df) < 210: return None

        # 處理 yfinance 可能產生的多層索引並提取 Series
        close = df['Close'].squeeze()
        volume = df['Volume'].squeeze()
        
        # 計算均線
        ma5 = close.rolling(5).mean()
        ma10 = close.rolling(10).mean()
        ma20 = close.rolling(20).mean()
        ma200 = close.rolling(200).mean()
        vma20 = volume.rolling(20).mean()

        # 【方案 A】邏輯判斷
        curr_price = close.iloc[-1]
        curr_ma200 = ma200.iloc[-1]
        
        # 1. 回測/突破檢測：過去 5 天(不含今日)曾跌破 200MA，且今天站在 200MA 之上
        prev_5_days_close = close.iloc[-6:-1]
        prev_5_days_ma200 = ma200.iloc[-6:-1]
        was_below_200 = (prev_5_days_close < prev_5_days_ma200).any()
        is_above_200 = curr_price > curr_ma200

        # 2. 均線多頭：5 > 10 > 20
        ma_aligned = ma5.iloc[-1] > ma10.iloc[-1] > ma20.iloc[-1]
        
        # 3. 成交量爆發：今日量 > 20日均量 * 1.5
        vol_ratio = float(volume.iloc[-1] / vma20.iloc[-1])
        vol_spike = vol_ratio > 1.5

        if was_below_200 and is_above_200 and ma_aligned and vol_spike:
            return {
                "代碼": ticker.split('.')[0],
                "名稱": name,
                "現價": round(float(curr_price), 2),
                "量增倍數": round(vol_ratio, 2),
                "200MA": round(float(curr_ma200), 2),
                "市場": row['market']
            }
    except:
        return None
    return None

# ----------------------------------------------------------------
# 4. Streamlit 介面佈局
# ----------------------------------------------------------------
st.title("🛡️ 倉鼠量化戰情室：方案 A 極速搜尋器")
st.markdown("> **策略邏輯：** 過去 5 天曾跌破 200MA (回測) + 今日重新站上 + 均線多頭 + 成交量爆發。")

# 側邊欄控制項
df_all = get_taiwan_stock_list()
st.sidebar.header("⚙️ 掃描參數設定")
market_filter = st.sidebar.multiselect("選擇市場", ["上市", "上櫃"], default=["上市", "上櫃"])
limit = st.sidebar.slider("掃描數量", 100, len(df_all), 300)
workers = st.sidebar.slider("並行加速數 (執行緒)", 5, 20, 10)

# 執行掃描
if st.button(f"🚀 開始掃描前 {limit} 檔符合條件標的"):
    # 篩選市場與數量
    target_stocks = df_all[df_all['market'].isin(market_filter)].head(limit).to_dict('records')
    results = []
    
    # 建立進度條與顯示文字
    progress_bar = st.progress(0)
    status_text = st.empty()
    start_time = time.time()

    # 使用多執行緒 ThreadPoolExecutor 加速
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_stock = {executor.submit(scan_stock_logic, s): s for s in target_stocks}
        
        for i, future in enumerate(as_completed(future_to_stock)):
            res = future.result()
            if res:
                results.append(res)
            
            # 每掃描 10 檔更新一次進度，提升介面流暢度
            if (i + 1) % 10 == 0 or (i + 1) == len(target_stocks):
                progress_bar.progress((i + 1) / len(target_stocks))
                status_text.text(f"🔍 掃描進度：{i + 1} / {len(target_stocks)} (已找到 {len(results)} 檔)")

    duration = round(time.time() - start_time, 1)
    status_text.success(f"✅ 掃描完成！總耗時：{duration} 秒")

    # 顯示結果
    if results:
        st.balloons()
        st.subheader(f"🔥 強力動能觀察清單 ({len(results)} 檔)")
        final_df = pd.DataFrame(results).sort_values("量增倍數", ascending=False)
        st.dataframe(final_df, use_container_width=True, hide_index=True)
        
        # 導出 CSV 功能
        csv = final_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 下載戰情報表", data=csv, file_name=f"hamster_A_report_{time.strftime('%Y%m%d')}.csv")
    else:
        st.warning("☹️ 當前掃描範圍內，查無符合「方案 A」回測突破條件的標的。")
