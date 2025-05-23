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
lot_size_cache = {}
last_trade_times = {}  # Track last trade times
last_exit_times = {}  # NEW: Track last exit times

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

# === Helper: Gold Checker ===
def is_gold_symbol(symbol):
    return "GOLD" in symbol.upper()

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

# === Stock/Index Position Count ===
def get_total_stock_positions(kite):
    try:
        active_positions = kite.positions()["net"]
        count = 0
        for pos in active_positions:
            if pos["exchange"] == "NFO" and abs(pos["quantity"]) > 0:
                if not is_gold_symbol(pos["tradingsymbol"]):
                    count += 1
        return count
    except Exception as e:
        logging.error(f"❌ Error counting active stock positions: {e}")
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
    if symbol in last_trade_times:
        if (entry_time - last_trade_times[symbol]).total_seconds() < 10:
            logging.warning(f"⏱️ Skipped duplicate entry for {symbol} within 10s block")
            return
    if symbol in last_exit_times:
        if (entry_time - last_exit_times[symbol]).total_seconds() < 10:
            logging.warning(f"⏳ Skipped entry for {symbol} - cooldown after exit")
            return

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
        last_trade_times[symbol] = entry_time
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
        last_exit_times[symbol] = datetime.now()
        logging.info(f"🚪 Exited position for {symbol}")
    except Exception as e:
        logging.error(f"❌ Exit failed: {e}")
