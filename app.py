from flask import Flask, jsonify, render_template, request
import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from collections import deque
import re
import json
import base64
import math
import feedparser
import io
import base64
from datetime import datetime
import pytz
import time
import threading
import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry
from py_vollib.black_scholes.greeks.analytical import delta as bs_delta
from py_vollib.black_scholes.greeks.analytical import gamma as bs_gamma
from py_vollib.black_scholes.greeks.analytical import vega as bs_vega

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
    #"https://lorem-rss.herokuapp.com/feed",
]

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

def get_live_price(t):
    try:
        d = datetime.now().strftime("%Y-%m-%d")
        # Hash the base URL
        base = base64.b64decode("aHR0cHM6Ly9hcGkuMGR0ZXNweC5jb20=").decode()
        u = f"{base}/aggregateData?series={t}&date={d}&interval=5"
        
        # Hash the headers
        h = {
            base64.b64decode("YWNjZXB0").decode(): "*/*",
            base64.b64decode("YWNjZXB0LWxhbmd1YWdl").decode(): "en-US,en;q=0.9", 
            base64.b64decode("Y2FjaGUtY29udHJvbA==").decode(): "no-cache",
            base64.b64decode("cHJhZ21h").decode(): "no-cache",
            base64.b64decode("cHJpb3JpdHk=").decode(): "u=1, i",
            base64.b64decode("c2VjLWNoLXVh").decode(): "\"Not(A:Brand\";v=\"99\", \"Google Chrome\";v=\"133\", \"Chromium\";v=\"133\"",
            base64.b64decode("c2VjLWNoLXVhLW1vYmlsZQ==").decode(): "?0",
            base64.b64decode("c2VjLWNoLXVhLXBsYXRmb3Jt").decode(): "\"Windows\"",
            base64.b64decode("c2VjLWZldGNoLWRlc3Q=").decode(): "empty",
            base64.b64decode("c2VjLWZldGNoLW1vZGU=").decode(): "cors",
            base64.b64decode("c2VjLWZldGNoLXNpdGU=").decode(): "same-site",
            base64.b64decode("UmVmZXJlcg==").decode(): base64.b64decode("aHR0cHM6Ly8wZHRlc3B4LmNvbS8=").decode(),
            base64.b64decode("UmVmZXJlci1Qb2xpY3k=").decode(): "strict-origin-when-cross-origin"
        }
        
        r = requests.get(u, headers=h, timeout=5)
        d = r.json()
        if d and isinstance(d, list):
            l = d[-1]
            if t.lower() in l:
                return l[t.lower()]
    except Exception:
        return None

def extract_expiry_from_contract(contract_symbol):
    """
    Extracts the expiration date from an option contract symbol.
    Handles both 6-digit (YYMMDD) and 8-digit (YYYYMMDD) date formats.
    """
    pattern = r'[A-Z]+W?(?P<date>\d{6}|\d{8})[CP]\d+'
    match = re.search(pattern, contract_symbol)
    if match:
        date_str = match.group("date")
        try:
            if len(date_str) == 6:
                # Parse as YYMMDD
                expiry_date = datetime.strptime(date_str, "%y%m%d").date()
            else:
                # Parse as YYYYMMDD
                expiry_date = datetime.strptime(date_str, "%Y%m%d").date()
            return expiry_date
        except ValueError:
            return None
    return None

