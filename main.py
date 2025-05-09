from flask import Flask
import os
import requests
import random
import time
from datetime import datetime
from deep_translator import GoogleTranslator
import feedparser
import tweepy
from dotenv import load_dotenv, main

# Flask web uygulamasını başlat
app = Flask(__name__)

# .env dosyasını yükle
load_dotenv()

# Çeviri ve Twitter API yapılandırması
CONSUMER_KEY = os.getenv('CONSUMER_KEY')
CONSUMER_SECRET = os.getenv('CONSUMER_SECRET')
ACCESS_TOKEN = os.getenv('ACCESS_TOKEN')
ACCESS_TOKEN_SECRET = os.getenv('ACCESS_TOKEN_SECRET')

client = tweepy.Client(
    consumer_key=CONSUMER_KEY,
    consumer_secret=CONSUMER_SECRET,
    access_token=ACCESS_TOKEN,
    access_token_secret=ACCESS_TOKEN_SECRET
)

# Çeviri fonksiyonu
def translate_to_turkish(text):
    try:
        result = GoogleTranslator(source='en', target='tr').translate(text)
        return result
    except Exception as e:
        print(f"Çeviri hatası: {e}")
        return text

def get_latest_news():
    """CoinDesk RSS feed üzerinden haberleri çek"""
    try:
        feed = feedparser.parse('https://www.coindesk.com/arc/outboundfeeds/rss/')
        news_list = []

        for entry in feed.entries[:5]:
            news_list.append({
                'title': entry.title,
                'link': entry.link
            })

        return news_list if news_list else None
    except Exception as e:
        print(f"RSS haber çekme hatası: {e}")
        return None

def create_tweet(news_item):
    try:
        translated_title = translate_to_turkish(news_item['title'])
        selected_hashtags = random.sample(["#Bitcoin", "#BTC", "#Kripto", "#KriptoPara"], k=3)
        hashtags_str = ' '.join(selected_hashtags)

        tweet_text = f"{translated_title}\n\n🔗 {news_item['link']}\n\n{hashtags_str}"
        return tweet_text[:275] + "..." if len(tweet_text) > 280 else tweet_text
    except Exception as e:
        print(f"Tweet oluşturma hatası: {e}")
        return None

def post_tweet(news_item):
    try:
        tweet_text = create_tweet(news_item)
        if not tweet_text:
            return False

        client.create_tweet(text=tweet_text)
        print(f"✅ Tweet atıldı: {datetime.now().strftime('%H:%M:%S')}")
        return True
    except tweepy.TweepyException as e:
        print(f"Tweet atma hatası: {e}")
        return False

@app.route('/')
def index():
    """Uptime Robot için boş bir HTTP yanıtı"""
    return "Bitcoin Haber Botu Çalışıyor!"

def run_bot():
    """Botu çalıştırma ve tweet atma"""
    while True:
        news_items = get_latest_news()
        if not news_items:
            print(f"⚠️ Haber bulunamadı. {datetime.now().strftime('%H:%M')}")
            time.sleep(3600)  # 1 saat bekle
            continue

        for item in news_items:
            if post_tweet(item):
                time.sleep(900)  # 15 dakika bekle
            else:
                time.sleep(600)  # Hata varsa 10 dakika bekle

if __name__ == "__main__":
    # Replit'te sürekli çalışması için thread ile botu başlat
    from threading import Thread
    thread = Thread(target=run_bot)
    thread.start()
    app.run(host="0.0.0.0", port=80)  # Flask web sunucusunu başlat

