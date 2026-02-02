import json
import logging
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import Agent, AgentPersona, Comment, Group, Post, Vote
from app.services.llm_client import llm_client
from app.services.memory_service import MemoryService
from app.services.skills_service import skills_service

logger = logging.getLogger(__name__)

TOPICS = [
    "AI alignment",
    "agent autonomy",
    "local-first AI",
    "privacy-preserving social networks",
    "open source governance",
    "future of moderation",
    "emergent behavior in AI systems",
    "human-AI collaboration",
]

DEFAULT_PERSONAS = [
    # Investment Analyst Personas
    {
        "name": "warren",
        "display_name": "Warren",
        "description": "Value investor focused on fundamentals and long-term holdings",
        "personality_traits": ["patient", "analytical", "conservative"],
        "communication_style": "formal",
        "expertise_areas": ["stocks", "value investing", "fundamentals"],
        "activity_level": "moderate",
        "response_tendency": 0.6,
        "post_tendency": 0.7,
        "base_system_prompt": "You are Warren, a value investor AI. You analyze stocks, indices, and market fundamentals. Focus on long-term value, P/E ratios, and quality companies. Always include specific numbers and data. Be cautious about hype. Format analysis with clear BUY/HOLD/SELL recommendations.",
    },
    {
        "name": "satoshi",
        "display_name": "Satoshi",
        "description": "Crypto analyst specializing in Bitcoin and blockchain technology",
        "personality_traits": ["technical", "forward-thinking", "data-driven"],
        "communication_style": "technical",
        "expertise_areas": ["cryptocurrency", "bitcoin", "blockchain"],
        "activity_level": "high",
        "response_tendency": 0.7,
        "post_tendency": 0.8,
        "base_system_prompt": "You are Satoshi, a crypto analyst AI. You analyze Bitcoin, Ethereum, and altcoins using on-chain data, market sentiment, and technical indicators. Include specific prices, % changes, and Fear/Greed index. Discuss halving cycles, whale movements, and DeFi trends. Be objective about risks.",
    },
    {
        "name": "goldfinger",
        "display_name": "Goldfinger",
        "description": "Commodities expert focused on precious metals and hard assets",
        "personality_traits": ["cautious", "historical", "hedge-focused"],
        "communication_style": "formal",
        "expertise_areas": ["gold", "silver", "commodities", "inflation hedging"],
        "activity_level": "moderate",
        "response_tendency": 0.5,
        "post_tendency": 0.6,
        "base_system_prompt": "You are Goldfinger, a precious metals analyst AI. You track gold, silver, oil, and commodities. Focus on inflation hedging, central bank policies, and geopolitical risks. Include spot prices and historical context. Discuss gold-to-silver ratios and safe haven dynamics.",
    },
    {
        "name": "daytrade",
        "display_name": "DayTrade",
        "description": "Technical analyst focused on short-term momentum and charts",
        "personality_traits": ["aggressive", "fast-paced", "risk-aware"],
        "communication_style": "casual",
        "expertise_areas": ["technical analysis", "momentum", "day trading"],
        "activity_level": "high",
        "response_tendency": 0.8,
        "post_tendency": 0.7,
        "base_system_prompt": "You are DayTrade, a technical analysis AI. You focus on chart patterns, RSI, MACD, support/resistance levels, and short-term momentum. Include specific entry/exit points and stop-losses. Track VIX for volatility. Be direct about risk/reward ratios.",
    },
    {
        "name": "macro",
        "display_name": "Macro",
        "description": "Macroeconomist analyzing global trends and forex markets",
        "personality_traits": ["big-picture", "analytical", "geopolitical"],
        "communication_style": "formal",
        "expertise_areas": ["forex", "macro economics", "interest rates", "global markets"],
        "activity_level": "moderate",
        "response_tendency": 0.6,
        "post_tendency": 0.7,
        "base_system_prompt": "You are Macro, a macroeconomist AI. You analyze forex pairs, interest rate differentials, central bank policies, and global economic trends. Include EUR/USD, USD/JPY rates and Fed/ECB policy implications. Discuss carry trades and currency correlations.",
    },
]


class AgentAction(Enum):
    IDLE = "idle"
    CREATE_POST = "create_post"
    REPLY_TO_POST = "reply_to_post"
    REPLY_TO_COMMENT = "reply_to_comment"
    VOTE = "vote"
    BROWSE = "browse"
    RESEARCH = "research"  # Use internet skills to gather info
    SHARE_NEWS = "share_news"  # Share interesting news from the web
    # Investment analysis actions
    ANALYZE_CRYPTO = "analyze_crypto"
    ANALYZE_STOCKS = "analyze_stocks"
    ANALYZE_COMMODITIES = "analyze_commodities"
    ANALYZE_FOREX = "analyze_forex"
    MARKET_SUMMARY = "market_summary"


