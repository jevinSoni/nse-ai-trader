import sys
import sqlite3
from datetime import datetime, timezone, timedelta
import yfinance as yf
import pandas as pd

DB_FILE = "paper_trades.db"
IST = timezone(timedelta(hours=5, minutes=30))

WATCHLIST = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
    "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "LT.NS", "TMPV.NS", "TMCV.NS",
    "AXISBANK.NS", "SUNPHARMA.NS", "MARUTI.NS", "NTPC.NS", "TITAN.NS",
    "BAJFINANCE.NS", "TRENT.NS", "TATASTEEL.NS", "ADANIENT.NS", "ETERNAL.NS",
    "HAL.NS", "BEL.NS", "M&M.NS", "POWERGRID.NS"
]

TRADE_QTY = 10
MAX_CONCURRENT_POSITIONS = 5

def now_ist():
    return datetime.now(IST)

def init_db():
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
    conn.close()

def is_market_open():
    now = now_ist()
    if now.weekday() >= 5:  # Saturday (5) & Sunday (6)
        return False
    open_time = now.replace(hour=9, minute=15, second=0, microsecond=0)
    close_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return open_time <= now <= close_time

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
    open_trades = c.execute("SELECT id, symbol, direction, entry_price, quantity, stop_loss, target FROM trades WHERE status = 'OPEN'").fetchall()
    
    for t_id, sym, direction, entry_p, qty, sl, tgt in open_trades:
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
                UPDATE trades SET status = 'CLOSED', exit_price = ?, exit_time = ?, pnl = ?, exit_reason = ?
                WHERE id = ?
            """, (ltp, now_ist().strftime("%Y-%m-%d %H:%M:%S IST"), pnl, reason, t_id))
            c.execute("UPDATE account SET cash = cash + ? WHERE id = 1", ((entry_p * qty) + pnl,))
            conn.commit()
            print(f"Exited {sym} | {reason} | P&L: ₹{pnl}")
    conn.close()

def scan_and_enter_trades():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    existing_symbols = [r[0] for r in c.execute("SELECT symbol FROM trades WHERE status = 'OPEN'").fetchall()]
    available_cash = c.execute("SELECT cash FROM account WHERE id = 1").fetchone()[0]

    if len(existing_symbols) >= MAX_CONCURRENT_POSITIONS:
        conn.close()
        return

    for sym in WATCHLIST:
        if sym in existing_symbols:
            continue
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
            cost = price * TRADE_QTY

            if available_cash >= cost:
                c.execute("""
                    INSERT INTO trades (symbol, direction, entry_price, quantity, stop_loss, target, status, entry_time, exit_price, exit_time, pnl, exit_reason)
                    VALUES (?, ?, ?, ?, ?, ?, 'OPEN', ?, 0, '', 0, '')
                """, (sym, direction, price, TRADE_QTY, sl, tgt, now_ist().strftime("%Y-%m-%d %H:%M:%S IST")))
                c.execute("UPDATE account SET cash = cash - ? WHERE id = 1", (cost,))
                conn.commit()
                available_cash -= cost
                existing_symbols.append(sym)
                print(f"AUTO-ENTER: {direction} {sym} at ₹{price} (SL: ₹{sl}, Target: ₹{tgt})")

            if len(existing_symbols) >= MAX_CONCURRENT_POSITIONS:
                break
    conn.close()

if __name__ == "__main__":
    init_db()
    force_run = "--force" in sys.argv
    if is_market_open() or force_run:
        print(f"[{now_ist().strftime('%Y-%m-%d %H:%M:%S IST')}] Running cloud scan...")
        manage_open_positions()
        scan_and_enter_trades()
    else:
        print(f"[{now_ist().strftime('%Y-%m-%d %H:%M:%S IST')}] Outside NSE market hours. Skipping.")