from flask import Flask, jsonify, render_template, request
from collections import deque
import feedparser
from datetime import datetime, timedelta
import pytz
import time
import threading
import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry
import numpy as np
import math
import random
import os
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient, OptionHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, OptionBarsRequest
from alpaca.data.timeframe import TimeFrame

load_dotenv()

app = Flask(__name__)

# Storage for articles
MAX_ARTICLES = 1000
article_storage = deque(maxlen=MAX_ARTICLES)

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
]

# Alpaca API credentials
ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY")

if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
    print("WARNING: You must set the ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables for real data.")

# Initialize Alpaca clients
trading_client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=False)
stock_client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
options_client = OptionHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)

def requests_retry_session(retries=3, backoff_factor=0.3):
    session = requests.Session()
    retry = Retry(total=retries, backoff_factor=backoff_factor)
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

# Fetch and parse RSS feeds
def fetch_articles():
    global article_storage
    while True:
        today_utc = datetime.now(pytz.utc).date()
        new_articles = []

        for url in rss_feeds:
            try:
                print(f"Fetching from: {url}")
                response = requests_retry_session().get(url, timeout=10)
                feed = feedparser.parse(url)
                for entry in feed.entries:
                    if hasattr(entry, 'published'):
                        publish_date = None
                        date_formats = [
                            "%Y-%m-%dT%H:%M:%SZ",
                            "%b %d, %Y %H:%M %Z",
                            "%b %d, %Y H:%M:%S %Z",
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

        time.sleep(5)  # Update frequency: 5 seconds

# Reset articles at UTC midnight
def reset_storage():
    global article_storage
    print("Resetting function: On")
    current_date = datetime.now(pytz.utc).date()
    
    while True:
        now_utc = datetime.now(pytz.utc)
        if now_utc.date() != current_date:
            article_storage = deque(maxlen=MAX_ARTICLES)
            print(f"UTC Date changed from {current_date} to {now_utc.date()}: Resetting Article Storage")
            current_date = now_utc.date()
        
        time.sleep(60)  # Check every minute

# Global variable to store options data
gex_data = None
gex_data_lock = threading.Lock()

def fetch_spx_options_data(max_attempts=5, retry_delay=60):
    global gex_data

    # Function to get the previous market day
    def get_previous_market_day(date):
        while True:
            date -= timedelta(days=1)
            if date.weekday() < 5:  # Monday - Friday
                return date

    # Fetch options data for a given date
    def get_options_for_date(date):
        try:
            date_str = date.strftime("%Y-%m-%d")
            
            # Get SPX price
            request_params = StockBarsRequest(
                symbol_or_symbols="SPX",
                timeframe=TimeFrame.Day,
                start=date,
                end=date
            )
            bars = stock_client.get_stock_bars(request_params)
            
            if not bars or "SPX" not in bars:
                print(f"No price data found for SPX on {date_str}.")
                return None

            spx_price = bars["SPX"][0].close

            # Fetch options data
            options_request = OptionBarsRequest(
                symbol_or_symbols="SPX",
                timeframe=TimeFrame.Day,
                start=date,
                end=date
            )
            options_data = options_client.get_option_bars(options_request)

            calls = []
            puts = []

            for contract, data in options_data.items():
                if contract.endswith("C"):
                    calls.append({"strike": float(contract.split("SPX")[1][:-1]), "price": data[0].close})
                elif contract.endswith("P"):
                    puts.append({"strike": float(contract.split("SPX")[1][:-1]), "price": data[0].close})

            return {"spx_price": spx_price, "calls": calls, "puts": puts, "date": date_str}

        except Exception as e:
            print(f"Error fetching data for {date_str}: {e}")
            return None
            
    current_date = datetime.now()
    attempts = 0
    while attempts < max_attempts:
        options_data = get_options_for_date(current_date)
        if options_data:
            with gex_data_lock:
                gex_data = options_data
            return  # Exit if successful

        # If data is not available, move to the previous market day
        current_date = get_previous_market_day(current_date)
        attempts += 1

        print(f"Retrying with previous market day: {current_date.strftime('%Y-%m-%d')}, attempt {attempts}/{max_attempts}")
        time.sleep(retry_delay)  # Wait before retrying

    print(f"Failed to fetch options data after {max_attempts} attempts.")

def calculate_gamma_exposure(options_data):
    spx_price = options_data["spx_price"]
    calls = options_data["calls"]
    puts = options_data["puts"]

    min_strike = spx_price - 125
    max_strike = spx_price + 125

    filtered_calls = [call for call in calls if min_strike <= call["strike"] <= max_strike]
    filtered_puts = [put for put in puts if min_strike <= put["strike"] <= max_strike]

    gamma_exposure = []
    total_gex = 0

    for call, put in zip(filtered_calls, filtered_puts):
        strike = call["strike"]
        call_price = call["price"]
        put_price = put["price"]

        gamma = (1 / (strike * math.sqrt(2 * math.pi))) * np.exp(-0.5 * ((spx_price - strike) / strike)**2)
        gex = gamma * (call_price - put_price)
        gamma_exposure.append(gex)

        total_gex += gex

    return [call["strike"] for call in filtered_calls], gamma_exposure, total_gex

def get_gex_data():
    global gex_data

    with gex_data_lock:
        options_data = gex_data

    if options_data is None or not isinstance(options_data, dict):
        return None

    try:
        strikes, gamma_exposure, total_gex = calculate_gamma_exposure(options_data)
        strikes = [int(strike) for strike in strikes]
        gamma_exposure = [float(exposure) for exposure in gamma_exposure]

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        spx_price = options_data["spx_price"]
        date = options_data["date"]
        return {"strikes": strikes, "gamma_exposure": gamma_exposure, "spx_price": spx_price, "current_time": current_time, "total_gex": total_gex, "date": date}
    except Exception as e:
        print(f"Error calculating GEX data: {e}")
        return None

@app.route("/api/gex_data")
def api_gex_data():
    data = get_gex_data()
    if data is None:
        return jsonify({"error": "Failed to fetch GEX data"}), 500
    return jsonify(data)

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
        formatted_article["datetime"] = dt.timestamp()
        formatted_articles.append(formatted_article)

    sorted_articles = sorted(formatted_articles, key=lambda x: x["datetime"], reverse=True)

    for article in sorted_articles:
        del article["datetime"]

    return jsonify(sorted_articles)

def update_options_data():
    while True:
        fetch_spx_options_data()
        time_to_sleep = 60 
        print(f"Sleeping for {time_to_sleep}")
        with gex_data_lock:
            print(gex_data)
        time.sleep(time_to_sleep)  

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/GEX")
def gex_data():
    return render_template("GEX.html")

if __name__ == "__main__":
    threading.Thread(target=fetch_articles, daemon=True).start()
    threading.Thread(target=reset_storage, daemon=True).start()
    threading.Thread(target=update_options_data, daemon=True).start()
    app.run(host='0.0.0.0', port=8000, debug=True)
