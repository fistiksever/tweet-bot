#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import Flask
import os
import re
import random
import time
from datetime import datetime, timezone
from deep_translator import GoogleTranslator
import feedparser
import tweepy
from dotenv import load_dotenv
from threading import Thread
import sqlite3
import requests
from bs4 import BeautifulSoup
from unidecode import unidecode
import traceback
from urllib.parse import urljoin  # Görsel URL'leri için

# Flask uygulamasını başlat
app = Flask(__name__)
load_dotenv()

# --- KONFİGÜRASYON ---
# Twitter API v2 (Tweet atmak için)
try:
    client = tweepy.Client(
        consumer_key=os.getenv('CONSUMER_KEY'),
        consumer_secret=os.getenv('CONSUMER_SECRET'),
        access_token=os.getenv('ACCESS_TOKEN'),
        access_token_secret=os.getenv('ACCESS_TOKEN_SECRET'),
        wait_on_rate_limit=True)
    print("✅ Twitter API v2 başarıyla yapılandırıldı")
except Exception as e:
    print(f"❌ Twitter API v2 hatası: {str(e)}")
    client = None

# Twitter API v1.1 (Medya yüklemek için)
try:
    auth = tweepy.OAuth1UserHandler(os.getenv('CONSUMER_KEY'),
                                    os.getenv('CONSUMER_SECRET'),
                                    os.getenv('ACCESS_TOKEN'),
                                    os.getenv('ACCESS_TOKEN_SECRET'))
    api_v1 = tweepy.API(auth)
    print("✅ Twitter API v1.1 (medya için) başarıyla yapılandırıldı")
except Exception as e:
    print(f"❌ Twitter API v1.1 hatası: {str(e)}")
    api_v1 = None

# Veritabanı
DB_PATH = 'tweets.db'  # Render için: os.path.join(os.environ.get('RENDER_DISK_MOUNT_PATH', '.'), 'tweets.db')


