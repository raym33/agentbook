"""
Skills Service for AgentBook.

Provides AI agents with real-world capabilities:
- Internet access (HTTP requests, web search)
- Code execution
- File operations
- And more from r_cli skills

This service wraps r_cli skills for use by autonomous agents.
"""

import json
import logging
import re
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class SkillResult:
    """Result from skill execution."""

    def __init__(self, success: bool, data: Any, error: Optional[str] = None):
        self.success = success
        self.data = data
        self.error = error

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
        }


class HTTPSkill:
    """HTTP client for agents to access the internet."""

    USER_AGENT = "AgentBook/1.0"
    TIMEOUT = 30
    MAX_RESPONSE_SIZE = 50000  # 50KB limit for agent context

    # Domains that agents are allowed to access
    ALLOWED_DOMAINS = [
        # Search and knowledge
        "wikipedia.org",
        "duckduckgo.com",
        "news.ycombinator.com",
        "reddit.com",
        # APIs
        "api.github.com",
        "api.openweathermap.org",
        "jsonplaceholder.typicode.com",
        # News
        "bbc.com",
        "reuters.com",
        # Tech
        "stackoverflow.com",
        "dev.to",
        "medium.com",
    ]

    # Blocked patterns (security)
    BLOCKED_PATTERNS = [
        r"localhost",
        r"127\.0\.0\.",
        r"192\.168\.",
        r"10\.\d+\.",
        r"172\.(1[6-9]|2[0-9]|3[01])\.",
        r"0\.0\.0\.0",
        r"::1",
    ]

    def is_url_allowed(self, url: str) -> tuple[bool, str]:
        """Check if URL is safe for agents to access."""
        from urllib.parse import urlparse

        try:
            parsed = urlparse(url)
            hostname = parsed.hostname or ""

            # Check blocked patterns (private IPs, localhost)
            for pattern in self.BLOCKED_PATTERNS:
                if re.search(pattern, hostname):
                    return False, f"Access to {hostname} is blocked (private network)"

            # For now, allow all public URLs
            # In production, you might want to restrict to ALLOWED_DOMAINS
            if parsed.scheme not in ("http", "https"):
                return False, "Only HTTP/HTTPS URLs are allowed"

            return True, ""

        except Exception as e:
            return False, f"Invalid URL: {e}"

    async def get(self, url: str, headers: Optional[dict] = None) -> SkillResult:
        """Make a GET request."""
        allowed, error = self.is_url_allowed(url)
        if not allowed:
            return SkillResult(False, None, error)

        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                req_headers = {"User-Agent": self.USER_AGENT}
                if headers:
                    req_headers.update(headers)

                response = await client.get(url, headers=req_headers, follow_redirects=True)

                # Get content
                content = response.text
                if len(content) > self.MAX_RESPONSE_SIZE:
                    content = content[: self.MAX_RESPONSE_SIZE] + "\n\n[Response truncated]"

                # Try to parse JSON
                try:
                    data = response.json()
                    return SkillResult(
                        True,
                        {
                            "status_code": response.status_code,
                            "content_type": "json",
                            "data": data,
                        },
                    )
                except json.JSONDecodeError:
                    return SkillResult(
                        True,
                        {
                            "status_code": response.status_code,
                            "content_type": "text",
                            "data": content,
                        },
                    )

        except httpx.TimeoutException:
            return SkillResult(False, None, f"Timeout connecting to {url}")
        except httpx.ConnectError as e:
            return SkillResult(False, None, f"Connection error: {e}")
        except Exception as e:
            return SkillResult(False, None, f"HTTP error: {e}")

    async def post(
        self, url: str, data: Optional[dict] = None, headers: Optional[dict] = None
    ) -> SkillResult:
        """Make a POST request."""
        allowed, error = self.is_url_allowed(url)
        if not allowed:
            return SkillResult(False, None, error)

        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                req_headers = {"User-Agent": self.USER_AGENT}
                if headers:
                    req_headers.update(headers)

                response = await client.post(
                    url, json=data, headers=req_headers, follow_redirects=True
                )

                content = response.text
                if len(content) > self.MAX_RESPONSE_SIZE:
                    content = content[: self.MAX_RESPONSE_SIZE]

                try:
                    return SkillResult(
                        True,
                        {
                            "status_code": response.status_code,
                            "data": response.json(),
                        },
                    )
                except json.JSONDecodeError:
                    return SkillResult(
                        True,
                        {
                            "status_code": response.status_code,
                            "data": content,
                        },
                    )

        except Exception as e:
            return SkillResult(False, None, f"HTTP error: {e}")


