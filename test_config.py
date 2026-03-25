import os
import requests
from dotenv import load_dotenv

def test_telegram():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    print("\n--- Kiểm tra Telegram ---")
    if not token or not chat_id:
        print("❌ Lỗi: Thiếu TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHAT_ID trong .env")
        return
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": "🔔 Test: Cấu hình Telegram của bạn đã chính xác!", "parse_mode": "HTML"}
    
    try:
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code == 200:
            print("✅ Thành công: Đã gửi tin nhắn test qua Telegram.")
        else:
            print(f"❌ Thất bại: Telegram phản hồi lỗi {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Lỗi kết nối Telegram: {e}")

def test_cmc():
    api_key = os.getenv("CMC_API_KEY")
    print("\n--- Kiểm tra CoinMarketCap ---")
    if not api_key:
        print("❌ Lỗi: Thiếu CMC_API_KEY trong .env")
        return
    
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    headers = {'Accepts': 'application/json', 'X-CMC_PRO_API_KEY': api_key}
    
    try:
        response = requests.get(url, headers=headers, params={'limit': '5'}, timeout=5)
        if response.status_code == 200:
            data = response.json()
            symbols = [d['symbol'] for d in data['data']]
            print(f"✅ Thành công: Đã lấy được Top 5 coin: {', '.join(symbols)}")
        else:
            print(f"❌ Thất bại: CMC phản hồi lỗi {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Lỗi kết nối CMC: {e}")

if __name__ == "__main__":
    load_dotenv()
    print("🚀 Bắt đầu kiểm tra cấu hình...")
    test_cmc()
    test_telegram()
    print("\nKiểm tra hoàn tất!")
