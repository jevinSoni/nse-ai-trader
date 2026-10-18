import yfinance as yf
import pandas as pd
import sqlite3
import requests
from datetime import datetime
import pytz
import os

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DB_FILE = "paper_trades.db"

# Top liquid intraday universe (keeps run time under 45 seconds)
WATCHLIST = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "BHARTIARTL.NS",
    "SBIN.NS", "INFY.NS", "ITC.NS", "LT.NS", "BAJFINANCE.NS", "HAL.NS", "TRENT.NS"
]

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=6)
    except Exception as e:
        print(f"Telegram alert failed: {e}")

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

def audit_and_square_off(conn, current_time_str, is_eod):
    c = conn.cursor()
    c.execute("SELECT id, strategy, symbol, direction, entry_price, quantity, stop_loss, target FROM strategy_trades WHERE status = 'OPEN'")
    open_positions = c.fetchall()

    for pos_id, strat, sym, direction, entry_p, qty, sl, tgt in open_positions:
        try:
            hist = yf.Ticker(sym).history(period="1d", interval="1m")
            if hist.empty:
                continue
            ltp = float(hist["Close"].iloc[-1])

            hit_target = ltp >= tgt if direction == "BUY" else ltp <= tgt
            hit_sl = ltp <= sl if direction == "BUY" else ltp >= sl

            if hit_target or hit_sl or is_eod:
                if is_eod:
                    exit_p = ltp
                    reason = "3:15 PM EOD SQUARE-OFF ⏱️"
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

                pnl_color = "🟢" if pnl >= 0 else "🔴"
                send_telegram(
                    f"{pnl_color} <b>POSITION CLOSED: {sym}</b>\n"
                    f"Reason: {reason}\n"
                    f"Exit Price: ₹{exit_p}\n"
                    f"Net P&L: ₹{pnl:,.2f}"
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

    # Check for EOD square-off (Past 3:15 PM IST)
    is_eod = current_hhmm >= "15:15"
    audit_and_square_off(conn, current_time_str, is_eod)

    # Don't scan new entries past 2:45 PM or after market hours
    if current_hhmm < "09:30" or current_hhmm > "14:45":
        print(f"Market scan skipped. Outside scan window: {current_hhmm}")
        conn.close()
        return

    print(f"⚡ Starting 15-Minute Intraday Scan at {current_time_str}...")

    for sym in WATCHLIST:
        try:
            # Check if position already open
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
                
                # Tight Intraday R:R (0.8% Target, 0.4% Stop Loss)
                if direction == "BUY":
                    target = round(entry_p * 1.008, 2)
                    sl = round(entry_p * 0.996, 2)
                else:
                    target = round(entry_p * 0.992, 2)
                    sl = round(entry_p * 1.004, 2)

                qty = max(1, int(25000 / entry_p))  # ₹25,000 risk allocation per trade

                c.execute("""
                    INSERT INTO strategy_trades 
                    (strategy, symbol, direction, entry_price, quantity, stop_loss, target, status, entry_time, ai_note)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, ("INTRADAY_MOMENTUM", sym, direction, entry_p, qty, sl, target, "OPEN", current_time_str, "15m EMA+Vol Cross"))
                conn.commit()

                send_telegram(
                    f"🚨 <b>INTRADAY {direction} SIGNAL: {sym}</b>\n"
                    f"💵 Entry: ₹{entry_p}\n"
                    f"🎯 Target: ₹{target} (+0.8%)\n"
                    f"🛑 Stop Loss: ₹{sl} (-0.4%)\n"
                    f"📦 Qty: {qty} (Allocated: ₹{entry_p * qty:,.0f})\n"
                    f"⏱️ Time: {current_hhmm} IST"
                )
                print(f"Executed intraday trade for {sym}")

        except Exception as e:
            print(f"Scan error for {sym}: {e}")

    conn.close()

if __name__ == "__main__":
    run_intraday_cycle()
