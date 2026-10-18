import os
import sqlite3
from datetime import datetime
from google import genai
import pandas as pd
import pytz
import requests
import yfinance as yf

# Environment Secrets
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DB_FILE = "paper_trades.db"

# Initialize Gemini Client
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# Top High-Beta Liquid Intraday Stock Universe
WATCHLIST = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "BHARTIARTL.NS",
    "SBIN.NS", "INFY.NS", "ITC.NS", "LT.NS", "BAJFINANCE.NS", "HAL.NS",
    "TRENT.NS", "TATAMOTORS.NS", "M&M.NS"
]

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram tokens not found in environment.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        res = requests.post(url, json=payload, timeout=8)
        print(f"Telegram response: {res.status_code}")
    except Exception as e:
        print(f"Telegram error: {e}")

def get_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS strategy_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, strategy TEXT, symbol TEXT, direction TEXT,
            entry_price REAL, quantity INTEGER, stop_loss REAL, target REAL, status TEXT,
            entry_time TEXT, exit_price REAL, exit_time TEXT, pnl REAL, exit_reason TEXT, ai_note TEXT
        )
    """)
    conn.commit()
    return conn

def get_live_news_summary(symbol):
    """Agent 1: News Analyst scrapes recent headlines for the ticker."""
    try:
        ticker = yf.Ticker(symbol)
        news_items = ticker.news
        if not news_items:
            return "No breaking ticker-specific news reported."
        headlines = [f"- {item.get('title', '')}" for item in news_items[:3] if item.get('title')]
        return "\n".join(headlines) if headlines else "No major headline catalysts found."
    except Exception:
        return "Market news feed temporarily unavailable."

def run_ai_boardroom_debate(symbol, direction, entry_p, df_context):
    """Summons the 4-agent committee: News Analyst, Bull, Bear, and CRO."""
    if not client:
        return True, "No Gemini API Key provided. Trade passed by default."

    news_data = get_live_news_summary(symbol)
    prompt = f"""
You are the Investment Committee of a proprietary intraday quant hedge fund.
A technical breakout setup has just triggered on the 15-minute chart:

TICKER: {symbol}
PROPOSED DIRECTION: {direction}
ENTRY PRICE: ₹{entry_p}

TECHNICAL DATA:
{df_context}

RECENT NEWS / CATALYSTS:
{news_data}

Conduct an aggressive multi-agent debate:
1. BULL AGENT: Make the case for momentum and buying/shorting with the trend.
2. BEAR AGENT: Act as Devil's Advocate. Look for bull/bear traps, divergence, overbought/oversold levels, and overhead resistance.
3. CHIEF RISK OFFICER (CRO): Cut through the bias and issue the final ruling.

