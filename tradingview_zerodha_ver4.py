# === Safe Startup Logging (Gunicorn crash protection) ===
print("🚀 Starting tradingview_zerodha_ver4...")
try:
    from flask import Flask, request, jsonify
    from kiteconnect import KiteConnect
    import logging
    import os
    import json
    from datetime import datetime, timedelta
    from dotenv import load_dotenv
    print("✅ All core imports loaded successfully")
except Exception as e:
    print("❌ Startup crash during import:", str(e))

# === CONFIG ===
PAPER_TRADE = True  # ✅ Set to False to place real trades

# === INIT ===
load_dotenv()
API_KEY = os.getenv("KITE_API_KEY")
app = Flask(__name__)

# === LOGGING ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# === In-Memory Signal Store ===
signals = {}

@app.route("/")
def home():
    return "✅ Botelyes Trading Webhook is Running!"

# === Kite Client ===
def get_kite_client():
    try:
        with open("token.json") as f:
            token_data = json.load(f)
        kite = KiteConnect(api_key=API_KEY)
        kite.set_access_token(token_data["access_token"])
        return kite
    except Exception as e:
        logging.error(f"❌ Kite init error: {str(e)}")
        return None

# === Position Quantity ===
def get_position_quantity(kite, tradingsymbol):
    try:
        positions = kite.positions()["net"]
        for pos in positions:
            if pos["tradingsymbol"] == tradingsymbol:
                return pos["quantity"]
        return 0
    except Exception as e:
        logging.error(f"⚠️ Failed to fetch positions: {e}")
        return 0

# === Get Active Futures Contract ===
def get_active_contract(symbol):
    today = datetime.now().date()
    last_day = datetime(today.year, today.month + 1, 1) - timedelta(days=1) if today.month < 12 else datetime(today.year + 1, 1, 1) - timedelta(days=1)
    while last_day.weekday() != 0:
        last_day -= timedelta(days=1)
    rollover_cutoff = last_day - timedelta(days=4)
    if today > rollover_cutoff:
        next_month = today.month + 1 if today.month < 12 else 1
        next_year = today.year if today.month < 12 else today.year + 1
        return f"{symbol}{str(next_year)[2:]}{datetime(next_year, next_month, 1).strftime('%b').upper()}FUT"
    else:
        return f"{symbol}{str(today.year)[2:]}{datetime(today.year, today.month, 1).strftime('%b').upper()}FUT"

# === Auto Rollover ===
def auto_rollover_positions(kite, symbol):
    today = datetime.now().date()
    last_day = datetime(today.year, today.month + 1, 1) - timedelta(days=1) if today.month < 12 else datetime(today.year + 1, 1, 1) - timedelta(days=1)
    while last_day.weekday() != 0:
        last_day -= timedelta(days=1)
    rollover_cutoff = last_day - timedelta(days=4)

    if today > rollover_cutoff:
        current = f"{symbol}{str(today.year)[2:]}{datetime(today.year, today.month, 1).strftime('%b').upper()}FUT"
        next_month = today.month + 1 if today.month < 12 else 1
        next_year = today.year if today.month < 12 else today.year + 1
        nxt = f"{symbol}{str(next_year)[2:]}{datetime(next_year, next_month, 1).strftime('%b').upper()}FUT"
        qty = get_position_quantity(kite, current)
        if qty != 0:
            logging.info(f"🔁 Rollover triggered for {symbol} from {current} to {nxt}")
            exit_position(kite, current, qty)
            enter_position(kite, nxt, "LONG" if qty > 0 else "SHORT")

