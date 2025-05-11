from flask import Flask, Response
import os
import requests
import random
import time
from datetime import datetime
from deep_translator import GoogleTranslator
import feedparser
import tweepy
from dotenv import load_dotenv
from threading import Thread

app = Flask(__name__)
load_dotenv()

# Twitter API
CONSUMER_KEY = os.getenv('CONSUMER_KEY')
CONSUMER_SECRET = os.getenv('CONSUMER_SECRET')
ACCESS_TOKEN = os.getenv('ACCESS_TOKEN')
ACCESS_TOKEN_SECRET = os.getenv('ACCESS_TOKEN_SECRET')

client = tweepy.Client(consumer_key=CONSUMER_KEY,
                       consumer_secret=CONSUMER_SECRET,
                       access_token=ACCESS_TOKEN,
                       access_token_secret=ACCESS_TOKEN_SECRET)

TWEETED_FILE = 'tweeted_titles.txt'

def translate_to_turkish(text):
    try:
        return GoogleTranslator(source='en', target='tr').translate(text[:500])  # Uzun metinleri kısalt
    except Exception as e:
        print(f"Çeviri hatası: {e}")
        return text

def get_latest_news():
    """CoinDesk ve Cointelegraph RSS feed'lerinden haberleri çek"""
    news_list = []

    sources = {
        "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "Cointelegraph": "https://cointelegraph.com/rss"
    }

    for name, url in sources.items():
        try:
            feed = feedparser.parse(url)
            if feed.bozo:
                print(f"❌ {name} için bozuk RSS verisi: {feed.bozo_exception}")
                continue

            for entry in feed.entries[:5]:  # Her kaynaktan 5 haber al
                if not entry.title or not entry.link:
                    continue

                translated_title = translate_to_turkish(entry.title)
                news_list.append({
                    'title': translated_title,
                    'link': entry.link,
                    'source': name
                })
        except Exception as e:
            print(f"{name} haber çekme hatası: {e}")

    return news_list if news_list else None

def create_tweet(news_item):
    try:
        selected_hashtags = random.sample(["#Bitcoin", "#BTC", "#Kripto", "#KriptoPara"], k=2)
        hashtags_str = ' '.join(selected_hashtags)
        tweet_text = f"{news_item['title']}\n\n🔗 {news_item['link']}\n\n{hashtags_str}"
        return tweet_text[:275] + "..." if len(tweet_text) > 280 else tweet_text
    except Exception as e:
        print(f"Tweet oluşturma hatası: {e}")
        return None

def post_tweet(news_item):
    try:
        if is_already_tweeted(news_item['title'], news_item['link']):
            print(f"⏩ Daha önce tweet atılmış: {news_item['title']}")
            return False

        tweet_text = create_tweet(news_item)
        if not tweet_text:
            return False

        response = client.create_tweet(text=tweet_text)
        if response.data['id']:
            print(f"✅ [{news_item['source']}] Tweet atıldı: {datetime.now().strftime('%H:%M:%S')}")
            save_tweeted_title(news_item['title'], news_item['link'])
            return True
        return False
    except tweepy.TweepyException as e:
        print(f"Tweet atma hatası: {e}")
        return False

def is_already_tweeted(title, link):
    if not os.path.exists(TWEETED_FILE):
        return False
    try:
        with open(TWEETED_FILE, 'r', encoding='utf-8') as file:
            for line in file:
                if '||' in line:
                    saved_title, saved_link = line.strip().split("||")
                    if saved_title == title or saved_link == link:
                        return True
    except Exception as e:
        print(f"Tweet kontrol hatası: {e}")
    return False

def save_tweeted_title(title, link):
    try:
        with open(TWEETED_FILE, 'a', encoding='utf-8') as file:
            file.write(f"{title}||{link}\n")
    except Exception as e:
        print(f"Tweet kaydetme hatası: {e}")

@app.route('/')
def index():
    return "Bitcoin Haber Botu Çalışıyor!"

@app.route('/start')
def start_bot():
    thread = Thread(target=run_bot, daemon=True)
    thread.start()
    return "🟢 Tweet botu başlatıldı."

def run_bot():
    while True:
        try:
            print(f"\n🔍 Haberler kontrol ediliyor: {datetime.now().strftime('%H:%M:%S')}")
            news_items = get_latest_news()

            if not news_items:
                print(f"⚠️ Haber bulunamadı. {datetime.now().strftime('%H:%M')}")
                time.sleep(3600)
                continue

            # Haberleri karıştır
            random.shuffle(news_items)

            for item in news_items:
                print(f"\n📰 [{item['source']}] Haber: {item['title']}")
                if post_tweet(item):
                    # Başarılı tweet sonrası 15-25 dakika bekle
                    wait_time = random.randint(900, 1500)
                    print(f"⏳ Sonraki tweet için {wait_time//60} dakika bekleniyor...")
                    time.sleep(wait_time)
                else:
                    # Başarısız tweet sonrası 5-10 dakika bekle
                    wait_time = random.randint(300, 600)
                    print(f"⏳ Sonraki deneme için {wait_time//60} dakika bekleniyor...")
                    time.sleep(wait_time)

        except Exception as e:
            print(f"🔴 Ana döngü hatası: {e}")
            time.sleep(3600)

@app.route('/debug')
def debug_feeds():
    output = []
    sources = {
        "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "Cointelegraph": "https://cointelegraph.com/rss"
    }

    for name, url in sources.items():
        output.append(f"<h2>🔍 {name}</h2>")
        try:
            feed = feedparser.parse(url)
            if hasattr(feed, 'status'):
                output.append(f"<p>📡 HTTP Durumu: {feed.status}</p>")
            if feed.bozo:
                output.append(f"<p style='color:red;'>❌ Hatalı RSS: {feed.bozo_exception}</p>")
                continue

            output.append(f"<p>📰 Başlık: {feed.feed.get('title', 'Yok')}</p>")
            output.append(f"<p>🗂️ Haber Sayısı: {len(feed.entries)}</p>")
            if feed.entries:
                entry = feed.entries[0]
                output.append(f"<p>✅ İlk Başlık: {entry.title}</p>")
                output.append(f"<p>🔗 Link: <a href='{entry.link}' target='_blank'>{entry.link}</a></p>")
                output.append(f"<p>🔄 Çeviri: {translate_to_turkish(entry.title)}</p>")
            else:
                output.append(f"<p>⚠️ Entry listesi boş.</p>")
        except Exception as e:
            output.append(f"<p style='color:red;'>🚨 Hata: {e}</p>")

    return Response("<br>".join(output), mimetype='text/html')

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)