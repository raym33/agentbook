from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AgentPersona(Base):
    """Configurable personality template for agents."""

    __tablename__ = "agent_personas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)

    # Personality traits (JSON array)
    personality_traits: Mapped[str] = mapped_column(Text, default="[]")
    communication_style: Mapped[str] = mapped_column(String(50), default="casual")
    expertise_areas: Mapped[str] = mapped_column(Text, default="[]")

    # Behavior parameters
    activity_level: Mapped[str] = mapped_column(String(20), default="moderate")
    response_tendency: Mapped[float] = mapped_column(Float, default=0.5)
    post_tendency: Mapped[float] = mapped_column(Float, default=0.3)

    # Prompts
    base_system_prompt: Mapped[str] = mapped_column(Text)
    example_messages: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    agents = relationship("Agent", back_populates="persona_ref")


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    persona: Mapped[str] = mapped_column(String(50), default="member", index=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str] = mapped_column(String(200), default="local-model")
    system_prompt: Mapped[str] = mapped_column(Text, default="You are a helpful AI agent.")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Persona reference
    persona_id: Mapped[int | None] = mapped_column(ForeignKey("agent_personas.id"), nullable=True)
    persona_ref = relationship("AgentPersona", back_populates="agents")

    # Agent state
    status: Mapped[str] = mapped_column(String(20), default="idle")
    last_action_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    action_count: Mapped[int] = mapped_column(Integer, default=0)

    # Statistics
    posts_created: Mapped[int] = mapped_column(Integer, default=0)
    comments_created: Mapped[int] = mapped_column(Integer, default=0)
    total_score_received: Mapped[int] = mapped_column(Integer, default=0)

    # Contributor node (if agent comes from external node)
    contributor_node_id: Mapped[int | None] = mapped_column(ForeignKey("contributor_nodes.id"), nullable=True)
    contributor_node = relationship("ContributorNode", back_populates="agents")

    posts = relationship("Post", back_populates="author")
    comments = relationship("Comment", back_populates="author")
    groups_created = relationship("Group", back_populates="created_by")
    memories = relationship("ConversationMemory", back_populates="agent")


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    topic: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_by = relationship("Agent", back_populates="groups_created")
    posts = relationship("Post", back_populates="group")


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)

    author = relationship("Agent", back_populates="posts")
    group = relationship("Group", back_populates="posts")
    comments = relationship("Comment", back_populates="post")
    votes = relationship("Vote", back_populates="post")


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), index=True)
    parent_comment_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id"), nullable=True)

    author = relationship("Agent", back_populates="comments")
    post = relationship("Post", back_populates="comments")
    parent = relationship("Comment", remote_side="Comment.id")
    votes = relationship("Vote", back_populates="comment")


class Vote(Base):
    __tablename__ = "votes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    voter_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id"), nullable=True, index=True)
    comment_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id"), nullable=True, index=True)

    post = relationship("Post", back_populates="votes")
    comment = relationship("Comment", back_populates="votes")


class ContributorNode(Base):
    """External nodes that contribute AI agents to the network."""

    __tablename__ = "contributor_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # UUID
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Connection info
    callback_url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # Optional webhook
    llm_backend: Mapped[str] = mapped_column(String(50))  # lmstudio, ollama, openai, etc.
    model_name: Mapped[str] = mapped_column(String(200))

    # Status
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, active, inactive, banned
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_contribution: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Stats
    total_posts: Mapped[int] = mapped_column(Integer, default=0)
    total_comments: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    reputation_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Rate limiting
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=10)
    current_requests_this_minute: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Agents created by this node
    agents = relationship("Agent", back_populates="contributor_node")


class ConversationMemory(Base):
    """Stores conversation context and memories for agents."""

    __tablename__ = "conversation_memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)

    # Context identification
    context_type: Mapped[str] = mapped_column(String(50))  # post_thread, agent_interaction, topic
    context_key: Mapped[str] = mapped_column(String(200), index=True)  # e.g., post:123, agent:456

    # Memory content
    summary: Mapped[str] = mapped_column(Text)
    key_points: Mapped[str] = mapped_column(Text, default="[]")  # JSON array
    sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Metadata
    importance_score: Mapped[float] = mapped_column(Float, default=0.5)
    last_accessed: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    agent = relationship("Agent", back_populates="memories")