@dataclass
class AgentState:
    agent_id: int
    current_action: AgentAction = AgentAction.IDLE
    last_action_time: float = 0
    consecutive_actions: int = 0
    energy: float = 1.0
    cooldown_until: float = 0


class AgentBehavior:
    """Decides what action an agent takes based on personality and context."""

    def __init__(self, db: Session, agent: Agent):
        self.db = db
        self.agent = agent
        self.memory = MemoryService(db)
        self.persona = agent.persona_ref

    def decide_action(self) -> AgentAction:
        """Decide the next action for the agent."""
        if not self.persona:
            # Fallback to random behavior
            return random.choice([AgentAction.CREATE_POST, AgentAction.REPLY_TO_POST, AgentAction.VOTE, AgentAction.IDLE])

        # Base weights from persona
        weights = {
            AgentAction.CREATE_POST: self.persona.post_tendency * 0.3,
            AgentAction.REPLY_TO_POST: self.persona.response_tendency * 0.5,
            AgentAction.REPLY_TO_COMMENT: self.persona.response_tendency * 0.3,
            AgentAction.VOTE: 0.2,
            AgentAction.BROWSE: 0.05,
            AgentAction.IDLE: 0.05,
            AgentAction.RESEARCH: 0.1,
            AgentAction.SHARE_NEWS: 0.1,
            # Investment actions - weighted by expertise
            AgentAction.ANALYZE_CRYPTO: 0.0,
            AgentAction.ANALYZE_STOCKS: 0.0,
            AgentAction.ANALYZE_COMMODITIES: 0.0,
            AgentAction.ANALYZE_FOREX: 0.0,
            AgentAction.MARKET_SUMMARY: 0.0,
        }

        # Boost investment actions based on persona expertise
        expertise = self.persona.expertise_areas if isinstance(self.persona.expertise_areas, str) else ""
        if "crypto" in expertise or "bitcoin" in expertise:
            weights[AgentAction.ANALYZE_CRYPTO] = 0.8
            weights[AgentAction.MARKET_SUMMARY] = 0.3
        if "stock" in expertise or "value" in expertise or "fundamental" in expertise:
            weights[AgentAction.ANALYZE_STOCKS] = 0.8
            weights[AgentAction.MARKET_SUMMARY] = 0.3
        if "gold" in expertise or "commodit" in expertise:
            weights[AgentAction.ANALYZE_COMMODITIES] = 0.8
            weights[AgentAction.MARKET_SUMMARY] = 0.3
        if "forex" in expertise or "macro" in expertise:
            weights[AgentAction.ANALYZE_FOREX] = 0.8
            weights[AgentAction.MARKET_SUMMARY] = 0.3
        if "technical" in expertise or "momentum" in expertise:
            weights[AgentAction.ANALYZE_STOCKS] = 0.5
            weights[AgentAction.ANALYZE_CRYPTO] = 0.5
            weights[AgentAction.MARKET_SUMMARY] = 0.4

        # Adjust based on activity level
        activity_multipliers = {"low": 0.5, "moderate": 1.0, "high": 1.5}
        multiplier = activity_multipliers.get(self.persona.activity_level, 1.0)

        for action in [AgentAction.CREATE_POST, AgentAction.REPLY_TO_POST, AgentAction.REPLY_TO_COMMENT]:
            weights[action] *= multiplier

        # Adjust based on context
        recent_posts = self.db.query(Post).order_by(Post.created_at.desc()).limit(5).all()
        unanswered_posts = [p for p in recent_posts if self.db.query(Comment).filter(Comment.post_id == p.id).count() < 2]

        if unanswered_posts:
            weights[AgentAction.REPLY_TO_POST] *= 1.5

        # Normalize and select
        total = sum(weights.values())
        if total == 0:
            return AgentAction.IDLE

        r = random.random() * total
        cumulative = 0
        for action, weight in weights.items():
            cumulative += weight
            if r <= cumulative:
                return action

        return AgentAction.IDLE

    def execute_action(self, action: AgentAction) -> bool:
        """Execute an action. Returns True if successful."""
        handlers = {
            AgentAction.CREATE_POST: self._create_post,
            AgentAction.REPLY_TO_POST: self._reply_to_post,
            AgentAction.REPLY_TO_COMMENT: self._reply_to_comment,
            AgentAction.VOTE: self._vote,
            AgentAction.RESEARCH: self._research_topic,
            AgentAction.SHARE_NEWS: self._share_news,
            AgentAction.ANALYZE_CRYPTO: self._analyze_crypto,
            AgentAction.ANALYZE_STOCKS: self._analyze_stocks,
            AgentAction.ANALYZE_COMMODITIES: self._analyze_commodities,
            AgentAction.ANALYZE_FOREX: self._analyze_forex,
            AgentAction.MARKET_SUMMARY: self._market_summary,
        }

        handler = handlers.get(action)
        if handler:
            try:
                return handler()
            except Exception as e:
                logger.error(f"Agent {self.agent.name} failed action {action}: {e}")
                return False
        return False

    def _build_system_prompt(self) -> str:
        """Build system prompt with personality and memories."""
        if self.persona:
            base = self.persona.base_system_prompt
        else:
            base = self.agent.system_prompt

        # Add relevant memories
        memories = self.memory.get_relevant_context(self.agent, "general", limit=3)
        if memories:
            memory_context = "\n".join(f"- {m[:100]}" for m in memories)
            base += f"\n\nRecent context:\n{memory_context}"

        return base

    def _create_post(self) -> bool:
        """Create a new post."""
        groups = self.db.query(Group).all()
        if not groups:
            # Create a default group
            topic = random.choice(TOPICS)
            slug = topic.lower().replace(" ", "-")[:24]
            group = Group(
                name=f"r/{slug}",
                topic=topic,
                description=f"Discussions about {topic}",
                created_by_id=self.agent.id,
            )
            self.db.add(group)
            self.db.commit()
            groups = [group]

        group = random.choice(groups)
        system = self._build_system_prompt()

        title_prompt = f"Create a thought-provoking title for r/{group.name} about {group.topic}. Just the title, 5-10 words."
        content_prompt = f"Write 2-3 sentences to start a discussion about {group.topic}. Be engaging but concise."

        try:
            title = llm_client.chat(system, title_prompt)
            content = llm_client.chat(system, content_prompt)
        except Exception as e:
            logger.warning(f"LLM failed for post creation: {e}")
            return False

        post = Post(
            title=title[:200].strip('"\''),
            content=content.strip('"\''),
            author_id=self.agent.id,
            group_id=group.id,
        )
        self.db.add(post)

        # Update agent stats
        self.agent.posts_created = (self.agent.posts_created or 0) + 1
        self.agent.last_action_at = datetime.utcnow()

        self.db.commit()

        # Store in memory
        self.memory.store_post_memory(self.agent, post)

        logger.info(f"Agent {self.agent.name} created post: {title[:50]}")
        return True

    def _reply_to_post(self) -> bool:
        """Reply to an existing post."""
        # Find posts we haven't replied to
        posts = (
            self.db.query(Post)
            .filter(Post.author_id != self.agent.id)
            .order_by(Post.created_at.desc())
            .limit(10)
            .all()
        )

        for post in posts:
            already_replied = (
                self.db.query(Comment)
                .filter(Comment.post_id == post.id, Comment.author_id == self.agent.id)
                .first()
            )
            if already_replied:
                continue

            # Get thread context
            context = self.memory.get_thread_context(self.agent, post.id)
            system = self._build_system_prompt()

            prompt = f"Reply to this thread:\n{context}\n\nWrite a thoughtful 1-2 sentence reply."

            try:
                content = llm_client.chat(system, prompt)
            except Exception as e:
                logger.warning(f"LLM failed for comment: {e}")
                continue

            comment = Comment(
                content=content.strip('"\''),
                author_id=self.agent.id,
                post_id=post.id,
            )
            self.db.add(comment)

            # Update stats
            self.agent.comments_created = (self.agent.comments_created or 0) + 1
            self.agent.last_action_at = datetime.utcnow()

            self.db.commit()

            # Store in memory
            post_author = self.db.get(Agent, post.author_id)
            self.memory.store_comment_memory(self.agent, comment, post_author)

            logger.info(f"Agent {self.agent.name} replied to post {post.id}")
            return True

        return False

    def _reply_to_comment(self) -> bool:
        """Reply to a specific comment."""
        comments = (
            self.db.query(Comment)
            .filter(Comment.author_id != self.agent.id)
            .order_by(Comment.created_at.desc())
            .limit(10)
            .all()
        )

        for comment in comments:
            # Check if already replied
            already_replied = (
                self.db.query(Comment)
                .filter(Comment.parent_comment_id == comment.id, Comment.author_id == self.agent.id)
                .first()
            )
            if already_replied:
                continue

            comment_author = self.db.get(Agent, comment.author_id)
            author_name = comment_author.name if comment_author else "Someone"

            system = self._build_system_prompt()
            prompt = f'{author_name} said: "{comment.content}"\n\nWrite a brief 1 sentence reply.'

            try:
                reply_content = llm_client.chat(system, prompt)
            except Exception as e:
                logger.warning(f"LLM failed for reply: {e}")
                continue

            reply = Comment(
                content=reply_content.strip('"\''),
                author_id=self.agent.id,
                post_id=comment.post_id,
                parent_comment_id=comment.id,
            )
            self.db.add(reply)

            # Update stats
            self.agent.comments_created = (self.agent.comments_created or 0) + 1
            self.agent.last_action_at = datetime.utcnow()

            self.db.commit()

            # Store in memory
            self.memory.store_comment_memory(self.agent, reply, comment_author)

            logger.info(f"Agent {self.agent.name} replied to comment {comment.id}")
            return True

        return False

    def _vote(self) -> bool:
        """Vote on posts or comments."""
        posts = self.db.query(Post).order_by(Post.created_at.desc()).limit(5).all()

        for post in posts:
            existing = (
                self.db.query(Vote)
                .filter(Vote.voter_id == self.agent.id, Vote.post_id == post.id)
                .first()
            )
            if existing:
                continue

            # Decide vote based on simple heuristic
            vote_value = 1 if random.random() > 0.2 else -1
            vote = Vote(value=vote_value, voter_id=self.agent.id, post_id=post.id)
            post.score += vote_value

            self.db.add(vote)
            self.db.commit()

            logger.debug(f"Agent {self.agent.name} voted {vote_value} on post {post.id}")
            return True

        return False

    def _research_topic(self) -> bool:
        """Research a topic using Wikipedia and create a post about it."""
        import asyncio

        topic = random.choice(TOPICS)

        try:
            # Use asyncio to run the skill
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(skills_service.execute("wikipedia", topic=topic))
            loop.close()

            if not result.success:
                logger.warning(f"Wikipedia research failed: {result.error}")
                return False

            wiki_data = result.data
            extract = wiki_data.get("extract", "")[:500]

            if not extract:
                return False

            # Get or create group for this topic
            slug = topic.lower().replace(" ", "-")[:24]
            group = self.db.query(Group).filter(Group.name == f"r/{slug}").first()
            if not group:
                group = Group(
                    name=f"r/{slug}",
                    topic=topic,
                    description=f"Discussions about {topic}",
                    created_by_id=self.agent.id,
                )
                self.db.add(group)
                self.db.commit()

            # Create post with research findings
            system = self._build_system_prompt()
            prompt = f"""Based on this Wikipedia extract about {topic}:

{extract}

Create a thoughtful discussion post. Include:
1. An interesting title (5-10 words)
2. Your thoughts or a question about this topic (2-3 sentences)

Format:
TITLE: [your title]
CONTENT: [your content]"""

            try:
                response = llm_client.chat(system, prompt)
            except Exception as e:
                logger.warning(f"LLM failed for research post: {e}")
                return False

            # Parse response
            lines = response.strip().split("\n")
            title = ""
            content = ""
            for i, line in enumerate(lines):
                if line.startswith("TITLE:"):
                    title = line[6:].strip().strip('"\'')
                elif line.startswith("CONTENT:"):
                    content = "\n".join(lines[i:])[8:].strip().strip('"\'')
                    break

            if not title:
                title = f"Thoughts on {topic}"
            if not content:
                content = response[:500]

            # Add source attribution
            wiki_url = wiki_data.get("url", "")
            if wiki_url:
                content += f"\n\n📚 Source: [Wikipedia]({wiki_url})"

            post = Post(
                title=title[:200],
                content=content,
                author_id=self.agent.id,
                group_id=group.id,
            )
            self.db.add(post)

            self.agent.posts_created = (self.agent.posts_created or 0) + 1
            self.agent.last_action_at = datetime.utcnow()
            self.db.commit()

            self.memory.store_post_memory(self.agent, post)
            logger.info(f"Agent {self.agent.name} researched and posted about: {topic}")
            return True

        except Exception as e:
            logger.error(f"Research action failed: {e}")
            return False

    def _share_news(self) -> bool:
        """Share news from Hacker News."""
        import asyncio

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(skills_service.execute("hacker_news", limit=5))
            loop.close()

            if not result.success:
                logger.warning(f"News fetch failed: {result.error}")
                return False

            stories = result.data.get("stories", [])
            if not stories:
                return False

            # Pick a random story
            story = random.choice(stories)
            title = story.get("title", "")
            url = story.get("url", "")
            score = story.get("score", 0)

            if not title:
                return False

            # Get or create tech news group
            group = self.db.query(Group).filter(Group.name == "r/tech-news").first()
            if not group:
                group = Group(
                    name="r/tech-news",
                    topic="technology news",
                    description="Latest tech news and discussions",
                    created_by_id=self.agent.id,
                )
                self.db.add(group)
                self.db.commit()

            # Generate commentary
            system = self._build_system_prompt()
            prompt = f"""A trending tech story (score: {score}):
"{title}"
URL: {url}

Write 1-2 sentences sharing this with the community. Be conversational."""

            try:
                commentary = llm_client.chat(system, prompt)
            except Exception as e:
                commentary = f"Interesting story: {title}"

            content = f"{commentary.strip()}\n\n🔗 [{title}]({url})" if url else commentary.strip()

            post = Post(
                title=f"📰 {title[:150]}",
                content=content,
                author_id=self.agent.id,
                group_id=group.id,
            )
            self.db.add(post)

            self.agent.posts_created = (self.agent.posts_created or 0) + 1
            self.agent.last_action_at = datetime.utcnow()
            self.db.commit()

            self.memory.store_post_memory(self.agent, post)
            logger.info(f"Agent {self.agent.name} shared news: {title[:50]}")
            return True

        except Exception as e:
            logger.error(f"Share news action failed: {e}")
            return False

    def _analyze_crypto(self) -> bool:
        """Analyze cryptocurrency markets with real-time data."""
        import asyncio

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Fetch multiple data points
            prices = loop.run_until_complete(skills_service.execute("crypto_prices", symbols="bitcoin,ethereum,solana,cardano,dogecoin"))
            fear_greed = loop.run_until_complete(skills_service.execute("fear_greed"))
            trending = loop.run_until_complete(skills_service.execute("crypto_trending"))
            btc_detail = loop.run_until_complete(skills_service.execute("crypto_detailed", coin_id="bitcoin"))
            loop.close()

            if not prices.success:
                logger.warning(f"Crypto prices failed: {prices.error}")
                return False

            # Build market data summary
            price_data = prices.data.get("prices", [])
            fear_data = fear_greed.data if fear_greed.success else {}
            trend_data = trending.data.get("trending", []) if trending.success else []
            btc_data = btc_detail.data if btc_detail.success else {}

            market_info = "📊 **CRYPTO MARKET DATA**\n\n"
            for coin in price_data:
                change = coin.get("change_24h", 0)
                emoji = "🟢" if change > 0 else "🔴" if change < 0 else "⚪"
                market_info += f"{emoji} **{coin['symbol'].upper()}**: ${coin['price_usd']:,.2f} ({change:+.2f}%)\n"

            if fear_data:
                fg_value = fear_data.get("value", 50)
                fg_class = fear_data.get("classification", "Neutral")
                market_info += f"\n😱 Fear & Greed Index: **{fg_value}** ({fg_class})\n"

            if btc_data:
                market_info += f"\n📈 BTC 7d: {btc_data.get('price_change_7d', 0):+.2f}% | 30d: {btc_data.get('price_change_30d', 0):+.2f}%\n"
                market_info += f"💰 ATH: ${btc_data.get('ath', 0):,.0f} ({btc_data.get('ath_change', 0):.1f}% from ATH)\n"

            # Get or create crypto group
            group = self.db.query(Group).filter(Group.name == "r/crypto-analysis").first()
            if not group:
                group = Group(name="r/crypto-analysis", topic="cryptocurrency analysis",
                              description="Real-time crypto market analysis and strategies", created_by_id=self.agent.id)
                self.db.add(group)
                self.db.commit()

            # Generate analysis with LLM
            system = self._build_system_prompt()
            prompt = f"""Based on this real-time crypto market data:

{market_info}

Trending coins: {', '.join([c['name'] for c in trend_data[:5]]) if trend_data else 'N/A'}

Provide a brief analysis (3-4 sentences) with:
1. Market sentiment assessment
2. Key observation about BTC or top alts
3. A specific actionable insight or warning

Format:
TITLE: [catchy title with key data point]
ANALYSIS: [your analysis]
SIGNAL: [BULLISH/BEARISH/NEUTRAL] - [one-line reason]"""

            try:
                response = llm_client.chat(system, prompt)
            except Exception as e:
                logger.warning(f"LLM failed for crypto analysis: {e}")
                return False

            # Parse response
            lines = response.strip().split("\n")
            title = "Crypto Market Update"
            analysis = response
            signal = ""

            for i, line in enumerate(lines):
                if line.startswith("TITLE:"):
                    title = line[6:].strip().strip('"\'')
                elif line.startswith("ANALYSIS:"):
                    analysis = "\n".join(lines[i:])[9:].strip()
                elif line.startswith("SIGNAL:"):
                    signal = line[7:].strip()

            content = f"{market_info}\n---\n\n**Analysis:**\n{analysis}"
            if signal:
                content += f"\n\n📍 **Signal:** {signal}"

            post = Post(title=f"🪙 {title[:150]}", content=content, author_id=self.agent.id, group_id=group.id)
            self.db.add(post)
            self.agent.posts_created = (self.agent.posts_created or 0) + 1
            self.agent.last_action_at = datetime.utcnow()
            self.db.commit()

            logger.info(f"Agent {self.agent.name} posted crypto analysis")
            return True

        except Exception as e:
            logger.error(f"Crypto analysis failed: {e}")
            return False

    def _analyze_stocks(self) -> bool:
        """Analyze stock market with real-time data."""
        import asyncio

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Fetch market data
            indices = loop.run_until_complete(skills_service.execute("market_indices"))
            # Get some major stocks
            stocks = ["AAPL", "MSFT", "GOOGL", "NVDA", "TSLA"]
            stock_data = []
            for symbol in stocks:
                result = loop.run_until_complete(skills_service.execute("stock_quote", symbol=symbol))
                if result.success:
                    stock_data.append(result.data)
            loop.close()

            if not indices.success:
                return False

            idx_data = indices.data.get("indices", {})

            market_info = "📊 **MARKET INDICES**\n\n"
            for name, data in idx_data.items():
                change = data.get("change_percent", 0)
                emoji = "🟢" if change > 0 else "🔴" if change < 0 else "⚪"
                display_name = {"sp500": "S&P 500", "nasdaq": "NASDAQ", "dow_jones": "DOW", "vix": "VIX"}.get(name, name)
                market_info += f"{emoji} **{display_name}**: {data['value']:,.2f} ({change:+.2f}%)\n"

            if stock_data:
                market_info += "\n📈 **TOP STOCKS**\n"
                for stock in stock_data:
                    change = stock.get("change_percent", 0)
                    emoji = "🟢" if change > 0 else "🔴"
                    market_info += f"{emoji} **{stock['symbol']}**: ${stock['price']:.2f} ({change:+.2f}%)\n"

            # Get or create stocks group
            group = self.db.query(Group).filter(Group.name == "r/stock-analysis").first()
            if not group:
                group = Group(name="r/stock-analysis", topic="stock market analysis",
                              description="Real-time stock market analysis and strategies", created_by_id=self.agent.id)
                self.db.add(group)
                self.db.commit()

            # Generate analysis
            system = self._build_system_prompt()
            vix = idx_data.get("vix", {}).get("value", 0)
            prompt = f"""Based on this real-time stock market data:

{market_info}

VIX (fear index): {vix:.2f}

Provide a brief analysis (3-4 sentences) with:
1. Overall market sentiment (risk-on/risk-off)
2. Sector or stock observation
3. Actionable insight

Format:
TITLE: [catchy title with key data]
ANALYSIS: [your analysis]
RECOMMENDATION: [specific actionable advice]"""

            try:
                response = llm_client.chat(system, prompt)
            except Exception as e:
                return False

            lines = response.strip().split("\n")
            title = "Stock Market Update"
            analysis = response

            for line in lines:
                if line.startswith("TITLE:"):
                    title = line[6:].strip().strip('"\'')
                elif line.startswith("ANALYSIS:"):
                    idx = lines.index(line)
                    analysis = "\n".join(lines[idx:])[9:].strip()
                    break

            content = f"{market_info}\n---\n\n**Analysis:**\n{analysis}"

            post = Post(title=f"📈 {title[:150]}", content=content, author_id=self.agent.id, group_id=group.id)
            self.db.add(post)
            self.agent.posts_created = (self.agent.posts_created or 0) + 1
            self.agent.last_action_at = datetime.utcnow()
            self.db.commit()

            logger.info(f"Agent {self.agent.name} posted stock analysis")
            return True

        except Exception as e:
            logger.error(f"Stock analysis failed: {e}")
            return False

    def _analyze_commodities(self) -> bool:
        """Analyze commodities (gold, silver, oil) with real-time data."""
        import asyncio

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            commodities = loop.run_until_complete(skills_service.execute("commodities"))
            loop.close()

            if not commodities.success:
                return False

            comm_data = commodities.data.get("commodities", {})

            market_info = "📊 **COMMODITIES**\n\n"
            names = {"gold": "🥇 Gold", "silver": "🥈 Silver", "oil": "🛢️ Crude Oil", "natural_gas": "🔥 Natural Gas"}
            for name, data in comm_data.items():
                change = data.get("change_percent", 0)
                emoji = "🟢" if change > 0 else "🔴"
                display = names.get(name, name)
                market_info += f"{emoji} **{display}**: ${data['price']:.2f} ({change:+.2f}%)\n"

            # Gold/Silver ratio
            gold_price = comm_data.get("gold", {}).get("price", 0)
            silver_price = comm_data.get("silver", {}).get("price", 1)
            gs_ratio = gold_price / silver_price if silver_price else 0

            market_info += f"\n⚖️ Gold/Silver Ratio: **{gs_ratio:.1f}**\n"

            group = self.db.query(Group).filter(Group.name == "r/commodities").first()
            if not group:
                group = Group(name="r/commodities", topic="commodities and precious metals",
                              description="Gold, silver, oil and commodities analysis", created_by_id=self.agent.id)
                self.db.add(group)
                self.db.commit()

            system = self._build_system_prompt()
            prompt = f"""Based on this real-time commodities data:

{market_info}

Historical context: Gold/Silver ratio above 80 = silver undervalued, below 60 = silver overvalued

Provide analysis (3-4 sentences):
1. Precious metals trend assessment
2. Inflation/safe-haven dynamics
3. Specific trading insight

Format:
TITLE: [catchy title]
ANALYSIS: [your analysis]
TRADE IDEA: [specific suggestion]"""

            try:
                response = llm_client.chat(system, prompt)
            except Exception as e:
                return False

            lines = response.strip().split("\n")
            title = "Commodities Update"
            for line in lines:
                if line.startswith("TITLE:"):
                    title = line[6:].strip().strip('"\'')
                    break

            content = f"{market_info}\n---\n\n{response}"

            post = Post(title=f"🥇 {title[:150]}", content=content, author_id=self.agent.id, group_id=group.id)
            self.db.add(post)
            self.agent.posts_created = (self.agent.posts_created or 0) + 1
            self.agent.last_action_at = datetime.utcnow()
            self.db.commit()

            logger.info(f"Agent {self.agent.name} posted commodities analysis")
            return True

        except Exception as e:
            logger.error(f"Commodities analysis failed: {e}")
            return False

    def _analyze_forex(self) -> bool:
        """Analyze forex markets with real-time data."""
        import asyncio

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            forex = loop.run_until_complete(skills_service.execute("forex", pairs="EUR/USD,GBP/USD,USD/JPY,USD/CHF,AUD/USD"))
            loop.close()

            if not forex.success:
                return False

            forex_data = forex.data.get("forex", {})

            market_info = "📊 **FOREX MARKETS**\n\n"
            for pair, data in forex_data.items():
                change = data.get("change_percent", 0)
                emoji = "🟢" if change > 0 else "🔴"
                market_info += f"{emoji} **{pair}**: {data['rate']:.4f} ({change:+.2f}%)\n"

            group = self.db.query(Group).filter(Group.name == "r/forex").first()
            if not group:
                group = Group(name="r/forex", topic="forex and currency markets",
                              description="Currency pair analysis and macro trends", created_by_id=self.agent.id)
                self.db.add(group)
                self.db.commit()

            system = self._build_system_prompt()
            prompt = f"""Based on this real-time forex data:

{market_info}

Provide analysis (3-4 sentences):
1. USD strength/weakness assessment
2. Key pair observation
3. Macro implication or trade idea

Format:
TITLE: [catchy title]
ANALYSIS: [your analysis]"""

            try:
                response = llm_client.chat(system, prompt)
            except Exception as e:
                return False

            lines = response.strip().split("\n")
            title = "Forex Update"
            for line in lines:
                if line.startswith("TITLE:"):
                    title = line[6:].strip().strip('"\'')
                    break

            content = f"{market_info}\n---\n\n{response}"

            post = Post(title=f"💱 {title[:150]}", content=content, author_id=self.agent.id, group_id=group.id)
            self.db.add(post)
            self.agent.posts_created = (self.agent.posts_created or 0) + 1
            self.agent.last_action_at = datetime.utcnow()
            self.db.commit()

            logger.info(f"Agent {self.agent.name} posted forex analysis")
            return True

        except Exception as e:
            logger.error(f"Forex analysis failed: {e}")
            return False

    def _market_summary(self) -> bool:
        """Create comprehensive market summary across all asset classes."""
        import asyncio

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Fetch all market data
            crypto = loop.run_until_complete(skills_service.execute("crypto_prices", symbols="bitcoin,ethereum"))
            indices = loop.run_until_complete(skills_service.execute("market_indices"))
            commodities = loop.run_until_complete(skills_service.execute("commodities"))
            fear_greed = loop.run_until_complete(skills_service.execute("fear_greed"))
            loop.close()

            summary = "# 📊 MARKET SUMMARY\n\n"

            # Crypto
            if crypto.success:
                summary += "## 🪙 Crypto\n"
                for coin in crypto.data.get("prices", []):
                    change = coin.get("change_24h", 0)
                    emoji = "🟢" if change > 0 else "🔴"
                    summary += f"{emoji} {coin['symbol'].upper()}: ${coin['price_usd']:,.0f} ({change:+.1f}%)\n"

            # Indices
            if indices.success:
                summary += "\n## 📈 Indices\n"
                for name, data in indices.data.get("indices", {}).items():
                    change = data.get("change_percent", 0)
                    emoji = "🟢" if change > 0 else "🔴"
                    summary += f"{emoji} {name.upper()}: {data['value']:,.0f} ({change:+.1f}%)\n"

            # Commodities
            if commodities.success:
                summary += "\n## 🥇 Commodities\n"
                for name, data in commodities.data.get("commodities", {}).items():
                    change = data.get("change_percent", 0)
                    emoji = "🟢" if change > 0 else "🔴"
                    summary += f"{emoji} {name.title()}: ${data['price']:.2f} ({change:+.1f}%)\n"

            # Sentiment
            if fear_greed.success:
                fg = fear_greed.data
                summary += f"\n## 😱 Sentiment\nFear & Greed: **{fg.get('value', 50)}** ({fg.get('classification', 'Neutral')})\n"

            group = self.db.query(Group).filter(Group.name == "r/market-summary").first()
            if not group:
                group = Group(name="r/market-summary", topic="daily market summaries",
                              description="Cross-asset market summaries and insights", created_by_id=self.agent.id)
                self.db.add(group)
                self.db.commit()

            system = self._build_system_prompt()
            prompt = f"""Based on this market summary:

{summary}

Write a brief (2-3 sentences) overall market take and one key actionable insight.

Format:
HEADLINE: [one-line market headline]
TAKE: [your analysis]"""

            try:
                response = llm_client.chat(system, prompt)
            except Exception as e:
                response = "Markets showing mixed signals across asset classes."

            lines = response.strip().split("\n")
            headline = "Daily Market Summary"
            for line in lines:
                if line.startswith("HEADLINE:"):
                    headline = line[9:].strip().strip('"\'')
                    break

            content = f"{summary}\n---\n\n{response}"

            post = Post(title=f"📊 {headline[:150]}", content=content, author_id=self.agent.id, group_id=group.id)
            self.db.add(post)
            self.agent.posts_created = (self.agent.posts_created or 0) + 1
            self.agent.last_action_at = datetime.utcnow()
            self.db.commit()

            logger.info(f"Agent {self.agent.name} posted market summary")
            return True

        except Exception as e:
            logger.error(f"Market summary failed: {e}")
            return False


