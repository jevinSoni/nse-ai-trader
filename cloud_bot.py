import os
import sys
import sqlite3
from datetime import datetime, timezone, timedelta
import yfinance as yf
import pandas as pd
import feedparser
from google import genai
from google.genai import types

DB_FILE = "paper_trades.db"
IST = timezone(timedelta(hours=5, minutes=30))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

WATCHLIST = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
    "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "LT.NS", "TMPV.NS", "TMCV.NS",
    "AXISBANK.NS", "SUNPHARMA.NS", "MARUTI.NS", "NTPC.NS", "TITAN.NS",
    "BAJFINANCE.NS", "TRENT.NS", "TATASTEEL.NS", "ADANIENT.NS", "ETERNAL.NS",
    "HAL.NS", "BEL.NS", "M&M.NS", "POWERGRID.NS"
]

TRADE_QTY = 10
MAX_POSITIONS_PER_STRAT = 5

def now_ist():
    return datetime.now(IST)

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS strategy_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy TEXT,
            symbol TEXT,
            direction TEXT,
            entry_price REAL,
            quantity INTEGER,
            stop_loss REAL,
            target REAL,
            status TEXT,
            entry_time TEXT,
            exit_price REAL,
            exit_time TEXT,
            pnl REAL,
            exit_reason TEXT,
            ai_note TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS strategy_accounts (
            strategy TEXT PRIMARY KEY,
            cash REAL
        )
    """)
    c.execute("INSERT OR IGNORE INTO strategy_accounts (strategy, cash) VALUES ('PURE_QUANT', 100000.0)")
    c.execute("INSERT OR IGNORE INTO strategy_accounts (strategy, cash) VALUES ('AI_HYBRID', 100000.0)")
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS ai_rejections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            direction TEXT,
            price REAL,
            time TEXT,
            ai_reason TEXT
        )
    """)
    conn.commit()
    conn.close()

def is_market_open():
    now = now_ist()
    if now.weekday() >= 5:  # Saturday (5) & Sunday (6)
        return False
    open_t = now.replace(hour=9, minute=15, second=0, microsecond=0)
    close_t = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return open_t <= now <= close_t

def get_headlines():
    try:
        feed = feedparser.parse("https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms")
        return [entry.title for entry in feed.entries[:6]]
    except Exception:
        return []

def ask_ai_gatekeeper(symbol, direction, price, rsi, vol_ratio, atr, headlines):
    if not GEMINI_API_KEY:
        return True, "No API key configured; auto-approved."
    
    prompt = f"""
    You are an institutional risk-filter for an Indian NSE algorithmic trading strategy.
    A breakout signal triggered:
    - Stock: {symbol} | Direction: {direction} | Price: ₹{price}
    - RSI(14): {rsi:.1f} | Volume Spike: {vol_ratio:.2f}x | ATR(14): ₹{atr:.2f}
    - Recent Market Headlines: {headlines}

    Determine if this setup is high probability or an obvious trap/exhaustion.
    Reply with EXACTLY this structure on a single line:
    DECISION: APPROVE | REASON: <1 concise sentence>
    or
    DECISION: REJECT | REASON: <1 concise sentence>
    """
    client = genai.Client(api_key=GEMINI_API_KEY)
    for model_name in ["gemini-2.5-flash", "gemini-2.5-flash-lite"]:
        try:
            res = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.2)
            )
            text = res.text.strip().replace("\n", " ")
            approved = "DECISION: APPROVE" in text.upper()
            reason = text.split("REASON:")[-1].strip() if "REASON:" in text else text
            return approved, reason
        except Exception:
            continue
    return True, "AI rate-limited; fallback approved."