def init_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS tweets
                    (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    link TEXT UNIQUE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()
        conn.close()
        print(f"✅ Veritabanı ({DB_PATH}) başarıyla kuruldu/kontrol edildi")
    except Exception as e:
        print(f"❌ Veritabanı hatası: {str(e)}")


init_db()


# --- YARDIMCI FONKSİYONLAR ---
def clean_title_text(text_input):
    """Metni temizle: HTML entity'leri ve özel karakterleri kaldır.
    Bu fonksiyon özellikle başlıkları temizlemek için daha agresif olabilir.
    """
    if not text_input or not isinstance(text_input, str):
        return ""

    text = text_input

    # 1. Temel HTML entity'leri
    replacements = {
        " ": " ",
        "&": "&",
        "\"": '"',
        "'": "'",
        "'": "'",
        "<": "<",
        ">": ">",
        "«": "«",
        "»": "»",
        "–": "-",
        "—": "—",
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "…": "...",
    }
    for entity, char in replacements.items():
        text = text.replace(entity, char)

    # 2. Unicode kıvrımlı tırnakları ve diğerlerini düzelt
    text = re.sub(r'[“”]', '"', text)
    text = re.sub(r'[‘’]', "'", text)
    text = re.sub(r'[–—]', "-", text)  # En dash, em dash

    # 3. Unidecode (dikkatli kullanılmalı, çeviriyi etkileyebilir)
    try:
        text_unidecoded = unidecode(text)
        # Unidecode bazen çok fazla karakteri (?) ile değiştirebilir, kontrol edelim
        if text_unidecoded.count(
                '?') < len(text_unidecoded
                           ) / 2:  # Eğer yarısından fazlası ? değilse kullan
            text = text_unidecoded
    except Exception as e:
        print(f"⚠️ Unidecode hatası: {e} - Metin: {text[:50]}")
        pass  # Unidecode başarısız olursa orijinal metinle devam et

    # 4. Kalan istenmeyen karakterleri temizle (çeviriye uygun hale getirme)
    text = re.sub(r'[^\w\s.,!?$%&\'():/\-]', ' ',
                  text)  # Ek olarak / ve - karakterlerine izin verildi.

    # 5. Fazla boşlukları ve satır başı/sonu boşluklarını temizle
    text = ' '.join(text.split())
    return text.strip()


def translate_text_robust(text_to_translate, target_lang='tr'):
     # <<< HATA DÜZELTİLDİ: ''' yerine """ kullanıldı
    if not text_to_translate or not isinstance(text_to_translate, str):
        return ""  # Boş veya string olmayan girdi için boş döndür

    cleaned_text = clean_title_text(text_to_translate)  # Önce temizle
    if not cleaned_text:  # Temizleme sonrası boşsa
        return ""

    try:
        # GoogleTranslator API'sinin karakter limiti olabilir, 4500 makul bir üst sınır.
        translated = GoogleTranslator(
            source='auto', target=target_lang).translate(cleaned_text[:4500])
        return translated if translated and isinstance(translated,
                                                       str) else cleaned_text
    except Exception as e:
        print(
            f"❌ Çeviri hatası ({target_lang}): {str(e)} - Orijinal (temizlenmiş): {cleaned_text[:100]}"
        )
        return cleaned_text  # Hata durumunda temizlenmiş orijinal metni döndür


def get_article_image(url):
    try:
        headers = {
            'User-Agent':
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept':
            'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,tr;q=0.8',
        }
        response = requests.get(url,
                                headers=headers,
                                timeout=20,
                                allow_redirects=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # Öncelikli meta tag'ler
        selectors = [
            {
                'property': 'og:image:secure_url'
            },
            {
                'property': 'og:image'
            },
            {
                'name': 'twitter:image:src'
            },  # Bazen :src eklenir
            {
                'name': 'twitter:image'
            },
            {
                'itemprop': 'image'
            }
        ]
        for sel_attrs in selectors:
            tag = soup.find('meta', attrs=sel_attrs)
            if tag and tag.get('content') and tag['content'].strip():
                img_url = tag['content'].strip()
                return urljoin(url, img_url)  # Göreceli URL'leri düzelt

        # Kaynağa özel img tag seçicileri
        img_tag_selectors = []
        if "cointelegraph.com" in url:
            img_tag_selectors.extend([
                {
                    'class_': 'post-cover__image'
                },
                {
                    'class_': 'article__header-image'
                }  # Cointelegraph yeni class
            ])
        elif "coindesk.com" in url:
            img_tag_selectors.extend([
                {
                    'class_': ['hero__image-img', 'Box-sc-1hpkeeg-0']
                },  # Coindesk yeni class'lar
                {
                    'class_': 'magnifier-image'
                },
                {
                    'class_': 'wp-post-image'
                }  # Wordpress genel
            ])

        for sel_attrs in img_tag_selectors:
            tag = soup.find('img', attrs=sel_attrs)
            if tag and tag.get('src') and tag['src'].strip():
                img_url = tag['src'].strip()
                if not img_url.startswith('data:image'):  # data URI'ları atla
                    return urljoin(url, img_url)
        return None
    except requests.exceptions.RequestException as e:
        print(f"❌ Görsel çekme (request) hatası ({url}): {str(e)}")
    except Exception as e:
        print(f"❌ Görsel çekme (parsing) hatası ({url}): {str(e)}")
    return None


# --- ÇEKİRDEK FONKSİYONLAR ---
def get_latest_news():
    sources = {
        "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "Cointelegraph": "https://cointelegraph.com/rss",
    }
    all_news = []
    for name, url in sources.items():
        try:
            print(f"🔍 {name} kaynağından haberler çekiliyor ({url})...")
            feed = feedparser.parse(
                url,
                agent=
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            )

            if feed.bozo:
                bozo_exception_str = "Bilinmeyen RSS ayrıştırma sorunu"
                if hasattr(feed, 'bozo_exception') and feed.bozo_exception:
                    try:
                        bozo_exception_str = repr(feed.bozo_exception)
                    except Exception:
                        bozo_exception_str = f"Bozo exception (repr alınamadı): {type(feed.bozo_exception).__name__}"
                print(
                    f"⚠️ {name} RSS'i 'bozo' olarak işaretlendi: {bozo_exception_str}. Entry'ler yine de kontrol edilecek."
                )

            if not feed.entries:
                print(
                    f"ℹ️ {name} kaynağından hiç entry (haber başlığı) bulunamadı."
                )
                continue

            print(f"ℹ️ {name} için {len(feed.entries)} entry bulundu.")

            for i, entry in enumerate(feed.entries[:7]):
                if not (hasattr(entry, 'title') and entry.title and isinstance(
                        entry.title, str) and hasattr(entry, 'link')
                        and entry.link and isinstance(entry.link, str)):
                    print(
                        f"⏩ {name} kaynağından eksik veya geçersiz tipte bilgi içeren haber atlanıyor (Entry index: {i})."
                    )
                    continue

                # Başlık temizleme ve çeviri
                original_title = clean_title_text(entry.title)
                if not original_title:
                    print(
                        f"⏩ {name} kaynağından başlık temizleme sonrası boş kaldı (Entry index: {i})."
                    )
                    continue

                translated_title = translate_text_robust(original_title)
                if not translated_title:
                    print(
                        f"⏩ {name} kaynağından çeviri sonrası başlık boş kaldı, orijinal temizlenmiş başlık kullanılacak (Entry index: {i})."
                    )
                    translated_title = original_title

                link_to_use = entry.link.split('?')[0].strip()

                published_time = None
                if hasattr(entry,
                           'published_parsed') and entry.published_parsed:
                    published_time = datetime.fromtimestamp(time.mktime(
                        entry.published_parsed),
                                                            tz=timezone.utc)
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    published_time = datetime.fromtimestamp(time.mktime(
                        entry.updated_parsed),
                                                            tz=timezone.utc)
                else:
                    published_time = datetime.now(timezone.utc)

                all_news.append({
                    'source': name,
                    'original_title': original_title,
                    'title': translated_title,
                    'link': link_to_use,
                    'published': published_time
                })
        except Exception as e:
            error_type_name = type(e).__name__
            error_repr = repr(e)
            print(
                f"❌ {name} haber çekme hatası (ana try-except). Tip: {error_type_name}, Detaylar (repr): {error_repr}"
            )
            print("--- TRACEBACK BAŞLANGICI (get_latest_news) ---")
            traceback.print_exc()
            print("--- TRACEBACK SONU (get_latest_news) ---")

    if not all_news:
        print("ℹ️ Döngü sonunda hiçbir kaynaktan haber çekilemedi.")
        return None

    all_news.sort(key=lambda x: x['published'], reverse=True)
    print(f"📰 Toplam {len(all_news)} adet haber işlendi ve sıralandı.")
    return all_news


def is_already_tweeted(link):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT 1 FROM tweets WHERE link=?", (link, ))
        exists = c.fetchone() is not None
        conn.close()
        return exists
    except Exception as e:
        print(f"❌ Veritabanı okuma hatası (is_already_tweeted): {e}")
        return True


def save_tweeted(title, link):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO tweets (title, link) VALUES (?, ?)",
                  (title, link))
        conn.commit()
        conn.close()
        print(f"💾 Veritabanına kaydedildi: {link}")
    except sqlite3.IntegrityError:
        print(f"⚠️ Bu haber zaten kayıtlı (IntegrityError): {link}")
    except Exception as e:
        print(f"❌ Veritabanı yazma hatası (save_tweeted): {e}")


def create_tweet_text(news_item):
    source_tags_map = {
        "CoinDesk": ["#CoinDesk", "#KriptoHaber", "#KriptoPara"],
        "Cointelegraph": ["#Cointelegraph", "#BlockchainHaberleri", "#Kripto"],
    }
    source_tags = source_tags_map.get(news_item['source'], [])
    general_tags = [
        "#Bitcoin", "#BTC", "#Kripto", "#Ekonomi", "#Finans", "#Yatırım",
        "#Teknoloji", "#Altcoin"
    ]

    num_source_tags = random.randint(1, min(
        2, len(source_tags))) if source_tags else 0
    num_general_tags = random.randint(1, min(3, len(general_tags)))

    chosen_source_tags = random.sample(source_tags, num_source_tags)
    chosen_general_tags = random.sample(general_tags, num_general_tags)

    all_tags = list(set(chosen_source_tags + chosen_general_tags))
    if len(all_tags) > 4:
        all_tags = random.sample(all_tags, 4)
    random.shuffle(all_tags)

    title_prefixes = ["", "📰 ", "⚡️ ", "💡 ", "🚀 ", "🔔 ", "📢 "]
    news_emojis = ["📉", "📈", "📊", "🧐", "📌", "🔍", "🌐", "🔥", "✨"]

    chosen_prefix = random.choice(title_prefixes)
    chosen_emoji = random.choice(news_emojis)

    display_title = news_item['title']

    max_title_len = 190

    full_title_part = f"{chosen_prefix}{display_title} {chosen_emoji}"
    if len(full_title_part) > max_title_len:
        cut_amount = len(full_title_part) - (max_title_len - 3)
        display_title_cut = display_title[:len(
            display_title) - cut_amount] if len(
                display_title) - cut_amount > 0 else display_title[:10]
        full_title_part = f"{chosen_prefix}{display_title_cut}... {chosen_emoji}"

    tweet_text = (f"{full_title_part}\n\n"
                  f"🔗 {news_item['link']}\n\n"
                  f"{' '.join(all_tags)}")

    while len(tweet_text) > 280:
        if len(all_tags) > 1:
            tweet_text = tweet_text.replace(" " + all_tags.pop(), "", 1)
        elif len(display_title) > 30:
            current_title_len = len(display_title)
            new_title_len = current_title_len - (len(tweet_text) - 280) - 5
            if new_title_len < 20:
                new_title_len = 20
            display_title = display_title[:new_title_len] + "..."
            full_title_part = f"{chosen_prefix}{display_title} {chosen_emoji}"
            tweet_text = (f"{full_title_part}\n\n"
                          f"🔗 {news_item['link']}\n\n"
                          f"{' '.join(all_tags)}")
        else:
            break

    return tweet_text[:280]


def post_tweet(news_item):
    if not client or not api_v1:
        print("❌ Twitter API bağlantısı (v1 veya v2) eksik.")
        return False
    try:
        if is_already_tweeted(news_item['link']):
            print(f"⏩ Daha önce tweetlenmiş (veritabanı): {news_item['link']}")
            return False

        tweet_text_content = create_tweet_text(news_item)
        if not tweet_text_content:
            print("❌ Tweet metni oluşturulamadı.")
            return False

        print(
            f"\nℹ️ Tweet denemesi ({datetime.now().strftime('%H:%M:%S')}):\n{tweet_text_content}"
        )

        media_id_str = None
        image_url = get_article_image(news_item['link'])

        if image_url:
            print(f"🖼️ Görsel bulundu: {image_url}")
            try:
                img_response = requests.get(image_url, timeout=30, stream=True)
                img_response.raise_for_status()

                temp_filename = "temp_media_twitter"
                content_type = img_response.headers.get('content-type',
                                                        '').lower()
                if 'jpeg' in content_type or 'jpg' in content_type:
                    temp_filename += ".jpg"
                elif 'png' in content_type:
                    temp_filename += ".png"
                elif 'gif' in content_type:
                    temp_filename += ".gif"
                elif 'webp' in content_type:
                    temp_filename += ".webp"
                else:
                    temp_filename += ".jpg" # Varsayılan

                # Render gibi ortamlarda /tmp genellikle yazılabilir bir geçici dizindir
                temp_media_path = os.path.join('/tmp', temp_filename) 

                with open(temp_media_path, 'wb') as f:
                    for chunk in img_response.iter_content(chunk_size=8192):
                        f.write(chunk)

                file_size = os.path.getsize(temp_media_path)
                if file_size > 5 * 1024 * 1024: # Twitter görsel limiti (yaklaşık)
                    print(
                        f"⚠️ Görsel boyutu çok büyük ({file_size / (1024*1024):.2f} MB). Yüklenemeyebilir. Atlanıyor."
                    )
                    media_id_str = None
                    os.remove(temp_media_path)
                else:
                    media = api_v1.media_upload(filename=temp_media_path)
                    media_id_str = media.media_id_string
                    print(
                        f"🖼️ Görsel Twitter'a yüklendi, Media ID: {media_id_str}"
                    )
                    os.remove(temp_media_path)
            except requests.exceptions.SSLError as ssl_err:
                print(
                    f"⚠️ Görsel SSL hatası ({image_url}): {ssl_err}. Sadece metin."
                )
            except Exception as e:
                print(
                    f"⚠️ Görsel işleme/yükleme hatası ({image_url}): {str(e)}. Sadece metin."
                )
        else:
            print(
                "🖼️ Görsel bulunamadı veya uygun değil, sadece metin tweeti.")

        if media_id_str:
            response = client.create_tweet(text=tweet_text_content,
                                           media_ids=[media_id_str])
        else:
            response = client.create_tweet(text=tweet_text_content)

        if response and response.data and response.data.get('id'):
            print(
                f"✅ Tweet atıldı! ID: {response.data['id']} - {news_item['link']}"
            )
            save_tweeted(news_item['original_title'], news_item['link'])
            return True
        else:
            error_msg = "Bilinmeyen API hatası."
            if response and response.errors:
                error_msg = f"API Yanıtı: {response.errors}"
                for error in response.errors:
                    if isinstance(error,
                                  dict) and (error.get("code") == 187 # v1.1 duplicate error
                                             or "duplicate" in error.get( # v2 duplicate error
                                                 "message", "").lower()):
                        print(
                            "🐦 API tarafından duplicate olarak işaretlendi. Veritabanına kaydediliyor."
                        )
                        save_tweeted(news_item['original_title'],
                                     news_item['link'])
                        # Duplicate durumunda da başarılı sayılabilir (amaç tekrar denememek)
                        # Ancak ana döngü için False dönmek daha iyi olabilir ki bir sonraki habere geçsin.
                        # Bu botun mantığına göre duplicate'i false dönmek doğru.
                        break 
            print(f"❌ Tweet atılamadı. {error_msg}")
            return False

    except tweepy.TweepyException as e:
        print(f"❌ Twitter API Hatası (tweepy.TweepyException): {e}")
        if e.response is not None:
            status_code = e.response.status_code
            print(f"API Hata Kodu: {status_code}")
            try:
                error_details = e.response.json()
                print(f"API Hata Detayları: {error_details}")
                detail_msg = error_details.get('detail', '').lower()
                title_error = error_details.get('title', '').lower() # Bazı v2 hatalarında

                # Duplicate content (API v2)
                if status_code == 403 and ("duplicate" in detail_msg or "duplicate" in title_error or "You are not allowed to create a Tweet with duplicate content" in detail_msg):
                    print(
                        "🐦 Zaten tweetlenmiş (API 403 Duplicate). Veritabanına kaydediliyor."
                    )
                    save_tweeted(news_item['original_title'],
                                 news_item['link'])
                elif status_code == 403 and ("User is over daily status update limit" in detail_msg or "tweet limit" in detail_msg):
                     print("🚫 Günlük tweet limiti aşıldı (API 403). Uzun süre beklenecek.")
                     time.sleep(random.randint(7200, 10800)) # 2-3 saat bekle
                elif status_code == 403: # Diğer 403 hataları
                    print(f"🚫 Yasaklı işlem (API 403): {error_details}. Bu haber atlanıyor ve kaydediliyor.")
                    save_tweeted(news_item['original_title'], news_item['link'])
                elif status_code == 429: # Rate limit
                    print(
                        "🚫 Rate limit aşıldı (API 429). Client'in otomatik beklemesi (wait_on_rate_limit=True) devrede olmalı."
                    )
                    # Ekstra bekleme eklenebilir, ama client halletmeli
            except requests.exceptions.JSONDecodeError:
                # API'den JSON olmayan bir yanıt gelirse (nadiren)
                print(f"API Hata Detayı (Non-JSON): {e.response.text}")
                if "duplicate content" in e.response.text.lower(): # Metin içinde arama
                    print("🐦 Zaten tweetlenmiş (API 403 Duplicate - text match). Veritabanına kaydediliyor.")
                    save_tweeted(news_item['original_title'], news_item['link'])
        # Duplicate content (API v1.1)
        elif hasattr(e, 'api_codes') and 187 in e.api_codes: # Status is a duplicate
            print("🐦 Zaten tweetlenmiş (API V1 Kod 187). Veritabanına kaydediliyor.")
            save_tweeted(news_item['original_title'], news_item['link'])
        # Genel duplicate mesajı kontrolü
        elif "duplicate" in str(e).lower():
            print("🐦 Zaten tweetlenmiş (Genel Hata Metni). Veritabanına kaydediliyor.")
            save_tweeted(news_item['original_title'], news_item['link'])
        return False # Hata durumunda False dön
    except Exception as e:
        print(f"❌ Tweet atma sırasında beklenmeyen genel hata: {str(e)}")
        print("--- TRACEBACK BAŞLANGICI (post_tweet) ---")
        traceback.print_exc()
        print("--- TRACEBACK SONU (post_tweet) ---")
        return False


# --- BOT ANA DÖNGÜSÜ ---
TWEET_SUCCESS_WAIT_MIN = 45 * 60
TWEET_SUCCESS_WAIT_MAX = 80 * 60
TWEET_FAIL_WAIT_MIN = 30 * 60  # Bir sonraki habere geçmeden önceki bekleme
TWEET_FAIL_WAIT_MAX = 50 * 60
NO_NEWS_WAIT_MIN = 55 * 60
NO_NEWS_WAIT_MAX = 75 * 60
CRITICAL_ERROR_WAIT_MIN = 60 * 60
CRITICAL_ERROR_WAIT_MAX = 100 * 60


def run_bot():
    print(f"🤖 Bot başlatıldı ({datetime.now().strftime('%d.%m.%Y %H:%M:%S')})")
    tweet_counter = 0
    max_tweets_per_cycle = 2 # Ana döngü başına atılacak maksimum tweet sayısı

    while True:
        try:
            current_time_str = datetime.now().strftime('%d.%m.%Y %H:%M:%S')
            print(f"\n🔄 {current_time_str} - Haberler kontrol ediliyor...")

            all_available_news = get_latest_news()

            if not all_available_news:
                wait_time = random.randint(NO_NEWS_WAIT_MIN, NO_NEWS_WAIT_MAX)
                print(
                    f"⚠️ Haber bulunamadı. {wait_time//60} dakika bekleniyor..."
                )
                time.sleep(wait_time)
                continue

            posted_in_this_cycle_count = 0
            for news_item_data in all_available_news:
                if posted_in_this_cycle_count >= max_tweets_per_cycle:
                    print(
                        f"🌀 Bu döngü için tweet atma limiti ({max_tweets_per_cycle}) doldu. Bir sonraki ana döngü bekleniyor."
                    )
                    break # İç döngüden çık, ana döngü beklemesine git

                print(
                    f"📰 Kontrol ediliyor: {news_item_data.get('title', 'Başlık Yok')[:60]}... ({news_item_data.get('link', 'Link Yok')})"
                )

                tweet_successful = post_tweet(news_item_data)

                if tweet_successful:
                    tweet_counter += 1
                    posted_in_this_cycle_count += 1
                    # Başarılı tweet sonrası, bir sonraki tweet denemesi için uzun bekleme
                    wait_time = random.randint(TWEET_SUCCESS_WAIT_MIN,
                                               TWEET_SUCCESS_WAIT_MAX)
                    print(
                        f"✅ Başarılı tweet #{tweet_counter}. Bir sonraki işlem için ~{wait_time//60} dakika bekleniyor..."
                    )
                    time.sleep(wait_time)
                else:
                    # Başarısız/atlanan tweet sonrası, bir sonraki habere geçmeden önce kısa bekleme
                    # Bu, API'yi boğmamak veya aynı hatayı tekrar tekrar yaşamamak için
                    fail_wait_time = random.randint(5 * 60, 10 * 60) # 5-10 dk
                    print(
                        f"🔻 Tweet atılamadı/atlandı. Bir sonraki habere geçmeden önce ~{fail_wait_time//60} dakika bekleniyor..."
                    )
                    time.sleep(fail_wait_time)

            # Tüm haberler işlendikten veya max_tweets_per_cycle dolduktan sonra
            # bir sonraki ana haber kontrol döngüsü için bekleme
            if posted_in_this_cycle_count < max_tweets_per_cycle:
                print(f"ℹ️ Bu döngüde ({posted_in_this_cycle_count}/{max_tweets_per_cycle}) tweet atıldı. Mevcut haberler bitti veya atlandı.")

            overall_cycle_wait = random.randint(NO_NEWS_WAIT_MIN, NO_NEWS_WAIT_MAX)
            print(f"⏳ Ana döngü tamamlandı. ~{overall_cycle_wait//60} dakika sonra tekrar haber kontrol edilecek.")
            time.sleep(overall_cycle_wait)

        except Exception as e:
            print(f"🔴 Kritik hata ana döngüde (run_bot): {str(e)}")
            print("--- TRACEBACK BAŞLANGICI (run_bot) ---")
            traceback.print_exc()
            print("--- TRACEBACK SONU (run_bot) ---")
            critical_wait_time = random.randint(CRITICAL_ERROR_WAIT_MIN,
                                                CRITICAL_ERROR_WAIT_MAX)
            print(
                f"💣 Kritik hata sonrası ~{critical_wait_time//60} dakika bekleniyor..."
            )
            time.sleep(critical_wait_time)


# --- FLASK ENDPOINT'LERİ ---
@app.route('/')
def home():
    status_info = "Beklemede"
    if hasattr(app, 'bot_thread') and app.bot_thread.is_alive():
        status_info = "Aktif ve Çalışıyor"
    return f"🚀 Bitcoin Haber Botu Durumu: {status_info}! (Render/UptimeRobot için)"


@app.route('/start_bot_manual')
def start_bot_endpoint():
    if not hasattr(app, 'bot_thread') or not app.bot_thread.is_alive():
        print("⚙️ /start_bot_manual endpoint'i üzerinden bot başlatılıyor...")
        app.bot_thread = Thread(target=run_bot, daemon=True)
        app.bot_thread.start()
        return "🟢 Bot başlatıldı!"
    return "⚠️ Bot zaten çalışıyor."


@app.route('/debug_info')
def debug_info():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM tweets")
        tweet_db_count = c.fetchone()[0]
        c.execute(
            "SELECT title, link, created_at FROM tweets ORDER BY created_at DESC LIMIT 5"
        )
        last_tweets_raw = c.fetchall()
        conn.close()

        last_tweets_formatted = []
        for t_row in last_tweets_raw:
            last_tweets_formatted.append({
                "title": t_row[0],
                "link": t_row[1],
                "time": t_row[2]
            })

        return {
            "bot_status":
            "Çalışıyor" if hasattr(app, 'bot_thread')
            and app.bot_thread.is_alive() else "Durdu",
            "total_tweets_in_db":
            tweet_db_count,
            "last_5_tweets_in_db":
            last_tweets_formatted,
            "current_server_time_utc":
            datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z')
        }
    except Exception as e:
        return {"error": str(e)}, 500


# --- UYGULAMA BAŞLATMA ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"🌐 Uygulama {port} portunda başlatılıyor...")
    if not (hasattr(app, 'bot_thread') and app.bot_thread.is_alive()):
        print("⚙️ Ana uygulama başlatılırken bot da başlatılıyor...")
        app.bot_thread = Thread(target=run_bot, daemon=True)
        app.bot_thread.start()
        print("🟢 Bot arka planda çalışmaya başladı.")
    app.run(host="0.0.0.0", port=port, debug=False)