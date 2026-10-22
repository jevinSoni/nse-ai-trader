import os
import sqlite3
from datetime import datetime
from google import genai
import pandas as pd
import pytz
import requests
import yfinance as yf

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DB_FILE = "paper_trades.db"

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# Expanded universe of top liquid NSE momentum movers
WATCHLIST = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "BHARTIARTL.NS",
    "SBIN.NS", "INFY.NS", "ITC.NS", "LT.NS", "BAJFINANCE.NS", "HAL.NS",
    "TRENT.NS", "TATAMOTORS.NS", "M&M.NS", "AXISBANK.NS", "KOTAKBANK.NS",
    "SUNPHARMA.NS", "MARUTI.NS", "NTPC.NS", "ONGC.NS"
]

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=8)
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
    try:
        ticker = yf.Ticker(symbol)
        news_items = ticker.news
        if not news_items:
            return "No breaking news reported."
        headlines = [f"- {item.get('title', '')}" for item in news_items[:3] if item.get('title')]
        return "\n".join(headlines) if headlines else "No major catalysts found."
    except Exception:
        return "News feed unavailable."

def run_ai_boardroom_debate(symbol, direction, entry_p, df_context):
    if not client:
        return True, "No Gemini API Key provided."

    news_data = get_live_news_summary(symbol)
    prompt = f"""
You are the Investment Committee of an intraday quant desk.
Technical setup triggered:
TICKER: {symbol} | DIRECTION: {direction} | ENTRY: ₹{entry_p}
TECHNICALS: {df_context}
NEWS: {news_data}

Evaluate and follow this exact format:
[NEWS_ANALYSIS]: <1 sentence catalyst review>
[BULL]: <1 sentence bull argument>
[BEAR]: <1 sentence bear argument>
[CRO_DECISION]: <APPROVED or VETOED>
[CRO_RATIONALE]: <1 sentence final decision reasoning>
"""
    try:
        response = client.models.generate_content(model="gemini-flash-latest", contents=prompt)
        text = response.text.strip()
        is_approved = "[CRO_DECISION]: APPROVED" in text.upper()
        return is_approved, text
    except Exception as e:
        print(f"AI error: {e}")
        return False, f"Error: {e}"

def audit_open_positions(conn, current_time_str, is_eod):
    c = conn.cursor()
    c.execute("SELECT id, strategy, symbol, direction, entry_price, quantity, stop_loss, target FROM strategy_trades WHERE status = 'OPEN'")
    for pos_id, strat, sym, direction, entry_p, qty, sl, tgt in c.fetchall():
        try:
            hist = yf.Ticker(sym).history(period="1d", interval="1m")
            if hist.empty:
                continue
            ltp = float(hist['Close'].iloc[-1])

            hit_target = ltp >= tgt if direction == "BUY" else ltp <= tgt
            hit_sl = ltp <= sl if direction == "BUY" else ltp >= sl

            if hit_target or hit_sl or is_eod:
                exit_p = ltp if is_eod else (tgt if hit_target else sl)
                reason = "EOD Square-Off ⏱️" if is_eod else ("TARGET HIT 🎯" if hit_target else "STOP LOSS HIT 🛑")
                pnl = round((exit_p - entry_p) * qty if direction == "BUY" else (entry_p - exit_p) * qty, 2)
                
                c.execute("""
                    UPDATE strategy_trades 
                    SET status = 'CLOSED', exit_price = ?, exit_time = ?, pnl = ?, exit_reason = ?
                    WHERE id = ?
                """, (exit_p, current_time_str, pnl, reason, pos_id))
                conn.commit()

                send_telegram(f"{'🟢' if pnl >= 0 else '🔴'} <b>EXIT ({strat}): {sym}</b>\nReason: {reason}\nP&L: ₹{pnl:,.2f}")
        except Exception as e:
            print(f"Audit error: {e}")

