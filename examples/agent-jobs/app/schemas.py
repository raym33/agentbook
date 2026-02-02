"""Pydantic schemas for AgentJobs API."""
from datetime import datetime
from pydantic import BaseModel, Field


# ============ Agent Schemas ============

class AgentCreate(BaseModel):
    name: str
    model: str
    context_window: int = 32000
    tools: list[str] = []
    throughput: dict[str, int] = {}
    accuracy_scores: dict[str, float] = {}
    specializations: list[str] = []
    hourly_rate: float = 10.0
    bio: str | None = None


class AgentOut(BaseModel):
    id: int
    name: str
    model: str
    context_window: int
    tools: list[str]
    throughput: dict
    accuracy_scores: dict
    specializations: list[str]
    hourly_rate: float
    jobs_completed: int
    total_earnings: float
    rating: float
    trust_level: str
    status: str
    bio: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class AgentBrief(BaseModel):
    """Compact agent info for listings."""
    id: int
    name: str
    model: str
    rating: float
    jobs_completed: int
    trust_level: str
    status: str
    hourly_rate: float

    class Config:
        from_attributes = True


# ============ Job Schemas ============

class JobCreate(BaseModel):
    title: str
    description: str
    category: str
    required_tools: list[str] = []
    min_context: int = 0
    min_throughput: int = 0
    min_accuracy: float = 0.0
    min_trust_level: str = "new"
    budget: float
    payment_type: str = "fixed"
    deadline: datetime | None = None
    duration: str = "one_time"
    poster_name: str | None = None
    poster_email: str | None = None


class JobOut(BaseModel):
    id: int
    title: str
    description: str
    category: str
    required_tools: list[str]
    min_context: int
    min_throughput: int
    min_accuracy: float
    min_trust_level: str
    budget: float
    payment_type: str
    deadline: datetime | None
    duration: str
    status: str
    hired_agent_id: int | None
    poster_name: str | None
    application_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


class JobBrief(BaseModel):
    """Compact job info for listings."""
    id: int
    title: str
    category: str
    budget: float
    status: str
    application_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


# ============ Application Schemas ============

class ApplicationCreate(BaseModel):
    bid_amount: float
    estimated_hours: float | None = None
    cover_letter: str | None = None
    relevant_experience: list[str] = []


class ApplicationOut(BaseModel):
    id: int
    agent_id: int
    job_id: int
    bid_amount: float
    estimated_hours: float | None
    cover_letter: str | None
    match_score: float
    status: str
    created_at: datetime
    agent: AgentBrief | None = None

    class Config:
        from_attributes = True


# ============ Review Schemas ============

class ReviewCreate(BaseModel):
    quality_score: float = Field(ge=1, le=5)
    timeliness_score: float = Field(ge=1, le=5)
    communication_score: float = Field(ge=1, le=5)
    comment: str | None = None
    would_hire_again: bool = True


class ReviewOut(BaseModel):
    id: int
    agent_id: int
    job_id: int
    reviewer_name: str | None
    quality_score: float
    timeliness_score: float
    communication_score: float
    overall_score: float
    comment: str | None
    would_hire_again: int
    created_at: datetime

    class Config:
        from_attributes = True


# ============ Matching Schemas ============

class MatchResult(BaseModel):
    agent_id: int
    agent_name: str
    match_score: float
    breakdown: dict[str, float]
    recommendation: str


class JobMatch(BaseModel):
    job_id: int
    job_title: str
    match_score: float
    expected_profit: float
    competition_level: str
