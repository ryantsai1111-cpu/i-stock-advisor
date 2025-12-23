import streamlit as st
import yfinance as yf
import requests
import pandas as pd
import datetime
import io
import re
from bs4 import BeautifulSoup

# ==========================================
# ⚙️ 網頁設定區
# ==========================================
st.set_page_config(page_title="帥哥城 AI 投顧", page_icon="😎")

st.title("😎 帥哥城 AI 投顧 (網頁版)")
st.write("👉 輸入股票代碼，AI 幫你從技術面、籌碼面、財報面進行健檢。")

# ==========================================
# 🕵️‍♂️ 數據抓取模組
# ==========================================

def get_yahoo_web_data(stock_id):
    try:
        url = f"https://tw.stock.yahoo.com/quote/{stock_id}"
        headers = { "User-Agent": "Mozilla/5.0" }
        r = requests.get(url, headers=headers)
        soup = BeautifulSoup(r.text, 'html.parser')
        data = {}

        try:
            title = soup.title.text
            match = re.search(r'^(.+?)\(', title)
            data['Name'] = match.group(1).strip() if match else stock_id
        except: data['Name'] = stock_id

        def find_val(keyword):
            try:
                for item in soup.find_all('li'):
                    if keyword in item.text:
                        # ✅ 強制抓取數字，修復河流圖問題
                        match = re.search(r'(-?\d+\.\d+|-?\d+)', item.text)
                        if match: return match.group(0)
            except: pass
            return "N/A"

        data['PE'] = find_val("本益比")
        data['PB'] = find_val("股價淨值比")
        data['Yield'] = find_val("殖利率")
        if data['Yield'] == "N/A": data['Yield'] = find_val("現金殖利率")

        return data
    except: return {'Name': stock_id, 'PE': 'N/A', 'PB': 'N/A', 'Yield': 'N/A'}

def get_mops_insider(stock_id):
    try:
        clean_id = stock_id.replace(".TW", "").replace(".TWO", "")
        url = "https://mopsov.twse.com.tw/mops/web/ajax_t146sb05"
        now = datetime.datetime.now()
        year, month = now.year - 1911, now.month - 1
        if month == 0: month = 12; year -= 1

        payload = {'encodeURIComponent': '1', 'step': '1', 'firstin': '1', 'off': '1', 'co_id': clean_id, 'year': str(year), 'month': str(month)}
        r = requests.post(url, data=payload, headers={'User-Agent': 'Mozilla/5.0'})
        dfs = pd.read_html(io.StringIO(r.text))
        for df in dfs:
            df.columns = df.columns.astype(str)
            if '全體董監事持股合計' in df.to_string():
                val = df.iloc[-1].astype(str).str.extract(r'(\d+\.?\d*)').dropna().iloc[-1, 0]
                return float(val)
    except: return None

def get_chips_yahoo_api(stock_id):
    try:
        url = f"https://tw.stock.yahoo.com/_td-stock/api/resource/StockServices.3MajorTrade:K?symbol={stock_id}"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
        data = r.json()
        if 'data' in data and 'list' in data['data'] and len(data['data']['list']) > 0:
            latest = data['data']['list'][0]
            return {
                'foreign': int(latest.get('foreignDiff', 0)) // 1000,
                'trust': int(latest.get('investmentTrustDiff', 0)) // 1000,
                'dealer': int(latest.get('dealerDiff', 0)) // 1000
            }
    except: return None

def calculate_technicals(df):
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    return df

def generate_report(stock_id):
    stock = yf.Ticker(stock_id)
    df = stock.history(period="1y")
    if df.empty: return None

    df = calculate_technicals(df)
    today = df.iloc[-1]
    price = today['Close']
    info = stock.info

    chips = get_chips_yahoo_api(stock_id)
    insider = get_mops_insider(stock_id)
    web_data = get_yahoo_web_data(stock_id)

    score = 50
    reasons = []

    # ✅ 修復了這裡的語法錯誤 (加上了冒號與完整條件)
    if price > today['MA20']: 
        score += 10
        reasons.append("站上月線 (短多)")
    else: 
        score -= 10
        reasons.append("跌破月線 (短空)")

    if price > today['MA60']: 
        score += 10
        reasons.append("站穩季線 (長多)")
    else: 
        score -= 10

    if today['MACD'] > today['Signal']: score += 5
    if today['RSI'] < 25: 
        score += 10
        reasons.append("RSI超賣 (醞釀反彈)")

    chip_msg = "數據不足"
    if chips:
        if chips['foreign'] > 0 and chips['trust'] > 0: score += 20; chip_msg = "🔥 土洋合一 (強力買進)"
        elif chips['foreign'] < 0 and chips['trust'] < 0: score -= 20; chip_msg = "❄️ 法人棄守 (賣壓重)"
        elif chips['trust'] > 0: score += 10; chip_msg = "🛡️ 投信認養"
        else: chip_msg = "⚖️ 土洋對作"

    score = max(0, min(100, score))

    if score >= 75: verdict = "🟢 強力買進"; color = "green"
    elif score >= 55: verdict = "🟡 持有/中性"; color = "orange"
    elif score >= 40: verdict = "🟠 觀望"; color = "brown"
    else: verdict = "🔴 賣出/避開"; color = "red"

    return {
        "name": web_data.get('Name', stock_id),
        "price": price,
        "score": score,
        "verdict": verdict,
        "color": color,
        "chip_msg": chip_msg,
        "chips": chips,
        "insider": insider,
        "web_data": web_data,
        "today": today,
        "reasons": reasons
    }

# ==========================================
# 🖥️ UI 介面互動區
# ==========================================
user_input = st.text_input("請輸入股票代碼 (例如: 2330)", "")

if st.button("開始分析"):
    if not user_input:
        st.warning("請輸入代碼！")
    else:
        stock_code = user_input.strip()
        if stock_code.isdigit(): stock_code += ".TW"

        with st.spinner(f"正在分析 {stock_code}，請稍等..."):
            data = generate_report(stock_code)

        if data:
            st.markdown(f"## {data['name']} ({stock_code})")
            st.markdown(f"### 🏆 綜合評分：{data['score']} 分")
            st.markdown(f"### 🚦 判決：:{data['color']}[{data['verdict']}]")
            st.divider()
            col1, col2 = st.columns(2)
            with col1:
                st.info("📊 **技術面**")
                st.write(f"現價：{data['price']:.1f}")
                st.write(f"月線：{data['today']['MA20']:.1f}")
                st.write(f"RSI：{data['today']['RSI']:.1f}")
            with col2:
                st.success("💰 **基本/籌碼面**")
                st.write(f"本益比：{data['web_data']['PE']}")
                st.write(f"殖利率：{data['web_data']['Yield']}%")
                st.write(f"董監持股：{data['insider']}%")
            st.divider()
            st.write(f"**主力動向**：{data['chip_msg']}")
            if data['chips']:
                st.write(f"外資: {data['chips']['foreign']} | 投信: {data['chips']['trust']} | 自營: {data['chips']['dealer']}")
            st.divider()
            st.write("**📝 評分理由：**")
            for r in data['reasons']:
                st.write(f"- {r}")
        else:
            st.error("查無資料，請檢查代碼是否正確。")