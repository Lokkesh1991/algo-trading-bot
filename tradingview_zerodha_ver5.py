# === Safe Startup Logging (Flask Standalone for Railway) ===
print("🚀 Starting tradingview_zerodha_ver5...")

from flask import Flask, request, jsonify
from kiteconnect import KiteConnect
import logging
import os
import json
from dotenv import load_dotenv

# === Load .env Variables ===
load_dotenv()
API_KEY = os.getenv("KITE_API_KEY")

# === Flask App ===
app = Flask(__name__)

# === Logging ===
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/tradingview_zerodha.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# === Health Check Route ===
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
        logging.error(f"❌ Failed to initialize Kite client: {str(e)}")
        return None

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

    result = f"Received signal {signal} for {symbol} at price {price}"
    logging.info(result)
    return jsonify({"status": result})

# === Run App Locally or in Railway ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
