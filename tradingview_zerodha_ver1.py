# Redeploy trigger
from flask import Flask, request, jsonify
from kiteconnect import KiteConnect
import logging
import os
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
API_KEY = os.getenv("KITE_API_KEY")

# === Flask App ===
app = Flask(__name__)

# === Logging ===
logging.basicConfig(
    filename="tradingview_zerodha.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# === Health Check Route ===
@app.route("/")
def home():
    return "✅ Botelyes Trading Webhook is Running!"

# === Load Access Token Dynamically ===
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

# === Get Available Margin ===
def get_available_margin(kite):
    try:
        margins = kite.margins()
        return margins["equity"]["available"]["cash"]
    except Exception as e:
        logging.error(f"⚠️ Unable to fetch margin data: {str(e)}")
        return 10000

# === Detect Exit Signal ===
def detect_exit_direction(kite, symbol):
    try:
        positions = kite.positions()["net"]
        for pos in positions:
            if pos["tradingsymbol"] == symbol and pos["quantity"] != 0:
                return "SELL" if pos["quantity"] > 0 else "BUY"
        return None
    except Exception as e:
        logging.error(f"❌ Error checking positions: {str(e)}")
        return None

# === Place Order ===
def place_order(symbol, signal, price=None):
    kite = get_kite_client()
    if not kite:
        return "❌ Kite client init failed."

    available_margin = get_available_margin(kite)

    if signal == "LONG":
        transaction_type = "BUY"
    elif signal == "SHORT":
        transaction_type = "SELL"
    elif signal == "EXIT":
        transaction_type = detect_exit_direction(kite, symbol)
        if not transaction_type:
            return "⚠️ No open position to exit."
    else:
        return "❌ Unknown signal type."

    max_trading_cap = available_margin * 0.75
    trade_amount = (price or 0) * 1
    if trade_amount > max_trading_cap:
        return "❌ Trade Rejected: 75% capital usage limit reached."

    order_data = {
        "tradingsymbol": symbol,
        "exchange": "NSE",
        "transaction_type": transaction_type,
        "quantity": 1,
        "order_type": "MARKET" if price is None else "LIMIT",
        "price": price if price else None,
        "product": "MIS",
        "validity": "DAY"
    }

    try:
        order_id = kite.place_order(
            variety=kite.VARIETY_REGULAR,
            **{k: v for k, v in order_data.items() if v is not None}
        )
        logging.info(f"✅ Order Placed: {order_id} for {symbol} [{signal}]")
        return f"✅ Order Placed: {order_id}"
    except Exception as e:
        logging.error(f"❌ Order Failed: {str(e)}")
        return f"❌ Order Failed: {str(e)}"

# === Webhook Endpoint ===
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    logging.info(f"Received Webhook Data: {data}")

    symbol = data.get("symbol")
    signal = data.get("signal")
    price = data.get("price")

    if not symbol or not signal:
        return jsonify({"status": "❌ Invalid webhook data!"})

    result = place_order(symbol, signal.upper(), price)
    return jsonify({"status": result})
