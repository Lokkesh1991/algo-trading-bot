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
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/server_debug.log",
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
        token_path = "token.json"
        if not os.path.exists(token_path):
            logging.warning("⚠️ token.json not found. Returning None.")
            return None
        with open(token_path) as f:
            token_data = json.load(f)
        kite = KiteConnect(api_key=API_KEY)
        kite.set_access_token(token_data["access_token"])
        return kite
    except Exception as e:
        logging.error(f"❌ Kite init error: {str(e)}")
        return None

# === Webhook Endpoint (Test Only) ===
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        logging.info("📩 Incoming webhook received.")
        data = request.json
        symbol = data.get("symbol")
        signal = data.get("signal")
        timeframe = data.get("timeframe")

        if not symbol or not signal or not timeframe:
            logging.warning("⚠️ Missing required fields in webhook payload.")
            return jsonify({"status": "❌ Invalid data"}), 400

        logging.info(f"✅ Webhook data received: {data}")
        return jsonify({"status": "✅ Webhook received", "data": data})

    except Exception as e:
        logging.exception("❌ Exception during webhook processing")
        return jsonify({"status": "❌ Crash in webhook", "error": str(e)}), 500
