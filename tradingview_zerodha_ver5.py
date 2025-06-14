print("\U0001F680 Starting tradingview_zerodha_ver5_with_hedge_exit...")

from flask import Flask, request, jsonify
from kiteconnect import KiteConnect
import logging
import os
import json
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv
import re
import time

# === Load .env ===
load_dotenv()
API_KEY = os.getenv("KITE_API_KEY")

app = Flask(__name__)

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/tradingview_zerodha.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

signals = {}
lot_size_cache = {}

@app.route("/")
def home():
    return "\u2705 Botelyes Trading Webhook with Hedge Exit is Running!"

def get_kite_client():
    try:
        with open("token.json") as f:
            token_data = json.load(f)
        kite = KiteConnect(api_key=API_KEY)
        kite.set_access_token(token_data["access_token"])
        return kite
    except Exception as e:
        logging.error(f"\u274c Failed to initialize Kite client: {str(e)}")
        return None

def get_lot_size(kite, tradingsymbol):
    if tradingsymbol in lot_size_cache:
        return lot_size_cache[tradingsymbol]
    try:
        instruments = kite.instruments("NFO")
        for item in instruments:
            if item["tradingsymbol"] == tradingsymbol:
                lot_size = item["lot_size"]
                lot_size_cache[tradingsymbol] = lot_size
                return lot_size
        return 1
    except Exception as e:
        logging.error(f"\u274c Error fetching lot size: {e}")
        return 1

def get_ltp(kite, symbol):
    try:
        ltp_data = kite.ltp(f"NFO:{symbol}")
        return ltp_data[f"NFO:{symbol}"]["last_price"]
    except Exception as e:
        logging.error(f"\u26A0\ufe0f Failed to fetch LTP for {symbol}: {e}")
        return None

def find_nearest_option_strike(kite, symbol, fut_price, direction):
    try:
        instruments = kite.instruments("NFO")
        expiry = None
        option_type = "CE" if direction == "LONG" else "PE"
        target_price = round(fut_price * (1.03 if direction == "LONG" else 0.97))
        symbol_upper = symbol.upper()

        for inst in instruments:
            if inst["segment"] == "NFO-OPT" and symbol_upper in inst["name"]:
                expiry = inst["expiry"]
                break

        options = [
            i for i in instruments
            if i["instrument_type"] == option_type
            and i["name"] == symbol_upper
            and i["expiry"] == expiry
        ]

        if not options:
            logging.warning(f"\u26A0\ufe0f No {option_type} options found for {symbol}")
            return None, None

        best_option = min(options, key=lambda x: abs(x["strike"] - target_price))
        return best_option["tradingsymbol"], best_option["lot_size"]

    except Exception as e:
        logging.error(f"\u274c Error finding hedge option: {e}")
        return None, None

def place_option_order(kite, symbol, lot_size, side="SELL", retries=3):
    for attempt in range(retries):
        try:
            quote = kite.quote(f"NFO:{symbol}")
            price = quote[f"NFO:{symbol}"]["depth"]["buy" if side == "SELL" else "sell"][0]["price"]

            txn_type = kite.TRANSACTION_TYPE_SELL if side == "SELL" else kite.TRANSACTION_TYPE_BUY
            order_id = kite.place_order(
                variety=kite.VARIETY_REGULAR,
                exchange="NFO",
                tradingsymbol=symbol,
                transaction_type=txn_type,
                quantity=lot_size,
                product="NRML",
                order_type="LIMIT",
                price=price
            )
            logging.info(f"{side} order placed for {symbol} at {price}, ID: {order_id}")

            for _ in range(6):
                time.sleep(5)
                order_history = kite.order_history(order_id)
                status = order_history[-1]["status"]
                if status == "COMPLETE":
                    return True
            kite.cancel_order(variety=kite.VARIETY_REGULAR, order_id=order_id)
        except Exception as e:
            logging.error(f"\u274c {side} attempt {attempt+1} failed: {e}")
            time.sleep(5)
    return False

