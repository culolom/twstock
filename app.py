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
st.set_page_config(page_title="倉鼠量化戰情室-電子版", layout="wide", page_icon="🐹")

# --- 1. 抓取當沖量前 20 名 ---
def get_top_20_daytrade():
    """抓取今日當沖成交量排行"""
    try:
        url = "https://www.twse.com.tw/exchangeReport/TWTB4U?response=json"
        res = requests.get(url, verify=False, timeout=10)
        data = res.json()
        if 'data' not in data: return []
        df = pd.DataFrame(data['data'], columns=data['fields'])
        df['成交股數'] = df['成交股數'].str.replace(',', '').astype(float)
        return df.sort_values(by='成交股數', ascending=False).head(20)['證券代號'].tolist()
    except: return []

# --- 2. 抓取全台股清單並限定「電子族群」 ---
@st.cache_data(ttl=86400)
def get_electronics_list():
    """從證交所抓取清單，並嚴格篩選電子相關產業"""
    urls = {"上市": "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", 
            "上櫃": "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"}
    # 定義電子相關產業關鍵字
    elec_sectors = ['半導體業', '電腦及週邊設備業', '光電業', '通訊網路業', 
                    '電子零組件業', '電子通路業', '資訊服務業', '其他電子業']
    all_elec_stocks = []
    
    for market, url in urls.items():
        try:
            response = requests.get(url, verify=False)
            response.encoding = 'big5'
            soup = BeautifulSoup(response.text, 'html.parser')
            table = soup.find('table', {'class': 'h4'})
            if not table: continue
            
            for row in table.find_all('tr')[2:]:
                cols = row.find_all('td')
                if len(cols) >= 5:
                    sector = cols[4].text.strip()
                    # 僅保留電子相關產業
                    if sector in elec_sectors:
                        text = cols[0].text.strip().split('\u3000')
                        if len(text) == 2 and len(text[0]) == 4:
                            all_elec_stocks.append({
                                "ticker": f"{text[0]}{'.TW' if market=='上市' else '.TWO'}",
                                "name": text[1], "id": text[0], "sector": sector
                            })
        except: pass
    return pd.DataFrame(all_elec_stocks)

# --- 3. 核心邏輯：矽格/金居/電子飆股模式 ---
def scan_logic(row, top_20_list, max_dist, only_hot):
    ticker = row['ticker']
    if only_hot and row['id'] not in top_20_list: return None

    try:
        # 使用 auto_adjust=False 確保數值與看盤軟體同步
        df = yf.download(ticker, period="15mo", progress=False, threads=False, auto_adjust=False)
        if len(df) < 210: return None

        close = df['Close'].squeeze()
        volume = df['Volume'].squeeze()
        
        # 指標計算
        ma5, ma10, ma20, ma200 = [close.rolling(w).mean().iloc[-1] for w in [5, 10, 20, 200]]
        vma20 = volume.rolling(20).mean().iloc[-1]

        # 糾結度計算：(Max/Min - 1) * 100
        ma_group = [ma5, ma10, ma20, ma200]
        squeeze_ratio = (max(ma_group) / min(ma_group) - 1) * 100
        dist_200 = ((ma5 / ma200) - 1) * 100

        # 終極條件：5>10>20>200 + 糾結 + 爆量
        if (ma5 > ma10 > ma20 > ma200 and volume.iloc[-1] > vma20 * 1.5 and 
            dist_200 <= max_dist and close.iloc[-1] > ma5):
            return {
                "代碼": row['id'], "名稱": row['name'], "現價": round(float(close.iloc[-1]), 2),
                "量增倍數": round(float(volume.iloc[-1] / vma20), 2),
                "離年線%": round(dist_200, 2), "糾結度%": round(squeeze_ratio, 2),
                "產業": row['sector'], "當沖熱度": "🔥" if row['id'] in top_20_list else "普通"
            }
    except: return None
    return None

# --- 4. 前端展示 ---
st.title("🐹 倉鼠戰情室：電子動能專用版")
st.markdown("針對**電子股**掃描：四線排列 + 均線糾結 + 爆量突破。")

df_elec = get_electronics_list()
st.sidebar.header("⚙️ 篩選設定")
st.sidebar.info(f"當前電子股池：{len(df_elec)} 檔")
only_hot = st.sidebar.checkbox("僅看當沖熱門前 20 名 (飆股選法)", value=False)
max_dist = st.sidebar.slider("5MA/200MA 最大乖離 %", 2.0, 15.0, 10.0)
workers = st.sidebar.slider("並行執行緒數", 5, 20, 15)

if st.button("🚀 執行電子全市場戰情掃描"):
    top_20 = get_top_20_daytrade()
    target_stocks = df_elec.to_dict('records')
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
                status.text(f"掃描中: {i+1}/{len(target_stocks)} (已找到 {len(results)} 檔符合條件)")

    st.success(f"✅ 掃描完成！耗時 {round(time.time()-start_time, 1)} 秒")

    if results:
        st.balloons()
        final_df = pd.DataFrame(results).sort_values("量增倍數", ascending=False)
        st.subheader(f"🔥 電子動能強勢清單 ({len(results)} 檔)")
        st.dataframe(final_df, use_container_width=True, hide_index=True)
    else:
        st.warning("☹️ 目前電子股中查無符合條件之標的。")
