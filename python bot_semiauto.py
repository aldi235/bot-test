import time
import requests

# === CONFIGURATION ===
TELEGRAM_TOKEN = "TOKEN_BOT_TELEGRAM_LO"
CHAT_ID = "CHAT_ID_TELEGRAM_LO"
MIN_PROFIT_PCT = 2.0  # Minimal selisih harga 2% baru kirim notif

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID, 
        "text": message, 
        "parse_mode": "Markdown", 
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Gagal kirim Telegram: {e}")

def get_new_pools():
    """ Mengambil daftar pool/token yang baru dibuat di Base """
    url = "https://api.geckoterminal.com/api/v2/networks/base/new_pools?page=1"
    headers = {"Accept": "application/json;version=20230302"}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get("data", [])
    except Exception as e:
        print(f"Error fetch pool baru: {e}")
    return []

def scan_auto_arbitrage():
    print("🕵️‍♂️ Bot Semiauto (+ Link Jual) Aktif di Codespaces... Mencari koin baru...")
    already_checked = set()

    while True:
        new_pools = get_new_pools()
        
        for pool in new_pools:
            pool_id = pool.get("id")
            if pool_id in already_checked:
                continue
                
            relationships = pool.get("relationships", {})
            base_token_id = relationships.get("base_token", {}).get("data", {}).get("id", "")
            
            if "base_" in base_token_id:
                token_ca = base_token_id.split("base_")[1]
            else:
                continue
                
            attributes = pool.get("attributes", {})
            token_name = attributes.get("name", "Unknown")
            
            price_url = f"https://api.geckoterminal.com/api/v2/networks/base/tokens/{token_ca}/pools"
            try:
                price_res = requests.get(price_url)
                if price_res.status_code == 200:
                    pools_data = price_res.json().get("data", [])
                    
                    if len(pools_data) >= 2:
                        price_dex1 = float(pools_data[0]["attributes"]["token_price_usd"])
                        price_dex2 = float(pools_data[1]["attributes"]["token_price_usd"])
                        dex1_name = pools_data[0]["attributes"]["market"]
                        dex2_name = pools_data[1]["attributes"]["market"]
                        
                        if price_dex1 > 0 and price_dex2 > 0:
                            diff = abs(price_dex1 - price_dex2)
                            min_price = min(price_dex1, price_dex2)
                            spread_pct = (diff / min_price) * 100
                            
                            if spread_pct >= MIN_PROFIT_PCT:
                                murah_di = dex2_name if price_dex1 > price_dex2 else dex1_name
                                mahal_di = dex1_name if price_dex1 > price_dex2 else dex2_name
                                
                                # === LINK INSTAN LINK (BUY & SELL) ===
                                WETH = "0x4200000000000000000000000000000000000006"
                                
                                # JALUR UNISWAP
                                uni_buy = f"https://app.uniswap.org/#/swap?inputCurrency={WETH}&outputCurrency={token_ca}&chain=base"
                                uni_sell = f"https://app.uniswap.org/#/swap?inputCurrency={token_ca}&outputCurrency={WETH}&chain=base"
                                
                                # JALUR SUSHISWAP
                                sushi_buy = f"https://www.sushi.com/swap?chainId=8453&token0={WETH}&token1={token_ca}"
                                sushi_sell = f"https://www.sushi.com/swap?chainId=8453&token0={token_ca}&token1={WETH}"
                                
                                msg = f"🚨 *PELUANG ARBITRASE BASE INDIKASI!*\n\n" \
                                      f"🪙 *Koin:* {token_name}\n" \
                                      f"📊 *Spread:* {spread_pct:.2f}%\n" \
                                      f"🛒 *Beli Murah di:* {murah_di}\n" \
                                      f"💰 *Jual Mahal di:* {mahal_di}\n\n" \
                                      f"📌 *CONTRACT ADDRESS (CA):*\n`{token_ca}`\n\n" \
                                      f"⚡ *AKSI CEPAT (FAST SWAP):*\n\n" \
                                      f"🦄 *UNISWAP Base:*\n" \
                                      f"📥 [🟢 KLIK BUY]({uni_buy}) | 📤 [🔴 KLIK SELL]({uni_sell})\n\n" \
                                      f"🍣 *SUSHISWAP Base:*\n" \
                                      f"📥 [🟢 KLIK BUY]({sushi_buy}) | 📤 [🔴 KLIK SELL]({sushi_sell})\n\n" \
                                      f"💡 _Eksekusi BUY di DEX yang murah, setelah sukses langsung klik SELL di DEX yang mahal!_"
                                
                                print(f"🔥 Peluang terdeteksi pada koin {token_name}")
                                send_telegram(msg)
                                
            except Exception as e:
                pass
                
            already_checked.add(pool_id)
            
        time.sleep(10)

if __name__ == "__main__":
    scan_auto_arbitrage()