# === Entry ===
def enter_position(kite, symbol, side):
    os.makedirs("logs", exist_ok=True)
    entry_time = datetime.now()
    log_data = {
        "symbol": symbol,
        "direction": side,
        "entry_time": entry_time.strftime('%Y-%m-%d %H:%M:%S'),
        "exit_time": None,
        "qty": 1,
        "pnl": None
    }
    print("📘 PAPER ENTRY:", json.dumps(log_data))
    with open(f"logs/{symbol}_trades.json", "a") as f:
        f.write(json.dumps(log_data) + "\n")
    with open("trades_log.txt", "a") as f:
        f.write(f"{entry_time} - ENTER {side} - {symbol} (Paper={PAPER_TRADE})\n")

    if PAPER_TRADE:
        logging.info(f"📅 [PAPER] Entered {side} for {symbol}")
        return

    txn = kite.TRANSACTION_TYPE_BUY if side == "LONG" else kite.TRANSACTION_TYPE_SELL
    try:
        kite.place_order(
            variety=kite.VARIETY_REGULAR,
            exchange="NFO",
            tradingsymbol=symbol,
            transaction_type=txn,
            quantity=1,
            product="NRML",
            order_type="MARKET"
        )
        logging.info(f"✅ Entered {side} for {symbol}")
    except Exception as e:
        logging.error(f"❌ Entry failed: {e}")

# === Exit ===
def exit_position(kite, symbol, current_qty):
    os.makedirs("logs", exist_ok=True)
    try:
        ltp = kite.ltp(f'NFO:{symbol}')[f'NFO:{symbol}']['last_price']
    except Exception as e:
        logging.error(f"⚠️ Could not fetch LTP: {e}")
        ltp = None

    exit_time = datetime.now()
    direction = "LONG" if current_qty > 0 else "SHORT"
    exit_log = {
        "symbol": symbol,
        "direction": direction,
        "exit_time": exit_time.strftime('%Y-%m-%d %H:%M:%S'),
        "qty": abs(current_qty),
        "exit_price": ltp,
        "pnl": None
    }
    print("📕 PAPER EXIT:", json.dumps(exit_log))
    with open(f"logs/{symbol}_trades.json", "a") as f:
        f.write(json.dumps(exit_log) + "\n")
    with open("trades_log.txt", "a") as f:
        f.write(f"{exit_time} - EXIT {direction} - {symbol} (Paper={PAPER_TRADE})\n")

    if PAPER_TRADE:
        logging.info(f"📅 [PAPER] Exited {direction} for {symbol}")
        return

    txn = kite.TRANSACTION_TYPE_SELL if current_qty > 0 else kite.TRANSACTION_TYPE_BUY
    try:
        kite.place_order(
            variety=kite.VARIETY_REGULAR,
            exchange="NFO",
            tradingsymbol=symbol,
            transaction_type=txn,
            quantity=abs(current_qty),
            product="NRML",
            order_type="MARKET"
        )
        logging.info(f"🚪 Exited position for {symbol}")
    except Exception as e:
        logging.error(f"❌ Exit failed: {e}")

# === Core Logic ===
def handle_trade_decision(kite, symbol, signals):
    tf_signals = [signals[symbol].get(tf, "") for tf in ["3m", "5m", "10m"]]
    if tf_signals[0] == tf_signals[1] == tf_signals[2] and tf_signals[0] in ["LONG", "SHORT"]:
        new_signal = tf_signals[0]
        last_action = signals[symbol].get("last_action", "NONE")
        tradingsymbol = get_active_contract(symbol)
        current_qty = get_position_quantity(kite, tradingsymbol)

        if new_signal != last_action:
            if current_qty != 0:
                exit_position(kite, tradingsymbol, current_qty)
            enter_position(kite, tradingsymbol, new_signal)
            signals[symbol]["last_action"] = new_signal
        else:
            logging.info(f"✅ Already in {new_signal} for {symbol}. No action.")
    else:
        logging.info(f"❌ {symbol} signals not aligned: {tf_signals}")

# === Webhook Endpoint ===
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    symbol = data.get("symbol")
    signal = data.get("signal")
    timeframe = data.get("timeframe")

    if not symbol or not signal or not timeframe:
        return jsonify({"status": "❌ Invalid data"})

    if symbol not in signals:
        signals[symbol] = {"3m": "", "5m": "", "10m": "", "last_action": "NONE"}

    signals[symbol][timeframe] = signal.upper()

    kite = get_kite_client()
    if not kite:
        return jsonify({"status": "❌ Kite client init failed"})

    auto_rollover_positions(kite, symbol)
    handle_trade_decision(kite, symbol, signals)

    return jsonify({"status": "✅ Webhook processed"})
