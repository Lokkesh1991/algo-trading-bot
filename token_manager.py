from kiteconnect import KiteConnect
import os
import json
from dotenv import load_dotenv

load_dotenv()

def generate_new_token():
    kite = KiteConnect(api_key=os.getenv("KITE_API_KEY"))
    print("👉 Open this URL in your browser to login and get request token:")
    print(kite.login_url())
    request_token = input("🔑 Paste the request token here: ")
    data = kite.generate_session(request_token, api_secret=os.getenv("KITE_API_SECRET"))
    
    # Save token to token.json
    with open("token.json", "w") as f:
        json.dump({"access_token": data["access_token"]}, f)

    print("✅ New access token generated and saved to token.json")
