from flask import Flask, jsonify, render_template, request
import feedparser
from datetime import datetime
import pytz
import time
import threading

app = Flask(__name__)

# Storage for articles
article_storage = []

# List of RSS feed URLs
rss_feeds = [
    "https://finance.yahoo.com/news/rss",
    "https://www.investing.com/rss/market_overview_investing_ideas.rss",
    "https://www.investing.com/rss/market_overview_Opinion.rss",
    "https://www.investing.com/rss/market_overview_Fundamental.rss",
    "https://www.investing.com/rss/market_overview_Technical.rss",
    "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258",
    "https://feeds.content.dowjones.io/public/rss/socialeconomyfeed",
    "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
    "https://seekingalpha.com/market_currents.xml",
    "https://ir.nasdaq.com/rss/news-releases.xml?items=15",
    "https://ir.nasdaq.com/rss/news-releases.xml?items=15&category=Financial",
    "https://feeds.content.dowjones.io/public/rss/mw_bulletins",
    #"https://lorem-rss.herokuapp.com/feed",
]

# Fetch and parse RSS feeds
def fetch_articles():
    global article_storage
    today_utc = datetime.now(pytz.utc).date()
    new_articles = []

    for url in rss_feeds:
        try:
            print(f"Fetching from: {url}")
            feed = feedparser.parse(url)
            for entry in feed.entries:
                if hasattr(entry, 'published'):
                    publish_date = None
                    date_formats = [
                        "%Y-%m-%dT%H:%M:%SZ",
                        "%b %d, %Y %H:%M %Z",
                        "%b %d, %Y %H:%M:%S %Z",
                        "%a, %d %b %Y %H:%M:%S %z",
                        "%a, %d %b %Y %H:%M:%S %Z",
                        "%Y-%m-%d %H:%M:%S",
                        "%a, %d %b %Y %H:%M:%S GMT",
                    ]

                    for date_format in date_formats:
                        try:
                            publish_date = datetime.strptime(entry.published, date_format).replace(tzinfo=pytz.UTC).date()
                            break
                        except ValueError:
                            continue

                    if publish_date is None:
                        print(f"Date parsing error for entry: {entry.title}. Date: {entry.published}")
                        continue

                    if publish_date == today_utc:
                        if not any(article['title'] == entry.title for article in article_storage):
                            new_articles.append({"title": entry.title, "link": entry.link, "published": entry.published})
                            print(f"Added article: {entry.title}")

        except Exception as e:
            print(f"Error fetching from {url}: {e}")

    if new_articles:
        article_storage.extend(new_articles)
        print(f"Total articles stored: {len(article_storage)}")

# Background thread to continuously fetch articles
def update_articles():
    while True:
        fetch_articles()
        time.sleep(5)  # Update frequency: 5 seconds

# Reset articles at UTC midnight
def reset_storage():
    global article_storage
    print("Resetting function: On")
    current_date = datetime.now(pytz.utc).date()
    
    while True:
        now_utc = datetime.now(pytz.utc)
        if now_utc.date() != current_date:
            article_storage = []
            print(f"UTC Date changed from {current_date} to {now_utc.date()}: Resetting Article Storage")
            current_date = now_utc.date()
        
        time.sleep(60)  # Check every minute

# API to get stored articles (JSON response)
@app.route("/api/articles", methods=["GET"])
def get_articles():
    user_timezone = request.args.get("timezone", "UTC")
    tz = pytz.timezone(user_timezone)
    formatted_articles = []
    
    date_formats = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%b %d, %Y %H:%M %Z",
        "%b %d, %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%d %H:%M:%S",
        "%a, %d %b %Y %H:%M:%S GMT",
    ]

    for article in article_storage:
        dt = None
        for date_format in date_formats:
            try:
                dt = datetime.strptime(article["published"], date_format).replace(tzinfo=pytz.UTC)
                break
            except ValueError:
                continue
        
        if dt is None:
            print(f"Error parsing date for article: {article['title']}")
            continue

        formatted_article = article.copy()
        formatted_article["published"] = dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")
        formatted_article["datetime"] = dt.timestamp()  # Use timestamp for sorting
        formatted_articles.append(formatted_article)

    # Sort articles by datetime, most recent first
    sorted_articles = sorted(formatted_articles, key=lambda x: x["datetime"], reverse=True)

    # Remove the datetime key from the articles before returning
    for article in sorted_articles:
        del article["datetime"]

    return jsonify(sorted_articles)



# Serve the frontend
@app.route("/")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    # Start background threads
    threading.Thread(target=update_articles, daemon=True).start()
    threading.Thread(target=reset_storage, daemon=True).start()
    app.run(host='0.0.0.0', port=8000, debug=True)

