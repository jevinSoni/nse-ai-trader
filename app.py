import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import sqlite3

st.set_page_config(page_title="NSE Algo Lab & Stock Inspector", layout="wide")
st.title("📈 NSE Algo Lab: Pure Quant vs. AI-Hybrid Tracker")

DB_FILE = "paper_trades.db"

def load_all_data():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS strategy_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, strategy TEXT, symbol TEXT, direction TEXT,
            entry_price REAL, quantity INTEGER, stop_loss REAL, target REAL, status TEXT,
            entry_time TEXT, exit_price REAL, exit_time TEXT, pnl REAL, exit_reason TEXT, ai_note TEXT
        )
    """)
    c.execute("CREATE TABLE IF NOT EXISTS strategy_accounts (strategy TEXT PRIMARY KEY, cash REAL)")
    c.execute("INSERT OR IGNORE INTO strategy_accounts VALUES ('PURE_QUANT', 100000.0)")
    c.execute("INSERT OR IGNORE INTO strategy_accounts VALUES ('AI_HYBRID', 100000.0)")
    c.execute("""
        CREATE TABLE IF NOT EXISTS ai_rejections (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, direction TEXT, price REAL, time TEXT, ai_reason TEXT
        )
    """)
    conn.commit()

    open_df = pd.read_sql_query("SELECT * FROM strategy_trades WHERE status = 'OPEN'", conn)
    closed_df = pd.read_sql_query("SELECT * FROM strategy_trades WHERE status = 'CLOSED'", conn)
    rejections_df = pd.read_sql_query("SELECT * FROM ai_rejections ORDER BY id DESC LIMIT 30", conn)
    conn.close()
    return open_df, closed_df, rejections_df

open_trades, closed_trades, rejections_df = load_all_data()

def compute_metrics(df_subset):
    if df_subset.empty:
        return {"Trades": 0, "Win Rate %": 0.0, "Net P&L (₹)": 0.0, "Profit Factor": 0.0, "Avg Win (₹)": 0.0, "Avg Loss (₹)": 0.0}
    total = len(df_subset)
    wins = df_subset[df_subset["pnl"] > 0]
    losses = df_subset[df_subset["pnl"] <= 0]
    win_rate = (len(wins) / total) * 100
    g_prof = wins["pnl"].sum() if not wins.empty else 0.0
    g_loss = abs(losses["pnl"].sum()) if not losses.empty else 0.0
    pf = round(g_prof / g_loss, 2) if g_loss > 0 else (g_prof if g_prof > 0 else 1.0)
    return {
        "Trades": total,
        "Win Rate %": round(win_rate, 1),
        "Net P&L (₹)": round(g_prof - g_loss, 2),
        "Profit Factor": pf,
        "Avg Win (₹)": round(wins["pnl"].mean(), 2) if not wins.empty else 0.0,
        "Avg Loss (₹)": round(abs(losses["pnl"].mean()), 2) if not losses.empty else 0.0
    }

tab1, tab2, tab3 = st.tabs(["⚔️ Strategy A/B Battle (Quant vs AI)", "💼 Live Positions & AI Vetoes", "🔍 Universal NSE/BSE Stock Inspector"])

# TAB 1: STRATEGY A/B COMPARISON
with tab1:
    st.subheader("⚔️ Head-to-Head Performance: Pure Math vs. AI-Filtered")
    
    quant_closed = closed_trades[closed_trades["strategy"] == "PURE_QUANT"] if not closed_trades.empty else pd.DataFrame()
    ai_closed = closed_trades[closed_trades["strategy"] == "AI_HYBRID"] if not closed_trades.empty else pd.DataFrame()

    q_m = compute_metrics(quant_closed)
    a_m = compute_metrics(ai_closed)

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("### ⚙️ Strategy 1: `PURE_QUANT` (Math Only)")
        st.caption("Executes on Price > 20 EMA > 50 EMA, RSI 55–75, and Vol Spike >= 1.5x")
        c1, c2, c3 = st.columns(3)
        c1.metric("Win Rate", f"{q_m['Win Rate %']}%", f"{q_m['Trades']} Trades")
        c2.metric("Net P&L", f"₹{q_m['Net P&L (₹)']:,.2f}")
        c3.metric("Profit Factor", f"{q_m['Profit Factor']}x")

    with col_b:
        st.markdown("### 🧠 Strategy 2: `AI_HYBRID` (Math + Gemini Filter)")
        st.caption("Identical math trigger, but Gemini gates entry using news & exhaustion analysis")
        c4, c5, c6 = st.columns(3)
        c4.metric("Win Rate", f"{a_m['Win Rate %']}%", f"{a_m['Trades']} Trades")
        c5.metric("Net P&L", f"₹{a_m['Net P&L (₹)']:,.2f}")
        c6.metric("Profit Factor", f"{a_m['Profit Factor']}x")

    st.divider()
    if not closed_trades.empty:
        closed_trades["Cum_PnL"] = closed_trades.groupby("strategy")["pnl"].cumsum()
        closed_trades["Equity"] = 100000.0 + closed_trades["Cum_PnL"]
        fig_ab = px.line(closed_trades, x="exit_time", y="Equity", color="strategy", markers=True,
                         title="📈 Strategy Equity Curves (Starting Capital: ₹1,00,000 Each)", template="plotly_dark")
        st.plotly_chart(fig_ab, use_container_width=True)
        st.dataframe(closed_trades, use_container_width=True, hide_index=True)
    else:
        st.info("No closed trades recorded yet. Once the cloud bot executes and closes positions, comparative curves will appear here.")

# TAB 2: LIVE POSITIONS & VETOES
with tab2:
    st.subheader("🤖 Active Open Positions Across Both Strategies")
    if not open_trades.empty:
        st.dataframe(open_trades[["id", "strategy", "symbol", "direction", "entry_price", "quantity", "stop_loss", "target", "ai_note", "entry_time"]], use_container_width=True, hide_index=True)
    else:
        st.info("No active open positions.")

    st.divider()
    st.subheader("🛡️ Setups Vetoed (Rejected) by Gemini AI")
    st.caption("Track these rejections to evaluate whether the AI saved capital or missed profitable trends.")
    if not rejections_df.empty:
        st.dataframe(rejections_df, use_container_width=True, hide_index=True)
    else:
        st.write("No trades vetoed by AI yet.")

# TAB 3: UNIVERSAL STOCK INSPECTOR
with tab3:
    st.subheader("🔍 Universal NSE/BSE Stock Inspector")
    ALL_STOCKS_DICT = {
        "BHARTIARTL.NS - Bharti Airtel (NSE)": "BHARTIARTL.NS",
        "RELIANCE.NS - Reliance Industries (NSE)": "RELIANCE.NS",
        "RELIANCE.BO - Reliance Industries (BSE)": "RELIANCE.BO",
        "TCS.NS - Tata Consultancy Services (NSE)": "TCS.NS",
        "HDFCBANK.NS - HDFC Bank (NSE)": "HDFCBANK.NS",
        "ICICIBANK.NS - ICICI Bank (NSE)": "ICICIBANK.NS",
        "INFY.NS - Infosys (NSE)": "INFY.NS",
        "SBIN.NS - State Bank of India (NSE)": "SBIN.NS",
        "ITC.NS - ITC Limited (NSE)": "ITC.NS",
        "LT.NS - Larsen & Toubro (NSE)": "LT.NS",
        "TMPV.NS - Tata Motors Passenger (NSE)": "TMPV.NS",
        "TMCV.NS - Tata Motors Commercial (NSE)": "TMCV.NS",
        "SUZLON.NS - Suzlon Energy (NSE)": "SUZLON.NS",
        "SUZLON.BO - Suzlon Energy (BSE)": "SUZLON.BO",
        "TRENT.NS - Trent Limited (NSE)": "TRENT.NS",
        "ETERNAL.NS - Eternal / Zomato (NSE)": "ETERNAL.NS",
        "^NSEI - Nifty 50 Index": "^NSEI",
        "^NSEBANK - Nifty Bank Index": "^NSEBANK",
        "^BSESN - BSE Sensex Index": "^BSESN"
    }

    col_s1, col_s2 = st.columns([3, 1])
    with col_s1:
        selected_dropdown = st.selectbox("Select or type stock:", options=list(ALL_STOCKS_DICT.keys()), index=0)
        search_symbol = ALL_STOCKS_DICT[selected_dropdown]
    with col_s2:
        timeframe_choice = st.selectbox("Timeframe:", ["15m (Intraday)", "1d (Daily)"])

    manual_input = st.text_input("Or type any NSE/BSE symbol manually (e.g. SUZLON.BO, HAL.NS, PNB.NS):")
    if manual_input.strip():
        clean_input = manual_input.strip().upper()
        if not clean_input.endswith(".NS") and not clean_input.endswith(".BO") and not clean_input.startswith("^"):
            search_symbol = clean_input + ".NS"
        else:
            search_symbol = clean_input

    try:
        interval_val = "15m" if "15m" in timeframe_choice else "1d"
        period_val = "10d" if "15m" in timeframe_choice else "6mo"
        ticker_obj = yf.Ticker(search_symbol)
        df = ticker_obj.history(period=period_val, interval=interval_val)
        
        if not df.empty and len(df) > 5:
            # Daily candles for official daily percentage change and reference levels
            daily_df = ticker_obj.history(period="5d", interval="1d")
            if len(daily_df) >= 2:
                today_bar = daily_df.iloc[-1]
                prev_close = daily_df.iloc[-2]["Close"]
                ltp = today_bar["Close"]
                day_open = today_bar["Open"]
                day_high = today_bar["High"]
                day_low = today_bar["Low"]
                day_vol = int(today_bar["Volume"])
            else:
                latest = df.iloc[-1]
                prev_close = df.iloc[-2]["Close"]
                ltp, day_open, day_high, day_low, day_vol = latest["Close"], latest["Open"], latest["High"], latest["Low"], int(latest["Volume"])

            chg_pct = ((ltp - prev_close) / prev_close) * 100

            m1, m2, m3, m4, m5, m6 = st.columns(6)
            m1.metric("Current Price (LTP)", f"₹{ltp:.2f}", f"{chg_pct:.2f}%")
            m2.metric("Day Open", f"₹{day_open:.2f}")
            m3.metric("Day High", f"₹{day_high:.2f}")
            m4.metric("Day Low", f"₹{day_low:.2f}")
            m5.metric("Day Volume", f"{day_vol:,}")
            m6.metric("Prev Close", f"₹{prev_close:.2f}")

            df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
            df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()

            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.75, 0.25])
            fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"], name="Price"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df["EMA20"], line=dict(color="orange", width=1.5), name="20 EMA"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df["EMA50"], line=dict(color="cyan", width=1.5), name="50 EMA"), row=1, col=1)
            fig.add_trace(go.Bar(x=df.index, y=df["Volume"], name="Volume", marker_color="rgba(100, 150, 250, 0.5)"), row=2, col=1)
            fig.update_layout(height=500, xaxis_rangeslider_visible=False, template="plotly_dark", margin=dict(l=10, r=10, t=30, b=10))
            st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.error(f"Error loading chart: {e}")
