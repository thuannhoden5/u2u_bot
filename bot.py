import requests
import feedparser
import json
import re
import time
import logging
from datetime import datetime
from pathlib import Path

TELEGRAM_BOT_TOKEN = "8780954709:AAHpwKc5Dbtpvkl9O83qhBb4YCpEf1JKxug"
TELEGRAM_CHAT_ID = "-1001987000275"
TELEGRAM_CHANNEL_ID = "u2u_xyzchat"
TWITTER_USERNAME = "u2u_xyzchat"
CHECK_INTERVAL = 300
POSTED_IDS_FILE = "posted_ids.json"
TRANSLATE_ENABLED = True

NITTER_INSTANCES = ["https://nitter.net","https://nitter.privacydev.net","https://nitter.poast.org","https://nitter.1d4.us"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.FileHandler("bot.log", encoding="utf-8"), logging.StreamHandler()])
log = logging.getLogger(__name__)

def load_posted_ids(): 
    return set(json.load(open(POSTED_IDS_FILE))) if Path(POSTED_IDS_FILE).exists() else set()

def save_posted_ids(ids): 
    open(POSTED_IDS_FILE, "w").write(json.dumps(list(ids)))

def translate_to_vietnamese(text):
    if not TRANSLATE_ENABLED or not text.strip(): 
        return text
    vietnamese_chars = set("àáâãèéêìíòóôõùúýăđơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ")
    if sum(1 for c in text.lower() if c in vietnamese_chars) > 5: 
        return text
    try:
        resp = requests.get("https://translate.googleapis.com/translate_a/single", params={"client":"gtx","sl":"auto","tl":"vi","dt":"t","q":text[:500]}, headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
        if resp.status_code == 200:
            result = resp.json()
            translated = "".join(item[0] for item in (result[0] if result and len(result) > 0 and len(result[0]) > 0 else []) if isinstance(item, (list, tuple)) and len(item) > 0)
            if translated and translated.strip(): 
                return translated.strip()
        return text
    except: 
        return text

def fetch_tweets():
    for instance in NITTER_INSTANCES:
        try:
            feed = feedparser.parse(f"{instance}/{TWITTER_USERNAME}/rss", request_headers={"User-Agent":"Mozilla/5.0"})
            if feed.entries: 
                log.info(f"  → Lấy được {len(feed.entries)} tweets")
                return feed.entries
        except: 
            pass
    return []

def extract_images(entry):
    try:
        raw_imgs = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', entry.get("summary", ""))
        result = []
        for img in raw_imgs:
            if "/pic/" in img:
                pic_part = requests.utils.unquote(img.split("/pic/")[-1]).split("?")[0]
                if not pic_part.startswith("http"): 
                    result.append(f"https://pbs.twimg.com/{pic_part}")
            elif img.startswith("http") and "pbs.twimg.com" in img: 
                result.append(img)
        return result
    except: 
        return []

def download_image(url):
    try:
        resp = requests.get(url, headers={"User-Agent":"Mozilla/5.0","Referer":"https://twitter.com/"}, timeout=10)
        if resp.status_code == 200 and "image" in resp.headers.get("content-type", ""):
            log.info(f"  Tải ảnh OK: {len(resp.content)//1024}KB")
            return resp.content
    except: 
        pass
    return None

def clean_html(text):
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()

def sanitize_telegram_html(text):
    text = re.sub(r'</?(?!b|strong|i|em|u|ins|s|strike|del|code|pre)[^>]*>', '', text)
    for tag in ['i', 'b', 'u', 's', 'em', 'strong', 'code', 'pre']:
        if len(re.findall(f'<{tag}(?:\\s[^>]*)?>|<{tag}>', text, re.IGNORECASE)) != len(re.findall(f'</{tag}>', text, re.IGNORECASE)):
            text = re.sub(f'</?{tag}(?:\\s[^>]*)?>|</{tag}>', '', text, flags=re.IGNORECASE)
    return text

def format_message(entry, translated, source="Twitter"):
    icon = "🐦" if source == "Twitter" else "💬"
    username = f"@{TWITTER_USERNAME}" if source == "Twitter" else f"@{TELEGRAM_CHANNEL_ID}"
    msg = f"{icon} <b>{username}</b>\n\n{clean_html(translated)}"
    return sanitize_telegram_html(msg)

def fetch_telegram_messages():
    try:
        resp = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates", timeout=10)
        if resp.status_code != 200: 
            return []
        updates = resp.json().get("result", [])
        messages = []
        for update in updates:
            msg = update.get("channel_post", {})
            if msg and msg.get("chat", {}).get("username") == TELEGRAM_CHANNEL_ID: 
                messages.append(msg)
        if messages: 
            log.info(f"  → Lấy được {len(messages)} message từ Telegram")
        return messages
    except: 
        return []

def format_telegram_message(msg):
    try:
        text, message_id, date = msg.get("text", msg.get("caption", "")), msg.get("message_id", ""), msg.get("date", int(time.time()))
        images = []
        if "photo" in msg: 
            images = [msg["photo"][-1].get("file_id", "")]
        elif "document" in msg and msg["document"].get("mime_type", "").startswith("image"): 
            images = [msg["document"].get("file_id", "")]
        return text, images, {"id":f"tg_{message_id}","link":f"https://t.me/{TELEGRAM_CHANNEL_ID}/{message_id}","summary":text,"published":datetime.fromtimestamp(date).strftime("%a, %d %b %Y %H:%M:%S +0000"),"source":"Telegram"}
    except: 
        return "", [], {}

def send_telegram(text, images=None):
    try:
        if not images:
            return _check(requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={"chat_id":TELEGRAM_CHAT_ID,"text":text,"parse_mode":"HTML","disable_web_page_preview":False}, timeout=10))
        img_bytes = [download_image(url) for url in images[:4] if isinstance(url, str) and url.startswith("http")]
        img_bytes = [x for x in img_bytes if x]
        if not img_bytes: 
            return _check(requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={"chat_id":TELEGRAM_CHAT_ID,"text":text,"parse_mode":"HTML"}, timeout=10))
        caption = text[:1024]
        if len(img_bytes) == 1:
            return _check(requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto", data={"chat_id":TELEGRAM_CHAT_ID,"caption":caption,"parse_mode":"HTML"}, files={"photo":("photo.jpg",img_bytes[0],"image/jpeg")}, timeout=20))
        files, media = {}, []
        for i, img_data in enumerate(img_bytes):
            key = f"photo{i}"
            files[key] = (f"photo{i}.jpg", img_data, "image/jpeg")
            item = {"type":"photo","media":f"attach://{key}"}
            if i == 0: 
                item.update({"caption":caption,"parse_mode":"HTML"})
            media.append(item)
        return _check(requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMediaGroup", data={"chat_id":TELEGRAM_CHAT_ID,"media":json.dumps(media)}, files=files, timeout=30))
    except Exception as e:
        log.error(f"Lỗi gửi Telegram: {e}")
        return False

def _check(resp):
    if resp.status_code == 200:
        result = resp.json()
        if result.get("ok"): 
            return True
        log.error(f"Telegram API error: {result.get('description')}")
    else: 
        log.error(f"Telegram HTTP {resp.status_code}: {resp.text[:300]}")
    return False

def run():
    log.info("="*60)
    log.info("Bot X2Telegram + TG Channel → Bản tin U2U")
    log.info("="*60)
    log.info(f"📍 Twitter: @{TWITTER_USERNAME}")
    log.info(f"📍 Fetch từ: @{TELEGRAM_CHANNEL_ID}")
    log.info(f"📍 Post vào: {TELEGRAM_CHAT_ID}")
    log.info(f"🌐 Mode: Chỉ tiếng Việt (Google Translate)")
    log.info(f"⏱️ Tần suất: {CHECK_INTERVAL}s/lần")
    log.info("="*60)
    posted_ids = load_posted_ids()
    log.info(f"📜 Lịch sử: {len(posted_ids)} item đã đăng\n")
    while True:
        try:
            all_items = []
            log.info("🐦 Fetching Twitter...")
            for entry in fetch_tweets():
                tweet_id = entry.get("id", entry.get("link", ""))
                if tweet_id not in posted_ids and not entry.get("title", "").startswith("RT by"):
                    entry["source"] = "Twitter"
                    all_items.append(entry)
            log.info("💬 Fetching Telegram Channel...")
            for msg in fetch_telegram_messages():
                text, images, entry = format_telegram_message(msg)
                if entry and entry.get("id") not in posted_ids:
                    entry["images"] = images
                    all_items.append(entry)
            new_count = 0
            log.info(f"📤 Processing {len(all_items)} items...\n")
            for entry in reversed(all_items):
                item_id, source = entry.get("id", ""), entry.get("source", "Unknown")
                if item_id in posted_ids: 
                    continue
                original = clean_html(entry.get("summary", ""))
                if not original.strip(): 
                    continue
                translated = translate_to_vietnamese(original)
                log.info(f"✓ Dịch: {original[:50]}...")
                text = format_message(entry, translated, source=source)
                images = entry.get("images", extract_images(entry)) if source == "Twitter" else []
                if send_telegram(text, images):
                    posted_ids.add(item_id)
                    save_posted_ids(posted_ids)
                    new_count += 1
                    img_info = f"({len(images)} ảnh)" if images else "(text)"
                    log.info(f"✅ Posted [{source}]: {item_id} {img_info}")
                else: 
                    log.warning(f"❌ Gửi thất bại: {item_id}")
            log.info(f"\n{'✨ Đăng '+str(new_count)+' item mới' if new_count else '⏸️ Không có item mới'}\n")
        except Exception as e: 
            log.error(f"❌ Lỗi: {e}")
        log.info(f"⏳ Chờ {CHECK_INTERVAL}s...\n")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__": 
    run()