STRICT INSTRUCTION: Your output MUST follow this exact template:
[BULL]: <1 sharp punchy sentence>
[BEAR]: <1 sharp punchy sentence>
[CRO_DECISION]: <APPROVED or VETOED>
[CRO_RATIONALE]: <1 clear summary sentence explaining the ruling>
"""
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        text = response.text.strip()
        is_approved = "[CRO_DECISION]: APPROVED" in text.upper()
        return is_approved, text
    except Exception as e:
        print(f"Boardroom debate failed: {e}")
        return False, f"Debate execution error: {e}"

def audit_open_positions(conn, current_time_str, is_eod):
    """Closes trades hitting Target/SL or squares off at 3:15 PM IST."""
    c = conn.cursor()
    c.execute("SELECT id, strategy, symbol, direction, entry_price, quantity, stop_loss, target FROM strategy_trades WHERE status = 'OPEN'")
    open_positions = c.fetchall()

    for pos_id, strat, sym, direction, entry_p, qty, sl, tgt in open_positions:
        try:
            hist = yf.Ticker(sym).history(period="1d", interval="1m")
            if hist.empty:
                continue
            ltp = float(hist['Close'].iloc[-1])

            hit_target = ltp >= tgt if direction == "BUY" else ltp <= tgt
            hit_sl = ltp <= sl if direction == "BUY" else ltp >= sl

            if hit_target or hit_sl or is_eod:
                if is_eod:
                    exit_p = ltp
                    reason = "3:15 PM EOD Auto-Square-Off ⏱️"
                elif hit_target:
                    exit_p = tgt
                    reason = "TARGET HIT 🎯"
                else:
                    exit_p = sl
                    reason = "STOP LOSS HIT 🛑"

                pnl = round((exit_p - entry_p) * qty if direction == "BUY" else (entry_p - exit_p) * qty, 2)
                c.execute("""
                    UPDATE strategy_trades 
                    SET status = 'CLOSED', exit_price = ?, exit_time = ?, pnl = ?, exit_reason = ?
                    WHERE id = ?
                """, (exit_p, current_time_str, pnl, reason, pos_id))
                conn.commit()

                icon = "🟢" if pnl >= 0 else "🔴"
                send_telegram(
                    f"{icon} <b>INTRADAY EXIT: {sym}</b>\n\n"
                    f"<b>Reason:</b> {reason}\n"
                    f"<b>Exit Price:</b> ₹{exit_p}\n"
                    f"<b>Net P&L:</b> ₹{pnl:,.2f}"
                )
        except Exception as e:
            print(f"Error auditing {sym}: {e}")

def run_intraday_cycle():
    ist = pytz.timezone('Asia/Kolkata')
    now_ist = datetime.now(ist)
    current_time_str = now_ist.strftime("%Y-%m-%d %H:%M:%S IST")
    current_hhmm = now_ist.strftime("%H:%M")

    conn = get_db()
    c = conn.cursor()

    is_eod = current_hhmm >= "15:15"
    audit_open_positions(conn, current_time_str, is_eod)

    if current_hhmm < "09:30" or current_hhmm > "14:45":
        print(f"Market scan skipped. Outside scan window: {current_hhmm}")
        conn.close()
        return

    print(f"⚡ Starting Quant-AI Hybrid Scan at {current_time_str}...")

    for sym in WATCHLIST:
        try:
            c.execute("SELECT id FROM strategy_trades WHERE symbol = ? AND status = 'OPEN'", (sym,))
            if c.fetchone():
                continue

            df = yf.Ticker(sym).history(period="5d", interval="15m")
            if len(df) < 30:
                continue

            df['EMA10'] = df['Close'].ewm(span=10, adjust=False).mean()
            df['EMA30'] = df['Close'].ewm(span=30, adjust=False).mean()
            df['Vol_Avg'] = df['Volume'].rolling(20).mean()

            c_bar, p_bar = df.iloc[-1], df.iloc[-2]
            bull_cross = p_bar['EMA10'] <= p_bar['EMA30'] and c_bar['EMA10'] > c_bar['EMA30']
            bear_cross = p_bar['EMA10'] >= p_bar['EMA30'] and c_bar['EMA10'] < c_bar['EMA30']
            vol_spike = c_bar['Volume'] > (c_bar['Vol_Avg'] * 1.3)

            if vol_spike and (bull_cross or bear_cross):
                direction = "BUY" if bull_cross else "SELL"
                entry_p = round(float(c_bar['Close']), 2)

                df_context = (
                    f"Price: ₹{entry_p}\n"
                    f"15m Volume: {c_bar['Volume']:,} (1.3x Avg Spike: {c_bar['Vol_Avg']:,.0f})\n"
                    f"10 EMA: ₹{c_bar['EMA10']:.2f} | 30 EMA: ₹{c_bar['EMA30']:.2f}"
                )

                print(f"📊 Technical setup on {sym} ({direction}). Summoning AI Committee...")
                approved, debate_transcript = run_ai_boardroom_debate(sym, direction, entry_p, df_context)

                if not approved:
                    print(f"🚫 CRO Vetoed {sym}: Skipping.")
                    continue

                if direction == "BUY":
                    target = round(entry_p * 1.008, 2)
                    sl = round(entry_p * 0.996, 2)
                else:
                    target = round(entry_p * 0.992, 2)
                    sl = round(entry_p * 1.004, 2)

                qty = max(1, int(25000 / entry_p))

                c.execute("""
                    INSERT INTO strategy_trades 
                    (strategy, symbol, direction, entry_price, quantity, stop_loss, target, status, entry_time, ai_note)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, ("AI_CRO_MOMENTUM", sym, direction, entry_p, qty, sl, target, "OPEN", current_time_str, debate_transcript))
                conn.commit()

                telegram_msg = (
                    f"🧠 <b>AI-APPROVED INTRADAY TRADE: {sym}</b>\n\n"
                    f"📈 <b>Action:</b> {direction}\n"
                    f"💵 <b>Entry:</b> ₹{entry_p}\n"
                    f"🎯 <b>Target:</b> ₹{target} (0.8%)\n"
                    f"🛑 <b>Stop Loss:</b> ₹{sl} (0.4%)\n"
                    f"📦 <b>Size:</b> {qty} shares (~₹{entry_p * qty:,.0f})\n\n"
                    f"<b>🏛️ AI Boardroom Debate:</b>\n"
                    f"<code>{debate_transcript}</code>"
                )
                send_telegram(telegram_msg)
                print(f"✅ Approved and Executed: {sym}")

        except Exception as e:
            print(f"Loop error on {sym}: {e}")

    conn.close()

if __name__ == "__main__":
    send_telegram("🧪 <b>Cloud Test Alert:</b> GitHub Actions successfully pinged Telegram!")
    run_intraday_cycle()
