import os
from datetime import datetime, timedelta

import yfinance as yf
from dotenv import load_dotenv
from newsapi import NewsApiClient

load_dotenv()


def get_stock_data(ticker: str) -> dict:
    try:
        tk = yf.Ticker(ticker)
        info = tk.info

        # 近四季营收
        try:
            financials = tk.quarterly_financials
            if financials is not None and "Total Revenue" in financials.index:
                revenue_row = financials.loc["Total Revenue"]
                quarterly_revenue = [
                    {"date": str(col.date()), "revenue": val}
                    for col, val in revenue_row.items()
                ][:4]
            else:
                quarterly_revenue = None
        except Exception:
            quarterly_revenue = None

        return {
            "ticker": ticker,
            "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "pe_ratio": info.get("trailingPE"),
            "ev_ebitda": info.get("enterpriseToEbitda"),
            "quarterly_revenue": quarterly_revenue,
            "sector": info.get("sector"),
            "week_52_high": info.get("fiftyTwoWeekHigh"),
            "week_52_low": info.get("fiftyTwoWeekLow"),
            "market_cap": info.get("marketCap"),
        }
    except Exception as e:
        print(f"[get_stock_data] error for {ticker}: {e}")
        return {}


def get_news(ticker: str, days: int = 7) -> list[dict]:
    try:
        api_key = os.getenv("NEWS_API_KEY")
        if not api_key:
            raise ValueError("NEWS_API_KEY not set")

        client = NewsApiClient(api_key=api_key)
        from_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

        response = client.get_everything(
            q=ticker,
            from_param=from_date,
            language="en",
            sort_by="publishedAt",
            page_size=20,
        )

        articles = response.get("articles", [])
        return [
            {
                "title": a.get("title"),
                "description": a.get("description"),
                "url": a.get("url"),
                "publishedAt": a.get("publishedAt"),
            }
            for a in articles
        ]
    except Exception as e:
        print(f"[get_news] error for {ticker}: {e}")
        return []
