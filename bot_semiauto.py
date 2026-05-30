import time
import requests
import os

# === CONFIGURATION ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Kita paksa minimal profit 0% biar notif langsung jebol keluar
MIN_PROFIT_PCT = 0.0

CCODE_API_KEY = "sk-37c195affa32dfa229891f3b7e887734c68e8f0b0bc477dee3130de79105245"
CCODE_BASE_URL = "https://cn-api.ccode.dev/v1"

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try:
        res = requests.post(url, json=payload)
        print(f"[Telegram Response]: {res.status_code} - {res.text}")
    except Exception as e:
        print(f"Gagal kirim Telegram: {e}")

def test_scan_single_token():
    print("🧪 Menjalankan Tes Koneksi Telegram & API...")
    print(f"Token yang dibaca dari Secret: {TELEGRAM_TOKEN[:10]}... ChatID: {CHAT_ID}")
    
    # Kita kunci ke CA Token DEGEN (Sudah pasti ada pool-nya di Uni & Sushi)
    token_ca = "0x4ed4e862860bedd9a60e889b742507a57b2a116b"
    token_name = "DEGEN/WETH"
    
    price_url = f"https://api.geckoterminal.com/api/v2/networks/base/tokens/{token_ca}/pools"
    
    try:
        price_res = requests.get(price_url)
        if price_res.status_code == 200:
            pools_data = price_res.json().get("data", [])
            print(f"Berhasil dapet data pool. Jumlah pool ditemukan: {len(pools_data)}")
            
            if len(pools_data) >= 2:
                price_dex1 = float(pools_data[0]["attributes"]["token_price_usd"])
                price_dex2 = float(pools_data[1]["attributes"]["token_price_usd"])
                
                diff = abs(price_dex1 - price_dex2)
                min_price = min(price_price := price_dex1, price_dex2)
                spread_pct = (diff / min_price) * 100
                
                WETH = "0x4200000000000000000000000000000000000006"
                uni_buy = f"https://app.uniswap.org/#/swap?inputCurrency={WETH}&outputCurrency={token_ca}&chain=base"
                uni_sell = f"https://app.uniswap.org/#/swap?inputCurrency={token_ca}&outputCurrency={WETH}&chain=base"
                
                msg = f"🧪 *TES NOTIFIKASI RADAR BERHASIL!*\n\n" \
                      f"🪙 *Koin Uji Coba:* {token_name}\n" \
                      f"📊 *Spread Real-time:* {spread_pct:.4f}%\n\n" \
                      f"📥 [🟢 LINK BUY UNISWAP]({uni_buy})\n" \
                      f"📤 [🔴 LINK SELL UNISWAP]({uni_sell})\n\n" \
                      f"Jika lo bisa baca pesan ini, berarti Bot Richbot lo udah aman, bro!"
                
                send_telegram(msg)
            else:
                print("Pool tidak cukup untuk kalkulasi arbitrase.")
        else:
            print(f"Gagal tembak Geckoterminal. Status code: {price_res.status_code}")
    except Exception as e:
        print(f"Error pas testing: {e}")

if __name__ == "__main__":
    test_scan_single_token()
