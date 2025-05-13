from flask import Flask, request, jsonify
import os

app = Flask(__name__)

# === Health Check Route ===
@app.route("/")
def home():
    return "✅ Railway + Gunicorn + Flask is working!"

# === Simple Webhook Route ===
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    symbol = data.get("symbol")
    signal = data.get("signal")

    if not symbol or not signal:
        return jsonify({"status": "❌ Missing symbol or signal"}), 400

    print(f"🚨 Received Trade Signal: {symbol} - {signal}")
    return jsonify({"status": f"✅ Received signal for {symbol}: {signal}"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
