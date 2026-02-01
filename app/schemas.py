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