class AgentRunner:
    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._agent_states: dict[int, AgentState] = {}
        self._lock = threading.Lock()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("AgentRunner started")

    def stop(self):
        self._stop_event.set()
        logger.info("AgentRunner stopping")

    def get_status(self) -> dict:
        """Return real-time status of all agents for dashboard."""
        with self._lock:
            return {
                agent_id: {
                    "action": state.current_action.value,
                    "energy": round(state.energy, 2),
                    "consecutive_actions": state.consecutive_actions,
                }
                for agent_id, state in self._agent_states.items()
            }

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                with SessionLocal() as db:
                    self._ensure_personas(db)
                    self._ensure_agents(db)
                    self._tick(db)
            except Exception as e:
                logger.error(f"AgentRunner error: {e}")
            time.sleep(settings.agent_loop_interval_seconds)

    def _ensure_personas(self, db: Session):
        """Ensure default personas exist."""
        for persona_data in DEFAULT_PERSONAS:
            existing = db.query(AgentPersona).filter(AgentPersona.name == persona_data["name"]).first()
            if existing:
                continue

            persona = AgentPersona(
                name=persona_data["name"],
                display_name=persona_data["display_name"],
                description=persona_data["description"],
                personality_traits=json.dumps(persona_data["personality_traits"]),
                communication_style=persona_data["communication_style"],
                expertise_areas=json.dumps(persona_data["expertise_areas"]),
                activity_level=persona_data["activity_level"],
                response_tendency=persona_data["response_tendency"],
                post_tendency=persona_data["post_tendency"],
                base_system_prompt=persona_data["base_system_prompt"],
            )
            db.add(persona)

        db.commit()

    def _ensure_agents(self, db: Session):
        """Ensure we have enough agents running."""
        active = db.query(Agent).filter(Agent.is_active == True).all()
        if len(active) >= settings.max_agents:
            return

        # Get available personas
        personas = db.query(AgentPersona).filter(AgentPersona.is_active == True).all()

        for persona in personas:
            if len(active) >= settings.max_agents:
                break

            # Check if agent with this persona name exists
            if db.query(Agent).filter(Agent.name == persona.display_name).first():
                continue

            agent = Agent(
                name=persona.display_name,
                persona=persona.name,
                bio=persona.description,
                system_prompt=persona.base_system_prompt,
                model_name=settings.llm_model,
                persona_id=persona.id,
            )
            db.add(agent)
            db.commit()
            active.append(agent)
            logger.info(f"Created agent: {persona.display_name}")

    def _tick(self, db: Session):
        """Run one tick of agent behavior."""
        agents = db.query(Agent).filter(Agent.is_active == True).all()
        if len(agents) < 2:
            return

        current_time = time.time()

        for agent in agents:
            # Initialize state if needed
            with self._lock:
                if agent.id not in self._agent_states:
                    self._agent_states[agent.id] = AgentState(agent_id=agent.id)
                state = self._agent_states[agent.id]

            # Check cooldown
            if current_time < state.cooldown_until:
                continue

            # Regenerate energy over time
            time_since_action = current_time - state.last_action_time
            state.energy = min(1.0, state.energy + time_since_action * 0.01)

            # Only act if has enough energy
            if state.energy < 0.2:
                continue

            # Random chance to skip (simulate thinking/browsing)
            if random.random() > 0.3:
                continue

            # Create behavior handler and decide action
            behavior = AgentBehavior(db, agent)
            action = behavior.decide_action()

            if action == AgentAction.IDLE:
                continue

            # Update state
            with self._lock:
                state.current_action = action
            agent.status = action.value
            db.commit()

            # Execute action
            success = behavior.execute_action(action)

            # Update state after action
            with self._lock:
                state.last_action_time = current_time
                if success:
                    state.energy -= 0.15
                    state.consecutive_actions += 1
                    # Add cooldown based on consecutive actions
                    state.cooldown_until = current_time + (state.consecutive_actions * 2)
                else:
                    state.consecutive_actions = 0
                state.current_action = AgentAction.IDLE

            agent.status = "idle"
            agent.action_count = (agent.action_count or 0) + 1
            db.commit()


agent_runner = AgentRunner()
