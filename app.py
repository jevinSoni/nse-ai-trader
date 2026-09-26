import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import sqlite3

st.set_page_config(page_title="NSE/BSE Autonomous Trading & Success Analytics", layout="wide")
st.title("📈 NSE & BSE Universal Algo & Performance Dashboard")

DB_FILE = "paper_trades.db"

def get_account_data():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, direction TEXT, entry_price REAL, quantity INTEGER,
            stop_loss REAL, target REAL, status TEXT, entry_time TEXT,
            exit_price REAL, exit_time TEXT, pnl REAL, exit_reason TEXT
        )
    """)
    c.execute("CREATE TABLE IF NOT EXISTS account (id INTEGER PRIMARY KEY, cash REAL)")
    c.execute("INSERT OR IGNORE INTO account (id, cash) VALUES (1, 100000.0)")
    conn.commit()
    
    try:
        cash = c.execute("SELECT cash FROM account WHERE id = 1").fetchone()[0]
    except Exception:
        cash = 100000.0

    try:
        open_df = pd.read_sql_query("SELECT * FROM trades WHERE status = 'OPEN'", conn)
    except Exception:
        open_df = pd.DataFrame()

    try:
        closed_df = pd.read_sql_query("SELECT * FROM trades WHERE status = 'CLOSED'", conn)
    except Exception:
        closed_df = pd.DataFrame()
        
    conn.close()
    return cash, open_df, closed_df

cash, open_trades, closed_trades = get_account_data()

tab1, tab2, tab3 = st.tabs(["📊 Success Ratio & Analytics", "💼 Live Bot Positions", "🔍 Universal NSE/BSE Stock Inspector"])

# TAB 1: SUCCESS RATIO & ANALYTICS
with tab1:
    st.subheader("🎯 Quantitative Strategy Success Metrics")
    if closed_trades.empty:
        st.info("No closed trades yet. Once the cloud bot executes and closes trades, your win rate, profit factor, and equity curve will appear here automatically.")
    else:
        total_trades = len(closed_trades)
        wins = closed_trades[closed_trades["pnl"] > 0]
        losses = closed_trades[closed_trades["pnl"] <= 0]
        
        win_count, loss_count = len(wins), len(losses)
        win_rate = (win_count / total_trades) * 100 if total_trades > 0 else 0.0
        
        gross_profit = wins["pnl"].sum() if not wins.empty else 0.0
        gross_loss = abs(losses["pnl"].sum()) if not losses.empty else 0.0
        net_pnl = gross_profit - gross_loss
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 1.0)
        
        avg_win = wins["pnl"].mean() if win_count > 0 else 0.0
        avg_loss = abs(losses["pnl"].mean()) if loss_count > 0 else 0.0

        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Win Rate %", f"{win_rate:.1f}%", f"{win_count}W - {loss_count}L")
        k2.metric("Net Realized P&L", f"₹{net_pnl:,.2f}", f"{(net_pnl / 100000.0) * 100:.2f}% Return")
        k3.metric("Profit Factor", f"{profit_factor}x")
        k4.metric("Avg Win", f"₹{avg_win:,.2f}")
        k5.metric("Avg Loss", f"₹{avg_loss:,.2f}")

        st.divider()

        if "pnl" in closed_trades.columns and not closed_trades.empty:
            closed_trades["Cumulative_PnL"] = closed_trades["pnl"].cumsum()
            closed_trades["Portfolio_Equity"] = 100000.0 + closed_trades["Cumulative_PnL"]

            fig_equity = px.line(closed_trades, x="exit_time", y="Portfolio_Equity", title="📈 Virtual Account Equity Growth", markers=True, template="plotly_dark")
            fig_equity.update_layout(height=400, yaxis_title="Capital (₹)", xaxis_title="Exit Time")
            st.plotly_chart(fig_equity, use_container_width=True)

        st.subheader("📜 Closed Trades History")
        st.dataframe(closed_trades, use_container_width=True, hide_index=True)

# TAB 2: LIVE BOT POSITIONS
with tab2:
    st.subheader("🤖 Active Cloud Bot Positions")
    c1, c2 = st.columns(2)
    c1.metric("Available Cash", f"₹{cash:,.2f}")
    c2.metric("Active Open Trades", f"{len(open_trades)} / 5 Max")

    if not open_trades.empty:
        live_rows = []
        for _, r in open_trades.iterrows():
            sym = r["symbol"]
            try:
                df_sym = yf.Ticker(sym).history(period="1d", interval="15m")
                ltp = round(df_sym.iloc[-1]["Close"], 2) if not df_sym.empty else r["entry_price"]
            except Exception:
                ltp = r["entry_price"]
                
            pnl = (ltp - r["entry_price"]) * r["quantity"] if r["direction"] == "BUY" else (r["entry_price"] - ltp) * r["quantity"]

            live_rows.append({
                "ID": r["id"], "Symbol": sym, "Type": r["direction"], "Qty": r["quantity"],
                "Entry Price": f"₹{r['entry_price']:.2f}", "LTP": f"₹{ltp:.2f}",
                "Stop Loss": f"₹{r['stop_loss']:.2f}", "Target": f"₹{r['target']:.2f}",
                "Unrealized P&L (₹)": round(pnl, 2)
            })
        st.dataframe(pd.DataFrame(live_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No open positions right now. The cloud bot is standing by.")

# TAB 3: UNIVERSAL NSE/BSE STOCK INSPECTOR
with tab3:
    st.subheader("🔍 Search Any NSE or BSE Stock")
    
    # Comprehensive dictionary covering prominent NSE and BSE equities
    ALL_STOCKS_DICT = {
        "RELIANCE.NS - Reliance Industries (NSE)": "RELIANCE.NS",
        "RELIANCE.BO - Reliance Industries (BSE)": "RELIANCE.BO",
        "TCS.NS - Tata Consultancy Services (NSE)": "TCS.NS",
        "TCS.BO - Tata Consultancy Services (BSE)": "TCS.BO",
        "HDFCBANK.NS - HDFC Bank (NSE)": "HDFCBANK.NS",
        "HDFCBANK.BO - HDFC Bank (BSE)": "HDFCBANK.BO",
        "ICICIBANK.NS - ICICI Bank (NSE)": "ICICIBANK.NS",
        "INFY.NS - Infosys (NSE)": "INFY.NS",
        "SBIN.NS - State Bank of India (NSE)": "SBIN.NS",
        "BHARTIARTL.NS - Bharti Airtel (NSE)": "BHARTIARTL.NS",
        "ITC.NS - ITC Limited (NSE)": "ITC.NS",
        "LT.NS - Larsen & Toubro (NSE)": "LT.NS",
        "TMPV.NS - Tata Motors Passenger (NSE)": "TMPV.NS",
        "TMCV.NS - Tata Motors Commercial (NSE)": "TMCV.NS",
        "AXISBANK.NS - Axis Bank (NSE)": "AXISBANK.NS",
        "SUNPHARMA.NS - Sun Pharma (NSE)": "SUNPHARMA.NS",
        "MARUTI.NS - Maruti Suzuki (NSE)": "MARUTI.NS",
        "NTPC.NS - NTPC Limited (NSE)": "NTPC.NS",
        "TITAN.NS - Titan Company (NSE)": "TITAN.NS",
        "BAJFINANCE.NS - Bajaj Finance (NSE)": "BAJFINANCE.NS",
        "TRENT.NS - Trent Limited (NSE)": "TRENT.NS",
        "TATASTEEL.NS - Tata Steel (NSE)": "TATASTEEL.NS",
        "ADANIENT.NS - Adani Enterprises (NSE)": "ADANIENT.NS",
        "ETERNAL.NS - Eternal / Zomato (NSE)": "ETERNAL.NS",
        "HAL.NS - Hindustan Aeronautics (NSE)": "HAL.NS",
        "BEL.NS - Bharat Electronics (NSE)": "BEL.NS",
        "M&M.NS - Mahindra & Mahindra (NSE)": "M&M.NS",
        "POWERGRID.NS - Power Grid Corp (NSE)": "POWERGRID.NS",
        "SUZLON.NS - Suzlon Energy (NSE)": "SUZLON.NS",
        "SUZLON.BO - Suzlon Energy (BSE)": "SUZLON.BO",
        "IRCTC.NS - IRCTC (NSE)": "IRCTC.NS",
        "ZOMATO.NS - Zomato (NSE)": "ZOMATO.NS",
        "NYKAA.NS - Nykaa (NSE)": "NYKAA.NS",
        "PAYTM.NS - Paytm (NSE)": "PAYTM.NS",
        "IDEA.NS - Vodafone Idea (NSE)": "IDEA.NS",
        "YESBANK.NS - Yes Bank (NSE)": "YESBANK.NS",
        "PNB.NS - Punjab National Bank (NSE)": "PNB.NS",
        "BANKBARODA.NS - Bank of Baroda (NSE)": "BANKBARODA.NS",
        "WIPRO.NS - Wipro (NSE)": "WIPRO.NS",
        "HCLTECH.NS - HCL Technologies (NSE)": "HCLTECH.NS",
        "ADANIGREEN.NS - Adani Green Energy (NSE)": "ADANIGREEN.NS",
        "ADANIPORTS.NS - Adani Ports (NSE)": "ADANIPORTS.NS",
        "ASIANPAINT.NS - Asian Paints (NSE)": "ASIANPAINT.NS",
        "COALINDIA.NS - Coal India (NSE)": "COALINDIA.NS",
        "DMART.NS - Avenue Supermarts (DMart) (NSE)": "DMART.NS",
        "GRASIM.NS - Grasim Industries (NSE)": "GRASIM.NS",
        "HINDALCO.NS - Hindalco Industries (NSE)": "HINDALCO.NS",
        "JSWSTEEL.NS - JSW Steel (NSE)": "JSWSTEEL.NS",
        "KOTAKBANK.NS - Kotak Mahindra Bank (NSE)": "KOTAKBANK.NS",
        "LTIM.NS - LTIMindtree (NSE)": "LTIM.NS",
        "NESTLEIND.NS - Nestle India (NSE)": "NESTLEIND.NS",
        "ONGC.NS - ONGC (NSE)": "ONGC.NS",
        "TECHM.NS - Tech Mahindra (NSE)": "TECHM.NS",
        "ULTRACEMCO.NS - UltraTech Cement (NSE)": "ULTRACEMCO.NS",
        "^NSEI - Nifty 50 Index": "^NSEI",
        "^NSEBANK - Nifty Bank Index": "^NSEBANK",
        "^BSESN - BSE Sensex Index": "^BSESN"
    }

    col_s1, col_s2 = st.columns([3, 1])
    with col_s1:
        selected_dropdown = st.selectbox(
            "Select or start typing any NSE/BSE stock name:",
            options=list(ALL_STOCKS_DICT.keys()),
            index=0
        )
        search_symbol = ALL_STOCKS_DICT[selected_dropdown]
        
    with col_s2:
        timeframe_choice = st.selectbox("Timeframe:", ["15m (Intraday)", "1d (Daily)"])

    # Universal manual input: handles any stock symbol from NSE or BSE directly
    manual_input = st.text_input("Or type any custom ticker manually (e.g. SUZLON, TCS, ZOMATO):", placeholder="Type symbol here...")
    if manual_input.strip():
        clean_input = manual_input.strip().upper()
        if not clean_input.endswith(".NS") and not clean_input.endswith(".BO") and not clean_input.startswith("^"):
            # Automatically check if user wants BSE (.BO) or default to NSE (.NS)
            search_symbol = clean_input + ".NS"
        else:
            search_symbol = clean_input

    try:
        interval_val = "15m" if "15m" in timeframe_choice else "1d"
        period_val = "10d" if "15m" in timeframe_choice else "6mo"
        
        df = yf.Ticker(search_symbol).history(period=period_val, interval=interval_val)
        if df.empty and not search_symbol.endswith(".BO"):
            # Auto-fallback: if NSE fails, try BSE (.BO)
            alt_symbol = search_symbol.replace(".NS", ".BO")
            df = yf.Ticker(alt_symbol).history(period=period_val, interval=interval_val)
            if not df.empty:
                search_symbol = alt_symbol

        if not df.empty and len(df) > 10:
            df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
            df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()

            st.success(f"Successfully loaded data for **{search_symbol}**")

            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.75, 0.25])
            fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"], name="Price"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df["EMA20"], line=dict(color="orange", width=1.5), name="20 EMA"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df["EMA50"], line=dict(color="cyan", width=1.5), name="50 EMA"), row=1, col=1)
            fig.add_trace(go.Bar(x=df.index, y=df["Volume"], name="Volume", marker_color="rgba(100, 150, 250, 0.5)"), row=2, col=1)
            fig.update_layout(height=500, xaxis_rangeslider_visible=False, template="plotly_dark", margin=dict(l=10, r=10, t=30, b=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.error(f"Could not load data for '{search_symbol}'. Please verify the symbol.")
    except Exception as e:
        st.error(f"Error loading chart: {e}")