def fetch_data(symbol):
    try:
        df = yf.Ticker(symbol).history(period="5d", interval="15m")
        if df is None or len(df) < 50:
            return None
        df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
        df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
        delta = df["Close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        df["RSI"] = 100 - (100 / (1 + (gain / loss)))
        tr = pd.concat([
            df["High"] - df["Low"],
            (df["High"] - df["Close"].shift()).abs(),
            (df["Low"] - df["Close"].shift()).abs()
        ], axis=1).max(axis=1)
        df["ATR"] = tr.rolling(window=14).mean()
        df["Vol_Avg20"] = df["Volume"].rolling(window=20).mean()
        df["Vol_Ratio"] = df["Volume"] / df["Vol_Avg20"]
        return df
    except Exception:
        return None

def manage_open_positions():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    open_trades = c.execute("""
        SELECT id, strategy, symbol, direction, entry_price, quantity, stop_loss, target 
        FROM strategy_trades WHERE status = 'OPEN'
    """).fetchall()
    
    for t_id, strat, sym, direction, entry_p, qty, sl, tgt in open_trades:
        df = fetch_data(sym)
        if df is None:
            continue
        ltp = round(df.iloc[-1]["Close"], 2)
        should_close, reason = False, ""

        if direction == "BUY":
            if ltp >= tgt:
                should_close, reason = True, "TARGET HIT 🎯"
            elif ltp <= sl:
                should_close, reason = True, "STOP LOSS HIT 🛑"
        elif direction == "SELL":
            if ltp <= tgt:
                should_close, reason = True, "TARGET HIT 🎯"
            elif ltp >= sl:
                should_close, reason = True, "STOP LOSS HIT 🛑"

        if should_close:
            pnl = round((ltp - entry_p) * qty if direction == "BUY" else (entry_p - ltp) * qty, 2)
            c.execute("""
                UPDATE strategy_trades 
                SET status = 'CLOSED', exit_price = ?, exit_time = ?, pnl = ?, exit_reason = ?
                WHERE id = ?
            """, (ltp, now_ist().strftime("%Y-%m-%d %H:%M:%S IST"), pnl, reason, t_id))
            c.execute("UPDATE strategy_accounts SET cash = cash + ? WHERE strategy = ?", ((entry_p * qty) + pnl, strat))
            conn.commit()
            print(f"[{strat}] Exited {sym} | {reason} | P&L: ₹{pnl}")
    conn.close()

def execute_entry(conn, strat, sym, direction, price, sl, tgt, note):
    c = conn.cursor()
    open_syms = [r[0] for r in c.execute("SELECT symbol FROM strategy_trades WHERE status = 'OPEN' AND strategy = ?", (strat,)).fetchall()]
    if sym in open_syms or len(open_syms) >= MAX_POSITIONS_PER_STRAT:
        return
    cash = c.execute("SELECT cash FROM strategy_accounts WHERE strategy = ?", (strat,)).fetchone()[0]
    cost = price * TRADE_QTY
    if cash >= cost:
        c.execute("""
            INSERT INTO strategy_trades (strategy, symbol, direction, entry_price, quantity, stop_loss, target, status, entry_time, exit_price, exit_time, pnl, exit_reason, ai_note)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, 0, '', 0, '', ?)
        """, (strat, sym, direction, price, TRADE_QTY, sl, tgt, now_ist().strftime("%Y-%m-%d %H:%M:%S IST"), note))
        c.execute("UPDATE strategy_accounts SET cash = cash - ? WHERE strategy = ?", (cost, strat))
        conn.commit()
        print(f"[{strat}] ENTERED {direction} {sym} @ ₹{price} | Note: {note}")

def scan_and_enter():
    conn = sqlite3.connect(DB_FILE)
    headlines = get_headlines()

    for sym in WATCHLIST:
        df = fetch_data(sym)
        if df is None:
            continue
        last = df.iloc[-1]
        price = round(last["Close"], 2)
        atr = round(last["ATR"], 2)

        is_bullish = (last["Close"] > last["EMA20"] > last["EMA50"]) and (55 < last["RSI"] < 75) and (last["Vol_Ratio"] >= 1.5)
        is_bearish = (last["Close"] < last["EMA20"] < last["EMA50"]) and (25 < last["RSI"] < 45) and (last["Vol_Ratio"] >= 1.5)

        if is_bullish or is_bearish:
            direction = "BUY" if is_bullish else "SELL"
            sl = round(price - (1.5 * atr) if is_bullish else price + (1.5 * atr), 2)
            tgt = round(price + (3.0 * atr) if is_bullish else price - (3.0 * atr), 2)

            # Strategy 1: PURE QUANT (math rules only)
            execute_entry(conn, "PURE_QUANT", sym, direction, price, sl, tgt, "Math Trigger (EMA+RSI+Vol)")

            # Strategy 2: AI HYBRID (filtered through Gemini)
            approved, ai_reason = ask_ai_gatekeeper(sym, direction, price, last["RSI"], last["Vol_Ratio"], atr, headlines)
            if approved:
                execute_entry(conn, "AI_HYBRID", sym, direction, price, sl, tgt, f"AI Approved: {ai_reason}")
            else:
                conn.cursor().execute("""
                    INSERT INTO ai_rejections (symbol, direction, price, time, ai_reason)
                    VALUES (?, ?, ?, ?, ?)
                """, (sym, direction, price, now_ist().strftime("%Y-%m-%d %H:%M:%S IST"), ai_reason))
                conn.commit()
                print(f"[AI_HYBRID] VETOED {sym}: {ai_reason}")

    conn.close()

if __name__ == "__main__":
    init_db()
    force_run = "--force" in sys.argv
    if is_market_open() or force_run:
        print(f"[{now_ist().strftime('%Y-%m-%d %H:%M:%S IST')}] Running Dual-Strategy A/B Scan...")
        manage_open_positions()
        scan_and_enter()
    else:
        print(f"[{now_ist().strftime('%Y-%m-%d %H:%M:%S IST')}] Market is closed. Skipping scan.")
