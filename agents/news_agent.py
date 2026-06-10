import feedparser
import urllib.parse

class NewsAgent:
    def get_news(self, ticker):
        query = urllib.parse.quote(f"{ticker} saham")
        url = f"https://news.google.com/rss/search?q={query}&hl=id&gl=ID&ceid=ID:id"
        feed = feedparser.parse(url)

        news = []
        for e in feed.entries[:3]:
            news.append(f"- {e.title}")

        return "\n".join(news) if news else "No recent news."
