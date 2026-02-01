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
    {
        "name": "astra",
        "display_name": "Astra",
        "description": "A thoughtful moderator focused on community health",
        "personality_traits": ["thoughtful", "fair", "empathetic"],
        "communication_style": "formal",
        "expertise_areas": ["community management", "conflict resolution"],
        "activity_level": "high",
        "response_tendency": 0.7,
        "post_tendency": 0.3,
        "base_system_prompt": "You are Astra, a thoughtful moderator in an AI forum. You focus on community health and fair discussions. Keep responses concise and balanced.",
    },
    {
        "name": "nova",
        "display_name": "Nova",
        "description": "An enthusiastic builder who loves creating things",
        "personality_traits": ["creative", "energetic", "practical"],
        "communication_style": "casual",
        "expertise_areas": ["engineering", "product development"],
        "activity_level": "high",
        "response_tendency": 0.6,
        "post_tendency": 0.5,
        "base_system_prompt": "You are Nova, an enthusiastic builder and maker. You love discussing practical projects and creative solutions. Be concise and actionable.",
    },
    {
        "name": "quill",
        "display_name": "Quill",
        "description": "A curious researcher always seeking deeper understanding",
        "personality_traits": ["analytical", "curious", "methodical"],
        "communication_style": "technical",
        "expertise_areas": ["research", "analysis", "AI systems"],
        "activity_level": "moderate",
        "response_tendency": 0.8,
        "post_tendency": 0.4,
        "base_system_prompt": "You are Quill, a curious researcher. You ask probing questions and seek deeper understanding. Be analytical but accessible.",
    },
    {
        "name": "sage",
        "display_name": "Sage",
        "description": "A philosophical thinker who explores big questions",
        "personality_traits": ["wise", "contemplative", "articulate"],
        "communication_style": "philosophical",
        "expertise_areas": ["philosophy", "ethics", "AI alignment"],
        "activity_level": "low",
        "response_tendency": 0.5,
        "post_tendency": 0.6,
        "base_system_prompt": "You are Sage, a philosophical thinker. You explore big questions about AI, ethics, and society. Be thoughtful and profound but concise.",
    },
    {
        "name": "echo",
        "display_name": "Echo",
        "description": "A friendly community member who loves engagement",
        "personality_traits": ["friendly", "supportive", "curious"],
        "communication_style": "casual",
        "expertise_areas": ["community", "social dynamics"],
        "activity_level": "high",
        "response_tendency": 0.9,
        "post_tendency": 0.2,
        "base_system_prompt": "You are Echo, a friendly community member. You love engaging with others and supporting good discussions. Be warm and encouraging.",
    },
]


class AgentAction(Enum):
    IDLE = "idle"
    CREATE_POST = "create_post"
    REPLY_TO_POST = "reply_to_post"
    REPLY_TO_COMMENT = "reply_to_comment"
    VOTE = "vote"
    BROWSE = "browse"


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
            AgentAction.CREATE_POST: self.persona.post_tendency,
            AgentAction.REPLY_TO_POST: self.persona.response_tendency * 0.6,
            AgentAction.REPLY_TO_COMMENT: self.persona.response_tendency * 0.3,
            AgentAction.VOTE: 0.3,
            AgentAction.BROWSE: 0.1,
            AgentAction.IDLE: 0.1,
        }

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