# -------------------------------
# Fetch all options experations and add extract expiry
# -------------------------------
def fetch_all_options(ticker):
    """
    Fetches option chains for all available expirations for the given ticker.
    Returns two DataFrames: one for calls and one for puts, with an added column 'extracted_expiry'.
    """
    print(f"Fetching available expirations for {ticker}")  # Add print statement
    stock = yf.Ticker(ticker)
    all_calls = []
    all_puts = []
    
    if stock.options:
        # Get current market date
        current_market_date = datetime.now().date()
        
        for exp in stock.options:
            try:
                chain = stock.option_chain(exp)
                calls = chain.calls
                puts = chain.puts
                
                # Only process options that haven't expired
                exp_date = datetime.strptime(exp, '%Y-%m-%d').date()
                if exp_date >= current_market_date:
                    if not calls.empty:
                        calls = calls.copy()
                        calls['extracted_expiry'] = calls['contractSymbol'].apply(extract_expiry_from_contract)
                        all_calls.append(calls)
                    if not puts.empty:
                        puts = puts.copy()
                        puts['extracted_expiry'] = puts['contractSymbol'].apply(extract_expiry_from_contract)
                        all_puts.append(puts)
            except Exception as e:
                print(f"Error fetching chain for expiry {exp}: {e}")
                continue
    else:
        try:
            # Get next valid expiration
            next_exp = stock.options[0] if stock.options else None
            if next_exp:
                chain = stock.option_chain(next_exp)
                calls = chain.calls
                puts = chain.puts
                if not calls.empty:
                    calls = calls.copy()
                    calls['extracted_expiry'] = calls['contractSymbol'].apply(extract_expiry_from_contract)
                    all_calls.append(calls)
                if not puts.empty:
                    puts = puts.copy()
                    puts['extracted_expiry'] = puts['contractSymbol'].apply(extract_expiry_from_contract)
                    all_puts.append(puts)
        except Exception as e:
            print(f"Error fetching fallback options data: {e}")
    
    if all_calls:
        combined_calls = pd.concat(all_calls, ignore_index=True)
    else:
        combined_calls = pd.DataFrame()
    if all_puts:
        combined_puts = pd.concat(all_puts, ignore_index=True)
    else:
        combined_puts = pd.DataFrame()
    
    return combined_calls, combined_puts

# Charts and price fetching
def get_current_price(ticker):
    """Get current price with fallback logic"""
    print(f"Fetching current price for {ticker}")
    formatted_ticker = ticker.replace('%5E', '^')
    
    # Try EzApi first for SPX
    if formatted_ticker in ['^SPX'] or ticker in ['%5ESPX', 'SPX']:
        try:
            live_price = get_live_price('spx')
            if live_price is not None:
                return round(float(live_price), 2)
        except Exception as e:
            print(f"EzApi failed for SPX: {str(e)}")
    
    try:
        stock = yf.Ticker(ticker)
        price = stock.info.get("regularMarketPrice")
        if price is None:
            price = stock.fast_info.get("lastPrice")
        if price is not None:
            return round(float(price), 2)
    except Exception as e:
        print(f"Yahoo Finance error: {str(e)}")
    
    return None

def add_current_price_line(fig, current_price):
    """
    Adds a vertical dashed white line at the current price to a Plotly figure.
    """
    fig.add_vline(
        x=current_price,
        line_dash="dash",
        line_color="white",
        opacity=0.7,
        annotation_text=f"{current_price}",
        annotation_position="top",
    )
    return fig

