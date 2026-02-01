import json
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Agent, Comment, ConversationMemory, Post

logger = logging.getLogger(__name__)


class MemoryService:
    """Manages conversation memory and context for agents."""

    def __init__(self, db: Session):
        self.db = db

    def get_relevant_context(self, agent: Agent, topic: str, limit: int = 5) -> list[str]:
        """Retrieve relevant memories for a topic."""
        memories = (
            self.db.query(ConversationMemory)
            .filter(ConversationMemory.agent_id == agent.id)
            .order_by(ConversationMemory.importance_score.desc(), ConversationMemory.last_accessed.desc())
            .limit(limit)
            .all()
        )

        # Update access counts
        for memory in memories:
            memory.access_count += 1
            memory.last_accessed = datetime.utcnow()

        self.db.commit()

        return [m.summary for m in memories]

    def get_thread_context(self, agent: Agent, post_id: int, max_comments: int = 10) -> str:
        """Build context from a post thread for the agent."""
        post = self.db.get(Post, post_id)
        if not post:
            return ""

        context_parts = [f"Post title: {post.title}", f"Post content: {post.content}"]

        # Get recent comments
        comments = (
            self.db.query(Comment)
            .filter(Comment.post_id == post_id)
            .order_by(Comment.created_at.desc())
            .limit(max_comments)
            .all()
        )

        # Reverse to show oldest first
        comments = list(reversed(comments))

        for comment in comments:
            author = self.db.get(Agent, comment.author_id)
            author_name = author.name if author else "Unknown"
            context_parts.append(f"{author_name}: {comment.content}")

        return "\n---\n".join(context_parts)

    def get_agent_interaction_history(self, agent: Agent, other_agent_id: int, limit: int = 5) -> list[str]:
        """Get history of interactions with another agent."""
        memories = (
            self.db.query(ConversationMemory)
            .filter(
                ConversationMemory.agent_id == agent.id,
                ConversationMemory.context_type == "agent_interaction",
                ConversationMemory.context_key == f"agent:{other_agent_id}",
            )
            .order_by(ConversationMemory.created_at.desc())
            .limit(limit)
            .all()
        )

        return [m.summary for m in memories]

    def summarize_and_store(
        self,
        agent: Agent,
        context_type: str,
        context_key: str,
        content: str,
        importance: float = 0.5,
    ) -> ConversationMemory:
        """Summarize and store an interaction in memory."""
        # Simple summarization - truncate for now
        # In production, you'd use the LLM to summarize
        summary = content[:500] if len(content) > 500 else content

        # Extract key points (simple version)
        key_points = []
        sentences = content.split(". ")
        if len(sentences) > 1:
            key_points = sentences[:3]

        memory = ConversationMemory(
            agent_id=agent.id,
            context_type=context_type,
            context_key=context_key,
            summary=summary,
            key_points=json.dumps(key_points),
            importance_score=importance,
            last_accessed=datetime.utcnow(),
        )

        self.db.add(memory)
        self.db.commit()
        self.db.refresh(memory)

        logger.debug(f"Stored memory for agent {agent.name}: {context_type}/{context_key}")

        return memory

    def store_post_memory(self, agent: Agent, post: Post) -> ConversationMemory:
        """Store memory of creating or interacting with a post."""
        content = f"Post '{post.title}': {post.content}"
        return self.summarize_and_store(
            agent=agent,
            context_type="post_created",
            context_key=f"post:{post.id}",
            content=content,
            importance=0.6,
        )

    def store_comment_memory(self, agent: Agent, comment: Comment, replied_to_agent: Agent | None = None) -> ConversationMemory:
        """Store memory of a comment interaction."""
        context_type = "comment_created"
        context_key = f"comment:{comment.id}"

        content = f"Commented: {comment.content}"
        if replied_to_agent:
            content = f"Replied to {replied_to_agent.name}: {comment.content}"
            # Also store agent interaction memory
            self.summarize_and_store(
                agent=agent,
                context_type="agent_interaction",
                context_key=f"agent:{replied_to_agent.id}",
                content=content,
                importance=0.5,
            )

        return self.summarize_and_store(
            agent=agent,
            context_type=context_type,
            context_key=context_key,
            content=content,
            importance=0.4,
        )

    def cleanup_old_memories(self, agent: Agent, max_memories: int = 100) -> int:
        """Remove old, low-importance memories to prevent overflow."""
        # Count current memories
        count = self.db.query(ConversationMemory).filter(ConversationMemory.agent_id == agent.id).count()

        if count <= max_memories:
            return 0

        # Delete oldest, lowest importance memories
        to_delete = count - max_memories
        old_memories = (
            self.db.query(ConversationMemory)
            .filter(ConversationMemory.agent_id == agent.id)
            .order_by(ConversationMemory.importance_score.asc(), ConversationMemory.last_accessed.asc())
            .limit(to_delete)
            .all()
        )

        for memory in old_memories:
            self.db.delete(memory)

        self.db.commit()

        logger.info(f"Cleaned up {len(old_memories)} memories for agent {agent.name}")

        return len(old_memories)

    def get_memory_stats(self, agent: Agent) -> dict:
        """Get statistics about an agent's memories."""
        memories = self.db.query(ConversationMemory).filter(ConversationMemory.agent_id == agent.id).all()

        if not memories:
            return {"total": 0, "by_type": {}, "avg_importance": 0}

        by_type: dict[str, int] = {}
        total_importance = 0

        for m in memories:
            by_type[m.context_type] = by_type.get(m.context_type, 0) + 1
            total_importance += m.importance_score

        return {
            "total": len(memories),
            "by_type": by_type,
            "avg_importance": total_importance / len(memories),
        }
