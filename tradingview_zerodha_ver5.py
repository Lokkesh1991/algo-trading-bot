print("🚀 Starting tradingview_zerodha_ver5...")

from flask import Flask, request, jsonify
from kiteconnect import KiteConnect
import logging
import os
import json
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv
import re

# === Load .env ===
load_dotenv()
API_KEY = os.getenv("KITE_API_KEY")

# === Flask App ===
app = Flask(__name__)

# === Logging Setup ===
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/tradingview_zerodha.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

# === In-memory signal store ===
signals = {}
lot_size_cache = {}  # <== Added cache for lot size lookup

@app.route("/")
def home():
    return "✅ Botelyes Trading Webhook is Running!"

# === Kite Connect ===
def get_kite_client():
    try:
        with open("token.json") as f:
            token_data = json.load(f)
        kite = KiteConnect(api_key=API_KEY)
        kite.set_access_token(token_data["access_token"])
        return kite
    except Exception as e:
        logging.error(f"❌ Failed to initialize Kite client: {str(e)}")
        return None

# === Lot Size Resolver ===
def get_lot_size(kite, tradingsymbol):
    if tradingsymbol in lot_size_cache:
        return lot_size_cache[tradingsymbol]
    try:
        instruments = kite.instruments("NFO")
        for item in instruments:
            if item["tradingsymbol"] == tradingsymbol:
                lot_size = item["lot_size"]
                lot_size_cache[tradingsymbol] = lot_size
                logging.info(f"📦 Lot size for {tradingsymbol}: {lot_size}")
                return lot_size
        logging.warning(f"⚠️ Lot size not found for {tradingsymbol}, defaulting to 1")
        return 1
    except Exception as e:
        logging.error(f"❌ Error fetching lot size: {e}")
        return 1

# === Position Lookup ===
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

# === Contract Resolver ===
def get_active_contract(symbol):
    today = datetime.now().date()
    current_month = today.month
    current_year = today.year
    next_month_first = datetime(current_year + int(current_month == 12), (current_month % 12) + 1, 1)
    last_day = next_month_first - timedelta(days=1)
    while last_day.weekday() != 0:
        last_day -= timedelta(days=1)
    rollover_cutoff = last_day.date() - timedelta(days=4)

    if today > rollover_cutoff:
        next_month = current_month + 1 if current_month < 12 else 1
        next_year = current_year if current_month < 12 else current_year + 1
        return f"{symbol}{str(next_year)[2:]}{datetime(next_year, next_month, 1).strftime('%b').upper()}FUT"
    else:
        return f"{symbol}{str(current_year)[2:]}{datetime(current_year, current_month, 1).strftime('%b').upper()}FUT"

# === Auto Rollover ===
def auto_rollover_positions(kite, symbol):
    today = datetime.now().date()
    current_month = today.month
    current_year = today.year
    next_month_first = datetime(current_year + int(current_month == 12), (current_month % 12) + 1, 1)
    last_day = next_month_first - timedelta(days=1)
    while last_day.weekday() != 0:
        last_day -= timedelta(days=1)
    rollover_cutoff = last_day.date() - timedelta(days=4)

    if today > rollover_cutoff:
        current_contract = f"{symbol}{str(current_year)[2:]}{datetime(current_year, current_month, 1).strftime('%b').upper()}FUT"
        next_month = current_month + 1 if current_month < 12 else 1
        next_year = current_year if current_month < 12 else current_year + 1
        next_contract = f"{symbol}{str(next_year)[2:]}{datetime(next_year, next_month, 1).strftime('%b').upper()}FUT"
        qty = get_position_quantity(kite, current_contract)
        if qty != 0:
            logging.info(f"🔁 Rollover from {current_contract} to {next_contract}")
            exit_position(kite, current_contract, qty)
            enter_position(kite, next_contract, "LONG" if qty > 0 else "SHORT")

# === Order Logic ===
def enter_position(kite, symbol, side):
    entry_time = datetime.now()
    lot_qty = get_lot_size(kite, symbol)
    log_data = {
        "symbol": symbol,
        "direction": side,
        "entry_time": entry_time.strftime('%Y-%m-%d %H:%M:%S'),
        "qty": lot_qty
    }
    with open(f"logs/{symbol}_trades.json", "a") as f:
        f.write(json.dumps(log_data) + "\n")

    txn = kite.TRANSACTION_TYPE_BUY if side == "LONG" else kite.TRANSACTION_TYPE_SELL

    try:
        kite.place_order(
            variety=kite.VARIETY_REGULAR,
            exchange="NFO",
            tradingsymbol=symbol,
            transaction_type=txn,
            quantity=lot_qty,
            product="NRML",
            order_type="MARKET"
        )
        logging.info(f"✅ Entered {side} for {symbol} with quantity={lot_qty}")
    except Exception as e:
        logging.error(f"❌ Entry failed: {e}")

def exit_position(kite, symbol, qty):
    try:
        txn = KiteConnect.TRANSACTION_TYPE_SELL if qty > 0 else KiteConnect.TRANSACTION_TYPE_BUY
        kite.place_order(
            variety=kite.VARIETY_REGULAR,
            exchange="NFO",
            tradingsymbol=symbol,
            transaction_type=txn,
            quantity=abs(qty),
            product="NRML",
            order_type="MARKET"
        )
        logging.info(f"🚪 Exited position for {symbol}")
    except Exception as e:
        logging.error(f"❌ Exit failed: {e}")

# === Decision Logic ===
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
        logging.info(f"❌ Not aligned for {symbol}: {tf_signals}")

# === Webhook ===
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json
        raw_symbol = data.get("symbol", "")
        signal = data.get("signal", "").lower()
        timeframe = data.get("timeframe", "")

        if signal == "buy":
            signal = "LONG"
        elif signal == "sell":
            signal = "SHORT"
        else:
            signal = signal.upper()

        cleaned_symbol = re.sub(r'[^A-Z]', '', raw_symbol.upper())

        logging.info(f"📩 Webhook received: raw={raw_symbol}, cleaned={cleaned_symbol}, signal={signal}, timeframe={timeframe}")
        if not cleaned_symbol or not signal or not timeframe:
            return jsonify({"status": "❌ Invalid data"}), 400

        if cleaned_symbol not in signals:
            signals[cleaned_symbol] = {"3m": "", "5m": "", "10m": "", "last_action": "NONE"}

        signals[cleaned_symbol][timeframe] = signal

        kite = get_kite_client()
        if not kite:
            return jsonify({"status": "❌ Kite client init failed"}), 500

        auto_rollover_positions(kite, cleaned_symbol)
        handle_trade_decision(kite, cleaned_symbol, signals)

        return jsonify({"status": "✅ Webhook processed"})
    except Exception as e:
        logging.error(f"❌ Exception: {e}")
        return jsonify({"status": "❌ Crash in webhook", "error": str(e)}), 500

# === App Runner ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