def create_oi_volume_charts(calls, puts, strike_range = 50): #Added default strike range
    # Get underlying price
    S = get_current_price("SPX") #Hardcoded SPX
    if S is None:
        print("Could not fetch underlying price.")
        return None # Return None if price couldn't be fetched

    # Calculate strike range around current price
    min_strike = S - strike_range
    max_strike = S + strike_range
    
    # Filter data based on strike range
    calls = calls[(calls['strike'] >= min_strike) & (calls['strike'] <= max_strike)]
    puts = puts[(puts['strike'] >= min_strike) & (puts['strike'] <= max_strike)]
    
    calls_df = calls[['strike', 'openInterest', 'volume']].copy()
    calls_df['OptionType'] = 'Call'
    
    puts_df = puts[['strike', 'openInterest', 'volume']].copy()
    puts_df['OptionType'] = 'Put'
    
    combined = pd.concat([calls_df, puts_df], ignore_index=True)
    combined.sort_values(by='strike', inplace=True)
    
    # Calculate Net Open Interest and Net Volume using filtered data
    net_oi = calls.groupby('strike')['openInterest'].sum() - puts.groupby('strike')['openInterest'].sum()
    net_volume = calls.groupby('strike')['volume'].sum() - puts.groupby('strike')['volume'].sum()
    
    # Add padding for x-axis range
    padding = strike_range * 0.1
    
    call_color = '#00FF00' #st.session_state.call_color   #Hardcoded colors
    put_color = '#FF0000'   #st.session_state.put_color

    fig_oi = px.bar(
        combined,
        x='strike',
        y='openInterest',
        color='OptionType',
        title='Open Interest by Strike',
        barmode='group',
        color_discrete_map={'Call': call_color, 'Put': put_color}
    )
    
    # Add Net OI trace as bar
    fig_oi.add_trace(go.Bar(
        x=net_oi.index, 
        y=net_oi.values, 
        name='Net OI', 
        marker=dict(color=[call_color if val >= 0 else put_color for val in net_oi.values])
    ))
    
    # Update OI chart layout with text size settings
    fig_oi.update_layout(
        title=dict(
            text='Open Interest by Strike',
            x=0,
            xanchor='left',
            font=dict(size=16 + 8) #st.session_state.chart_text_size + 8
        ),
        xaxis_title=dict(
            text='Strike Price',
            font=dict(size=16) #st.session_state.chart_text_size
        ),
        yaxis_title=dict(
            text='Open Interest',
            font=dict(size=16) #st.session_state.chart_text_size
        ),
        legend=dict(
            font=dict(size=16) #st.session_state.chart_text_size
        ),
        hovermode='x unified',
        xaxis=dict(
            range=[min_strike - padding, max_strike + padding],
            tickmode='linear',
            dtick=math.ceil(strike_range / 10), #st.session_state.strike_range / 10
            tickfont=dict(size=16) #st.session_state.chart_text_size
        ),
        yaxis=dict(
            tickfont=dict(size=16) #st.session_state.chart_text_size
        )
    )
    
    fig_volume = px.bar(
        combined,
        x='strike',
        y='volume',
        color='OptionType',
        title='Volume by Strike',
        barmode='group',
        color_discrete_map={'Call': call_color, 'Put': put_color}
    )
    
    # Add Net Volume trace as bar
    fig_volume.add_trace(go.Bar(
        x=net_volume.index, 
        y=net_volume.values, 
        name='Net Volume', 
        marker=dict(color=[call_color if val >= 0 else put_color for val in net_volume.values])
    ))
    
    # Update Volume chart layout with text size settings
    fig_volume.update_layout(
        title=dict(
            text='Volume by Strike',
            x=0,
            xanchor='left',
            font=dict(size=16 + 8) #st.session_state.chart_text_size + 8
        ),
        xaxis_title=dict(
            text='Strike Price',
            font=dict(size=16) #st.session_state.chart_text_size
        ),
        yaxis_title=dict(
            text='Volume',
            font=dict(size=16) #st.session_state.chart_text_size
        ),
        legend=dict(
            font=dict(size=16) #st.session_state.chart_text_size
        ),
        hovermode='x unified',
        xaxis=dict(
            range=[min_strike - padding, max_strike + padding],
            tickmode='linear',
            dtick=math.ceil(strike_range / 10), #st.session_state.strike_range / 10
            tickfont=dict(size=16) #st.session_state.chart_text_size
        ),
        yaxis=dict(
            tickfont=dict(size=16) #st.session_state.chart_text_size
        )
    )
    
    fig_oi.update_xaxes(rangeslider=dict(visible=True))
    fig_volume.update_xaxes(rangeslider=dict(visible=True))
    
    # Add current price line
    S = round(S, 2)
    fig_oi = add_current_price_line(fig_oi, S)
    fig_volume = add_current_price_line(fig_volume, S)
    
    return fig_oi, fig_volume




# Serve the frontend
@app.route("/")
def index():
    return render_template("index.html")

# Serve the GEX data page
@app.route("/GEX")
def get_gex_data():
    """
    Fetches options data for SPX, calculates GEX, and returns a Plotly chart as HTML.
    """
    try:
        # Fetch all options data for SPX
        calls, puts = fetch_all_options("SPX")

        # Check if DataFrames are empty
        if calls.empty or puts.empty:
            return "Error: Could not retrieve options data for SPX."

        # Create the Open Interest and Volume charts
        fig_oi, fig_volume = create_oi_volume_charts(calls, puts)

        if fig_oi is None or fig_volume is None:
            return "Error: Could not generate GEX chart."

        # Convert the Plotly chart to HTML
        gex_html = fig_oi.to_html(full_html=False, include_plotlyjs='cdn')
        volume_html = fig_volume.to_html(full_html=False, include_plotlyjs='cdn')

        # Return the HTML to be embedded in the template
        return render_template("GEX.html", gex_plot=gex_html, volume_plot = volume_html)

    except Exception as e:
        print(f"Error generating GEX data: {e}")
        return f"Error: {str(e)}"

if __name__ == "__main__":
    # Start background threads
    threading.Thread(target=fetch_articles, daemon=True).start()
    threading.Thread(target=reset_storage, daemon=True).start()
    app.run(host='0.0.0.0', port=8000, debug=True)