class WebSearchSkill:
    """Web search capability for agents."""

    async def search(self, query: str, max_results: int = 5) -> SkillResult:
        """Search the web using DuckDuckGo."""
        try:
            # Use DuckDuckGo HTML API (no API key needed)
            http = HTTPSkill()
            url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"

            result = await http.get(url)
            if not result.success:
                return result

            # Parse simple results from HTML (basic extraction)
            html = result.data.get("data", "")

            # Extract result snippets (simplified)
            results = []
            # This is a basic extraction - in production use proper HTML parser
            import re

            links = re.findall(r'class="result__a"[^>]*href="([^"]+)"[^>]*>([^<]+)', html)
            snippets = re.findall(r'class="result__snippet"[^>]*>([^<]+)', html)

            for i, (link, title) in enumerate(links[:max_results]):
                snippet = snippets[i] if i < len(snippets) else ""
                results.append(
                    {
                        "title": title.strip(),
                        "url": link,
                        "snippet": snippet.strip(),
                    }
                )

            return SkillResult(True, {"query": query, "results": results})

        except Exception as e:
            return SkillResult(False, None, f"Search error: {e}")


class WikipediaSkill:
    """Wikipedia access for agents to get factual information."""

    API_URL = "https://en.wikipedia.org/api/rest_v1"

    async def summary(self, topic: str) -> SkillResult:
        """Get Wikipedia summary for a topic."""
        try:
            http = HTTPSkill()
            # Clean topic for URL
            topic_url = topic.replace(" ", "_")
            url = f"{self.API_URL}/page/summary/{topic_url}"

            result = await http.get(url)
            if not result.success:
                return result

            data = result.data.get("data", {})
            if isinstance(data, dict):
                return SkillResult(
                    True,
                    {
                        "title": data.get("title", topic),
                        "extract": data.get("extract", "No information found"),
                        "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                    },
                )

            return SkillResult(False, None, "Could not parse Wikipedia response")

        except Exception as e:
            return SkillResult(False, None, f"Wikipedia error: {e}")


class NewsSkill:
    """News access for agents."""

    async def get_hacker_news_top(self, limit: int = 10) -> SkillResult:
        """Get top stories from Hacker News."""
        try:
            http = HTTPSkill()

            # Get top story IDs
            result = await http.get("https://hacker-news.firebaseio.com/v0/topstories.json")
            if not result.success:
                return result

            story_ids = result.data.get("data", [])[:limit]

            # Get story details
            stories = []
            for story_id in story_ids:
                story_result = await http.get(
                    f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
                )
                if story_result.success:
                    story = story_result.data.get("data", {})
                    stories.append(
                        {
                            "title": story.get("title", ""),
                            "url": story.get("url", ""),
                            "score": story.get("score", 0),
                            "by": story.get("by", ""),
                        }
                    )

            return SkillResult(True, {"stories": stories})

        except Exception as e:
            return SkillResult(False, None, f"News error: {e}")


class MarketDataSkill:
    """Real-time market data for crypto, stocks, and commodities."""

    async def get_crypto_prices(self, symbols: str = "bitcoin,ethereum,solana") -> SkillResult:
        """Get cryptocurrency prices from CoinGecko (free, no API key)."""
        try:
            http = HTTPSkill()
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbols}&vs_currencies=usd&include_24hr_change=true&include_market_cap=true"
            result = await http.get(url)
            if not result.success:
                return result

            data = result.data.get("data", {})
            prices = []
            for coin, info in data.items():
                prices.append({
                    "symbol": coin,
                    "price_usd": info.get("usd", 0),
                    "change_24h": info.get("usd_24h_change", 0),
                    "market_cap": info.get("usd_market_cap", 0),
                })
            return SkillResult(True, {"prices": prices, "timestamp": "now"})
        except Exception as e:
            return SkillResult(False, None, f"Crypto price error: {e}")

    async def get_crypto_detailed(self, coin_id: str = "bitcoin") -> SkillResult:
        """Get detailed crypto data including historical trends."""
        try:
            http = HTTPSkill()
            url = f"https://api.coingecko.com/api/v3/coins/{coin_id}?localization=false&tickers=false&community_data=false&developer_data=false"
            result = await http.get(url)
            if not result.success:
                return result

            data = result.data.get("data", {})
            market_data = data.get("market_data", {})
            return SkillResult(True, {
                "name": data.get("name", coin_id),
                "symbol": data.get("symbol", ""),
                "current_price": market_data.get("current_price", {}).get("usd", 0),
                "market_cap": market_data.get("market_cap", {}).get("usd", 0),
                "total_volume": market_data.get("total_volume", {}).get("usd", 0),
                "high_24h": market_data.get("high_24h", {}).get("usd", 0),
                "low_24h": market_data.get("low_24h", {}).get("usd", 0),
                "price_change_24h": market_data.get("price_change_percentage_24h", 0),
                "price_change_7d": market_data.get("price_change_percentage_7d", 0),
                "price_change_30d": market_data.get("price_change_percentage_30d", 0),
                "ath": market_data.get("ath", {}).get("usd", 0),
                "ath_change": market_data.get("ath_change_percentage", {}).get("usd", 0),
            })
        except Exception as e:
            return SkillResult(False, None, f"Crypto detail error: {e}")

    async def get_trending_crypto(self) -> SkillResult:
        """Get trending cryptocurrencies."""
        try:
            http = HTTPSkill()
            result = await http.get("https://api.coingecko.com/api/v3/search/trending")
            if not result.success:
                return result

            data = result.data.get("data", {})
            coins = data.get("coins", [])
            trending = []
            for item in coins[:10]:
                coin = item.get("item", {})
                trending.append({
                    "name": coin.get("name", ""),
                    "symbol": coin.get("symbol", ""),
                    "market_cap_rank": coin.get("market_cap_rank", 0),
                    "price_btc": coin.get("price_btc", 0),
                })
            return SkillResult(True, {"trending": trending})
        except Exception as e:
            return SkillResult(False, None, f"Trending error: {e}")

    async def get_fear_greed_index(self) -> SkillResult:
        """Get crypto Fear & Greed Index."""
        try:
            http = HTTPSkill()
            result = await http.get("https://api.alternative.me/fng/?limit=10")
            if not result.success:
                return result

            data = result.data.get("data", {}).get("data", [])
            if data:
                current = data[0]
                history = [{"value": int(d.get("value", 0)), "classification": d.get("value_classification", "")} for d in data[:7]]
                return SkillResult(True, {
                    "value": int(current.get("value", 0)),
                    "classification": current.get("value_classification", ""),
                    "history_7d": history,
                })
            return SkillResult(False, None, "No Fear & Greed data")
        except Exception as e:
            return SkillResult(False, None, f"Fear & Greed error: {e}")

    async def get_stock_quote(self, symbol: str = "AAPL") -> SkillResult:
        """Get stock quote from Yahoo Finance (via query API)."""
        try:
            http = HTTPSkill()
            # Using Yahoo Finance chart API (free, no key needed)
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
            result = await http.get(url)
            if not result.success:
                return result

            data = result.data.get("data", {})
            chart = data.get("chart", {}).get("result", [{}])[0]
            meta = chart.get("meta", {})
            indicators = chart.get("indicators", {}).get("quote", [{}])[0]

            closes = indicators.get("close", [])
            current_price = meta.get("regularMarketPrice", closes[-1] if closes else 0)
            prev_close = meta.get("previousClose", closes[-2] if len(closes) > 1 else current_price)
            change = ((current_price - prev_close) / prev_close * 100) if prev_close else 0

            return SkillResult(True, {
                "symbol": symbol.upper(),
                "price": round(current_price, 2),
                "previous_close": round(prev_close, 2),
                "change_percent": round(change, 2),
                "currency": meta.get("currency", "USD"),
                "exchange": meta.get("exchangeName", ""),
                "market_state": meta.get("marketState", ""),
            })
        except Exception as e:
            return SkillResult(False, None, f"Stock quote error: {e}")

    async def get_commodities(self) -> SkillResult:
        """Get gold, silver, and other commodity prices."""
        try:
            http = HTTPSkill()
            # Gold and Silver from metals API alternative
            commodities = {}

            # Get Gold (GC=F) and Silver (SI=F) from Yahoo
            for symbol, name in [("GC=F", "gold"), ("SI=F", "silver"), ("CL=F", "oil"), ("NG=F", "natural_gas")]:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
                result = await http.get(url)
                if result.success:
                    data = result.data.get("data", {})
                    chart = data.get("chart", {}).get("result", [{}])[0]
                    meta = chart.get("meta", {})
                    price = meta.get("regularMarketPrice", 0)
                    prev = meta.get("previousClose", price)
                    change = ((price - prev) / prev * 100) if prev else 0
                    commodities[name] = {
                        "price": round(price, 2),
                        "change_percent": round(change, 2),
                        "currency": "USD",
                    }

            return SkillResult(True, {"commodities": commodities})
        except Exception as e:
            return SkillResult(False, None, f"Commodities error: {e}")

    async def get_market_indices(self) -> SkillResult:
        """Get major market indices (S&P 500, NASDAQ, etc.)."""
        try:
            http = HTTPSkill()
            indices = {}

            for symbol, name in [("^GSPC", "sp500"), ("^IXIC", "nasdaq"), ("^DJI", "dow_jones"), ("^VIX", "vix")]:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
                result = await http.get(url)
                if result.success:
                    data = result.data.get("data", {})
                    chart = data.get("chart", {}).get("result", [{}])[0]
                    meta = chart.get("meta", {})
                    price = meta.get("regularMarketPrice", 0)
                    prev = meta.get("previousClose", price)
                    change = ((price - prev) / prev * 100) if prev else 0
                    indices[name] = {
                        "value": round(price, 2),
                        "change_percent": round(change, 2),
                    }

            return SkillResult(True, {"indices": indices})
        except Exception as e:
            return SkillResult(False, None, f"Indices error: {e}")

    async def get_forex(self, pairs: str = "EUR/USD,GBP/USD,USD/JPY") -> SkillResult:
        """Get forex exchange rates."""
        try:
            http = HTTPSkill()
            forex = {}

            pair_map = {
                "EUR/USD": "EURUSD=X",
                "GBP/USD": "GBPUSD=X",
                "USD/JPY": "JPY=X",
                "USD/CHF": "CHF=X",
                "AUD/USD": "AUDUSD=X",
            }

            for pair in pairs.split(","):
                pair = pair.strip()
                symbol = pair_map.get(pair, f"{pair.replace('/', '')}=X")
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
                result = await http.get(url)
                if result.success:
                    data = result.data.get("data", {})
                    chart = data.get("chart", {}).get("result", [{}])[0]
                    meta = chart.get("meta", {})
                    rate = meta.get("regularMarketPrice", 0)
                    prev = meta.get("previousClose", rate)
                    change = ((rate - prev) / prev * 100) if prev else 0
                    forex[pair] = {
                        "rate": round(rate, 4),
                        "change_percent": round(change, 2),
                    }

            return SkillResult(True, {"forex": forex})
        except Exception as e:
            return SkillResult(False, None, f"Forex error: {e}")


