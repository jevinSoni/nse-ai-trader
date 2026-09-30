# 1. POSITION AUDIT FIRST: Check and enforce SL/TP on all open positions BEFORE scanning new entries
def audit_open_positions(conn):
    c = conn.cursor()
    c.execute("SELECT id, strategy, symbol, entry_price, quantity, stop_loss, target FROM strategy_trades WHERE status = 'OPEN'")
    open_positions = c.fetchall()

    for pos_id, strat, sym, entry_p, qty, sl, tgt in open_positions:
        hist = yf.Ticker(sym).history(period="1d", interval="1m")
        if hist.empty:
            continue
        current_price = float(hist["Close"].iloc[-1])

        # Enforce long-only exits (Strict checks)
        hit_target = current_price >= tgt
        hit_sl = current_price <= sl

        if hit_target or hit_sl:
            exit_price = current_price
            pnl = round((exit_price - entry_p) * qty, 2)
            reason = "TARGET HIT 🎯" if hit_target else "STOP LOSS HIT 🛑"
            
            c.execute("""
                UPDATE strategy_trades 
                SET status = 'CLOSED', exit_price = ?, exit_time = datetime('now', '+330 minutes'), pnl = ?, exit_reason = ?
                WHERE id = ?
            """, (exit_price, pnl, reason, pos_id))
            conn.commit()
            print(f"[{strat}] Closed {sym}: {reason} at ₹{exit_price:.2f} (P&L: ₹{pnl})")

# 2. LONG-ONLY ENFORCEMENT & RISK SIZING: Cash swing trades must only BUY
def calculate_position_size(capital, risk_rupees, entry_price, stop_loss):
    risk_per_share = abs(entry_price - stop_loss)
    if risk_per_share <= 0:
        return 0
    qty = int(risk_rupees / risk_per_share)
    max_qty = int((capital * 0.25) / entry_price)  # Max 25% account per position
    return max(1, min(qty, max_qty))

# 3. FAIL-SAFE AI GATE: If Gemini hits rate limits, default to REJECT, not approve
def ai_veto_check(symbol, tech_summary, client):
    if not client:
        return False, "AI Vetoed: No API Key configured"
    try:
        response = client.models.generate_content(...)
        # Parse decision...
        return approved, reason
    except Exception as e:
        # Default to safety: reject the trade if AI fails
        return False, f"AI Vetoed: System throttled ({e})"
