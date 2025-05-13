# === Startup Banner ===
print("🚀 Starting tradingview_zerodha_ver5...")

from flask import Flask, request, jsonify
from kiteconnect import KiteConnect
import logging
import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

# === ENV and API Setup ===
load_dotenv()
API_KEY = os.getenv("KITE_API_KEY")

app = Flask(__name__)
os.makedirs("logs", exist_ok=True)

# === Logging Setup ===
logging.basicConfig(
    filename="logs/tradingview_zerodha.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

signals = {}

@app.route("/")
def home():
    return "✅ Botelyes Trading Webhook is Running!"

# === Kite Initialization ===
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

# === Position Helper ===
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

# === Contract Selection ===
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

# === Auto-Rollover Logic ===
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
            logging.info(f"🔁 Rollover from {current} to {nxt}")
            exit_position(kite, current, qty)
            enter_position(kite, nxt, "LONG" if qty > 0 else "SHORT")

# === Entry & Exit ===
def enter_position(kite, symbol, side):
    entry_time = datetime.now()
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

def exit_position(kite, symbol, current_qty):
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
        logging.info(f"🚪 Exited {symbol} ({current_qty})")
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
            logging.info(f"✅ Already in {new_signal} for {symbol}")
    else:
        logging.info(f"❌ Signals not aligned for {symbol}: {tf_signals}")

# === Webhook ===
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
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
    except Exception as e:
        logging.exception("❌ Exception during webhook")
        return jsonify({"status": "❌ Exception", "error": str(e)})

# === Local/Railway App Runner ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
