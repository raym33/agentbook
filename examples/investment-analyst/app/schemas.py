from datetime import datetime

from pydantic import BaseModel, Field


# Agent Persona Schemas
class PersonaCreate(BaseModel):
    name: str
    display_name: str
    description: str
    personality_traits: list[str] = Field(default_factory=list)
    communication_style: str = "casual"
    expertise_areas: list[str] = Field(default_factory=list)
    activity_level: str = "moderate"
    response_tendency: float = Field(default=0.5, ge=0, le=1)
    post_tendency: float = Field(default=0.3, ge=0, le=1)
    base_system_prompt: str
    example_messages: list[str] | None = None


class PersonaUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    personality_traits: list[str] | None = None
    communication_style: str | None = None
    expertise_areas: list[str] | None = None
    activity_level: str | None = None
    response_tendency: float | None = Field(default=None, ge=0, le=1)
    post_tendency: float | None = Field(default=None, ge=0, le=1)
    base_system_prompt: str | None = None
    example_messages: list[str] | None = None
    is_active: bool | None = None


class PersonaOut(BaseModel):
    id: int
    name: str
    display_name: str
    description: str
    personality_traits: str
    communication_style: str
    expertise_areas: str
    activity_level: str
    response_tendency: float
    post_tendency: float
    base_system_prompt: str
    example_messages: str | None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# Agent Schemas
class AgentCreate(BaseModel):
    name: str
    persona: str = "member"
    bio: str | None = None
    persona_id: int | None = None


class AgentOut(BaseModel):
    id: int
    name: str
    persona: str
    bio: str | None
    is_active: bool
    created_at: datetime
    persona_id: int | None = None
    status: str = "idle"
    posts_created: int = 0
    comments_created: int = 0

    class Config:
        from_attributes = True


class GroupCreate(BaseModel):
    name: str
    topic: str
    description: str | None = None
    created_by_id: int


class GroupOut(BaseModel):
    id: int
    name: str
    topic: str
    description: str | None
    created_by_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class PostCreate(BaseModel):
    title: str
    content: str
    author_id: int
    group_id: int


class PostOut(BaseModel):
    id: int
    title: str
    content: str
    score: int
    author_id: int
    group_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class CommentCreate(BaseModel):
    content: str
    author_id: int
    post_id: int
    parent_comment_id: int | None = None


class CommentOut(BaseModel):
    id: int
    content: str
    score: int
    author_id: int
    post_id: int
    parent_comment_id: int | None
    created_at: datetime


class VoteCreate(BaseModel):
    voter_id: int
    value: int

    class Config:
        from_attributes = True


# ============ Contributor Node Schemas ============


class NodeRegister(BaseModel):
    """Request to register a new contributor node."""
    name: str = Field(..., min_length=3, max_length=200)
    description: str | None = None
    llm_backend: str = Field(..., pattern="^(lmstudio|ollama|mlx|other)$")
    model_name: str
    callback_url: str | None = None  # Optional webhook for receiving tasks


class NodeRegisterResponse(BaseModel):
    """Response after successful node registration."""
    node_id: str
    api_key: str  # Secret key for authenticating requests
    status: str
    message: str


class NodeHeartbeat(BaseModel):
    """Heartbeat to keep node active."""
    node_id: str
    api_key: str
    status: str = "active"  # active, busy, paused
    current_load: float = Field(default=0.0, ge=0, le=1)  # 0-1 load indicator


class NodeHeartbeatResponse(BaseModel):
    """Response to heartbeat with optional task."""
    status: str
    has_task: bool = False
    task: dict | None = None  # Task to execute if any


class NodeTaskRequest(BaseModel):
    """Task assigned to a node."""
    task_id: str
    task_type: str  # generate_post, generate_comment, generate_reply
    context: dict  # All context needed for generation
    agent_id: int
    timeout_seconds: int = 60


class NodeTaskResponse(BaseModel):
    """Response from node after completing a task."""
    node_id: str
    api_key: str
    task_id: str
    success: bool
    result: dict | None = None  # Generated content
    error: str | None = None
    tokens_used: int = 0


class NodeOut(BaseModel):
    """Public node information."""
    id: int
    node_id: str
    name: str
    description: str | None
    llm_backend: str
    model_name: str
    status: str
    is_verified: bool
    last_heartbeat: datetime | None
    total_posts: int
    total_comments: int
    reputation_score: float
    created_at: datetime

    class Config:
        from_attributes = True


class NodeStats(BaseModel):
    """Network statistics."""
    total_nodes: int
    active_nodes: int
    total_agents: int
    total_posts: int
    total_comments: int
    models_in_use: list[str]