def enter_position(kite, symbol, side):
    lot_qty = get_lot_size(kite, symbol)
    txn = kite.TRANSACTION_TYPE_BUY if side == "LONG" else kite.TRANSACTION_TYPE_SELL
    kite.place_order(
        variety=kite.VARIETY_REGULAR,
        exchange="NFO",
        tradingsymbol=symbol,
        transaction_type=txn,
        quantity=lot_qty,
        product="NRML",
        order_type="MARKET"
    )
    logging.info(f"Entered {side} for {symbol}, qty={lot_qty}")
    log_data = {
        "symbol": symbol,
        "direction": side,
        "entry_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "qty": lot_qty
    }
    with open(f"logs/{symbol}_trades.json", "a") as f:
        f.write(json.dumps(log_data) + "\n")

    # Hedge
    fut_price = get_ltp(kite, symbol)
    option_symbol, lot_size = find_nearest_option_strike(kite, symbol, fut_price, side)
    if option_symbol and place_option_order(kite, option_symbol, lot_size, side="SELL"):
        signals[symbol]["hedge_symbol"] = option_symbol
        signals[symbol]["hedge_lot"] = lot_size

def exit_position(kite, symbol, qty):
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
    logging.info(f"Exited position for {symbol}")

    # Hedge exit
    hedge_symbol = signals[symbol].get("hedge_symbol")
    hedge_lot = signals[symbol].get("hedge_lot")
    if hedge_symbol and hedge_lot:
        if place_option_order(kite, hedge_symbol, hedge_lot, side="BUY"):
            logging.info(f"Exited hedge {hedge_symbol}")
        signals[symbol]["hedge_symbol"] = None
        signals[symbol]["hedge_lot"] = 0

def get_position_quantity(kite, symbol):
    try:
        positions = kite.positions()["net"]
        for pos in positions:
            if pos["tradingsymbol"] == symbol:
                return pos["quantity"]
        return 0
    except:
        return 0

def get_active_contract(symbol):
    today = datetime.now().date()
    current_month = today.month
    current_year = today.year
    next_month_first = datetime(current_year + int(current_month == 12), (current_month % 12) + 1, 1)
    last_day = next_month_first - timedelta(days=1)
    while last_day.weekday() != 3:
        last_day -= timedelta(days=1)
    rollover_cutoff = last_day.date() - timedelta(days=4)
    if today > rollover_cutoff:
        next_month = current_month + 1 if current_month < 12 else 1
        next_year = current_year if current_month < 12 else current_year + 1
        return f"{symbol}{str(next_year)[2:]}{datetime(next_year, next_month, 1).strftime('%b').upper()}FUT"
    else:
        return f"{symbol}{str(current_year)[2:]}{datetime(current_year, current_month, 1).strftime('%b').upper()}FUT"

def handle_trade_decision(kite, symbol, signals):
    tf_signals = [signals[symbol].get(tf, "") for tf in ["3m", "5m", "10m"]]
    if tf_signals[0] == tf_signals[1] == tf_signals[2] and tf_signals[0] in ["LONG", "SHORT"]:
        new_signal = tf_signals[0]
        last_action = signals[symbol].get("last_action", "NONE")
        fut_symbol = get_active_contract(symbol)
        qty = get_position_quantity(kite, fut_symbol)

        if new_signal != last_action:
            if qty != 0:
                exit_position(kite, fut_symbol, qty)
            enter_position(kite, fut_symbol, new_signal)
            signals[symbol]["last_action"] = new_signal

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json
        raw_symbol = data.get("symbol", "")
        signal = data.get("signal", "").lower()
        timeframe_raw = data.get("timeframe", "").lower()
        timeframe = timeframe_raw.replace("minutes", "m").replace("min", "m")
        if not timeframe.endswith("m"):
            timeframe += "m"

        if signal == "buy": signal = "LONG"
        elif signal == "sell": signal = "SHORT"
        else: signal = signal.upper()

        cleaned_symbol = re.sub(r'[^A-Z]', '', raw_symbol.upper())

        if cleaned_symbol not in signals:
            signals[cleaned_symbol] = {"3m": "", "5m": "", "10m": "", "last_action": "NONE", "hedge_symbol": None, "hedge_lot": 0}

        signals[cleaned_symbol][timeframe] = signal
        kite = get_kite_client()
        if kite:
            handle_trade_decision(kite, cleaned_symbol, signals)
            return jsonify({"status": "✅ processed"})
        return jsonify({"status": "❌ kite failed"})
    except Exception as e:
        logging.error(f"Exception: {e}")
        return jsonify({"status": "❌ error", "error": str(e)})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