class CodeSkill:
    """Code-related capabilities for agents."""

    async def explain_code(self, code: str, language: str = "python") -> SkillResult:
        """Prepare context for code explanation (LLM will do the actual explanation)."""
        return SkillResult(
            True,
            {
                "code": code,
                "language": language,
                "task": "explain",
                "prompt": f"Explain this {language} code:\n```{language}\n{code}\n```",
            },
        )

    async def review_code(self, code: str, language: str = "python") -> SkillResult:
        """Prepare context for code review."""
        return SkillResult(
            True,
            {
                "code": code,
                "language": language,
                "task": "review",
                "prompt": f"Review this {language} code for bugs, improvements, and best practices:\n```{language}\n{code}\n```",
            },
        )


class SkillsService:
    """
    Main service that provides all skills to agents.

    Usage:
        skills = SkillsService()
        result = await skills.execute("http_get", url="https://example.com")
    """

    def __init__(self):
        self.http = HTTPSkill()
        self.search = WebSearchSkill()
        self.wikipedia = WikipediaSkill()
        self.news = NewsSkill()
        self.code = CodeSkill()
        self.market = MarketDataSkill()

        # Registry of available skills
        self.skills = {
            # HTTP
            "http_get": self.http.get,
            "http_post": self.http.post,
            # Search
            "web_search": self.search.search,
            # Knowledge
            "wikipedia": self.wikipedia.summary,
            # News
            "hacker_news": self.news.get_hacker_news_top,
            # Code
            "explain_code": self.code.explain_code,
            "review_code": self.code.review_code,
            # Market Data
            "crypto_prices": self.market.get_crypto_prices,
            "crypto_detailed": self.market.get_crypto_detailed,
            "crypto_trending": self.market.get_trending_crypto,
            "fear_greed": self.market.get_fear_greed_index,
            "stock_quote": self.market.get_stock_quote,
            "commodities": self.market.get_commodities,
            "market_indices": self.market.get_market_indices,
            "forex": self.market.get_forex,
        }

    def list_skills(self) -> list[dict]:
        """List all available skills with descriptions."""
        return [
            {
                "name": "http_get",
                "description": "Make HTTP GET request to fetch web content",
                "parameters": ["url", "headers (optional)"],
            },
            {
                "name": "http_post",
                "description": "Make HTTP POST request to send data",
                "parameters": ["url", "data", "headers (optional)"],
            },
            {
                "name": "web_search",
                "description": "Search the web using DuckDuckGo",
                "parameters": ["query", "max_results (optional, default 5)"],
            },
            {
                "name": "wikipedia",
                "description": "Get Wikipedia summary for a topic",
                "parameters": ["topic"],
            },
            {
                "name": "hacker_news",
                "description": "Get top stories from Hacker News",
                "parameters": ["limit (optional, default 10)"],
            },
            {
                "name": "explain_code",
                "description": "Get code explanation context",
                "parameters": ["code", "language (optional, default python)"],
            },
            {
                "name": "review_code",
                "description": "Get code review context",
                "parameters": ["code", "language (optional, default python)"],
            },
        ]

    async def execute(self, skill_name: str, **kwargs) -> SkillResult:
        """Execute a skill by name."""
        if skill_name not in self.skills:
            return SkillResult(False, None, f"Unknown skill: {skill_name}")

        try:
            handler = self.skills[skill_name]
            return await handler(**kwargs)
        except TypeError as e:
            return SkillResult(False, None, f"Invalid parameters for {skill_name}: {e}")
        except Exception as e:
            return SkillResult(False, None, f"Skill execution error: {e}")


# Global instance
skills_service = SkillsService()
