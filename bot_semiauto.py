import time
import requests

# === ISI LANGSUNG DI SINI BUAT TES JALUR ===
TELEGRAM_TOKEN = "8837609908:AAEd64fiTgswO4bXNTxXIZ13unXEO92Dhe0"
CHAT_ID = "6516395346"

# Paksa profit 0% biar notif langsung jebol keluar tanpa nunggu koin baru
MIN_PROFIT_PCT = 0.0

CCODE_API_KEY = "sk-37c195affa32dfa229891f3b7e887734c68e8f0b0bc477dee3130de79105245"
CCODE_BASE_URL = "https://cn-api.ccode.dev/v1"

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try:
        res = requests.post(url, json=payload)
        print(f"📡 [Status Kirim Telegram]: {res.status_code}")
        if res.status_code != 200:
            print(f"❌ Detail Error: {res.text}")
    except Exception as e:
        print(f"❌ Gagal total kirim Telegram: {e}")

def test_scan():
    print("🧪 Menjalankan Tes Tembak Data Koin DEGEN ke Telegram...")
    token_ca = "0x4ed4e862860bedd9a60e889b742507a57b2a116b"
    price_url = f"https://api.geckoterminal.com/api/v2/networks/base/tokens/{token_ca}/pools"
    
    try:
        price_res = requests.get(price_url)
        if price_res.status_code == 200:
            pools_data = price_res.json().get("data", [])
            if len(pools_data) >= 2:
                price_dex1 = float(pools_data[0]["attributes"]["token_price_usd"])
                price_dex2 = float(pools_data[1]["attributes"]["token_price_usd"])
                
                diff = abs(price_dex1 - price_dex2)
                min_price = min(price_dex1, price_dex2)
                spread_pct = (diff / min_price) * 100
                
                WETH = "0x4200000000000000000000000000000000000006"
                uni_buy = f"https://app.uniswap.org/#/swap?inputCurrency={WETH}&outputCurrency={token_ca}&chain=base"
                uni_sell = f"https://app.uniswap.org/#/swap?inputCurrency={token_ca}&outputCurrency={WETH}&chain=base"
                
                msg = f"🧪 *TES JALUR RADAR RICHBOT SKSES!*\n\n" \
                      f"🪙 *Koin:* DEGEN/WETH\n" \
                      f"📊 *Spread Real-time:* {spread_pct:.2f}%\n\n" \
                      f"🦄 *UNISWAP Base:*\n" \
                      f"📥 [🟢 KLIK BUY]({uni_buy}) | 📤 [🔴 KLIK SELL]({uni_sell})\n\n" \
                      f"🔥 _Kalau pesan ini masuk, jalur robot lo udah paten, bro!_"
                
                send_telegram(msg)
            else:
                print("Data pool kurang dari 2.")
        else:
            print(f"Gagal konek ke GeckoTerminal API. Code: {price_res.status_code}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_scan()