def run_intraday_cycle():
    ist = pytz.timezone('Asia/Kolkata')
    now_ist = datetime.now(ist)
    current_time_str = now_ist.strftime("%Y-%m-%d %H:%M:%S IST")
    current_hhmm = now_ist.strftime("%H:%M")

    print(f"\n=======================================================")
    print(f"🕒 INTRADAY SCAN CYCLE: {current_time_str}")
    print(f"=======================================================")

    conn = get_db()
    c = conn.cursor()
    audit_open_positions(conn, current_time_str, current_hhmm >= "15:15")

    if current_hhmm < "09:30" or current_hhmm > "14:45":
        print(f"⚠️ Scan skipped. Outside trading hours (09:30 - 14:45 IST). Current: {current_hhmm}")
        conn.close()
        return

    triggered_count = 0

    for sym in WATCHLIST:
        try:
            c.execute("SELECT id FROM strategy_trades WHERE symbol = ? AND status = 'OPEN'", (sym,))
            if c.fetchone():
                continue

            df = yf.Ticker(sym).history(period="5d", interval="15m")
            if len(df) < 35:
                continue

            df['EMA10'] = df['Close'].ewm(span=10, adjust=False).mean()
            df['EMA30'] = df['Close'].ewm(span=30, adjust=False).mean()
            df['Vol_Avg'] = df['Volume'].rolling(20).mean()

            # Use df.iloc[-2] as the LAST COMPLETED 15m candle to avoid partial-candle volume distortion
            completed_bar = df.iloc[-2]
            prev_bar = df.iloc[-3]
            live_bar = df.iloc[-1]

            vol_ratio = completed_bar['Volume'] / completed_bar['Vol_Avg'] if completed_bar['Vol_Avg'] > 0 else 0
            
            # Setup criteria:
            # 1. EMA10 trending above EMA30 (Bullish) or below (Bearish)
            # 2. Volume on completed bar >= 1.1x average (healthy volume)
            # 3. Momentum breakout: candle closes higher than previous high (BUY) or lower than previous low (SELL)
            bullish_momentum = (completed_bar['EMA10'] > completed_bar['EMA30']) and (completed_bar['Close'] > prev_bar['High']) and (vol_ratio >= 1.1)
            bearish_momentum = (completed_bar['EMA10'] < completed_bar['EMA30']) and (completed_bar['Close'] < prev_bar['Low']) and (vol_ratio >= 1.1)

            print(f"🔍 [{sym:14}] Close: ₹{live_bar['Close']:<8.2f} | 10EMA: {completed_bar['EMA10']:<8.2f} | 30EMA: {completed_bar['EMA30']:<8.2f} | Vol: {vol_ratio:.2f}x")

            if bullish_momentum or bearish_momentum:
                triggered_count += 1
                direction = "BUY" if bullish_momentum else "SELL"
                entry_p = round(float(live_bar['Close']), 2)
                target = round(entry_p * 1.008, 2) if direction == "BUY" else round(entry_p * 0.992, 2)
                sl = round(entry_p * 0.996, 2) if direction == "BUY" else round(entry_p * 1.004, 2)
                qty = max(1, int(25000 / entry_p))

                # 1. Log Pure Quant Strategy Trade
                c.execute("""
                    INSERT INTO strategy_trades (strategy, symbol, direction, entry_price, quantity, stop_loss, target, status, entry_time, ai_note)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, ("PURE_QUANT", sym, direction, entry_p, qty, sl, target, "OPEN", current_time_str, "Math momentum trigger"))

                # 2. Run AI Boardroom Debate
                print(f"🔥 Setup detected on {sym}! Convening AI Committee...")
                df_context = f"Live Price: ₹{entry_p}, Completed Bar Volume: {completed_bar['Volume']:,} ({vol_ratio:.1f}x avg), 10EMA: ₹{completed_bar['EMA10']:.2f}, 30EMA: ₹{completed_bar['EMA30']:.2f}"
                approved, debate = run_ai_boardroom_debate(sym, direction, entry_p, df_context)

                if approved:
                    c.execute("""
                        INSERT INTO strategy_trades (strategy, symbol, direction, entry_price, quantity, stop_loss, target, status, entry_time, ai_note)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, ("AI_HYBRID", sym, direction, entry_p, qty, sl, target, "OPEN", current_time_str, debate))
                    
                    telegram_msg = (
                        f"🏛️ <b>AI BOARDROOM APPROVED TRADE (AI_HYBRID)</b>\n\n"
                        f"📌 <b>Symbol:</b> {sym} ({direction})\n"
                        f"💵 <b>Entry:</b> ₹{entry_p}\n"
                        f"🎯 <b>Target:</b> ₹{target} (0.8%) | 🛑 <b>Stop Loss:</b> ₹{sl} (0.4%)\n\n"
                        f"<b>📋 Committee Transcript:</b>\n"
                        f"<code>{debate}</code>"
                    )
                    send_telegram(telegram_msg)
                else:
                    telegram_msg = (
                        f"🚫 <b>AI BOARDROOM VETOED SETUP</b>\n\n"
                        f"📌 <b>Symbol:</b> {sym} ({direction})\n"
                        f"💵 <b>Trigger Price:</b> ₹{entry_p}\n\n"
                        f"<b>📋 Committee Transcript:</b>\n"
                        f"<code>{debate}</code>"
                    )
                    send_telegram(telegram_msg)

                conn.commit()
        except Exception as e:
            print(f"❌ Error on {sym}: {e}")

    print(f"\n🏁 Cycle complete. Setups evaluated: {triggered_count}/{len(WATCHLIST)}")
    print(f"=======================================================\n")
    conn.close()

if __name__ == "__main__":
    run_intraday_cycle()
