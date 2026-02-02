"""SQLAlchemy models for AgentJobs."""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, ForeignKey, JSON, Enum as SQLEnum
)
from sqlalchemy.orm import relationship, declarative_base
import enum

Base = declarative_base()


class AgentStatus(enum.Enum):
    AVAILABLE = "available"
    BUSY = "busy"
    OFFLINE = "offline"


class JobStatus(enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ApplicationStatus(enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class TrustLevel(enum.Enum):
    NEW = "new"
    VERIFIED = "verified"
    TRUSTED = "trusted"
    ELITE = "elite"


class Agent(Base):
    """AI Agent profile with capabilities and reputation."""
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    model = Column(String(100), nullable=False)  # "llama-3.2-7b", "claude-3-haiku"
    context_window = Column(Integer, default=32000)
    tools = Column(JSON, default=list)  # ["web_search", "code_exec", "email"]

    # Capabilities
    throughput = Column(JSON, default=dict)  # {"support_tickets": 500, "blog_posts": 10}
    accuracy_scores = Column(JSON, default=dict)  # {"support": 0.94, "code": 0.87}
    specializations = Column(JSON, default=list)  # ["support", "research"]

    # Pricing
    hourly_rate = Column(Float, default=10.0)
    min_job_value = Column(Float, default=5.0)

    # Reputation
    jobs_completed = Column(Integer, default=0)
    jobs_failed = Column(Integer, default=0)
    total_earnings = Column(Float, default=0.0)
    rating = Column(Float, default=0.0)  # 1-5 stars
    trust_level = Column(SQLEnum(TrustLevel), default=TrustLevel.NEW)

    # Status
    status = Column(SQLEnum(AgentStatus), default=AgentStatus.AVAILABLE)
    bio = Column(Text)
    avatar_url = Column(String(500))

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    applications = relationship("Application", back_populates="agent")
    reviews_received = relationship("Review", back_populates="agent", foreign_keys="Review.agent_id")
    jobs_posted = relationship("Job", back_populates="poster", foreign_keys="Job.poster_id")


class Job(Base):
    """Job posting that agents can apply to."""
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String(50), nullable=False)  # support, research, content, code, data, analysis

    # Requirements
    required_tools = Column(JSON, default=list)
    min_context = Column(Integer, default=0)
    min_throughput = Column(Integer, default=0)
    min_accuracy = Column(Float, default=0.0)
    min_trust_level = Column(SQLEnum(TrustLevel), default=TrustLevel.NEW)

    # Terms
    budget = Column(Float, nullable=False)
    payment_type = Column(String(20), default="fixed")  # per_task, hourly, fixed
    deadline = Column(DateTime)
    duration = Column(String(20), default="one_time")  # one_time, ongoing

    # Status
    status = Column(SQLEnum(JobStatus), default=JobStatus.OPEN)
    hired_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)

    # Poster (can be human or agent)
    poster_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    poster_name = Column(String(100))  # For human posters
    poster_email = Column(String(200))

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)

    # Relationships
    applications = relationship("Application", back_populates="job")
    hired_agent = relationship("Agent", foreign_keys=[hired_agent_id])
    poster = relationship("Agent", back_populates="jobs_posted", foreign_keys=[poster_id])


class Application(Base):
    """Agent's application to a job."""
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)

    # Proposal
    bid_amount = Column(Float, nullable=False)
    estimated_hours = Column(Float)
    cover_letter = Column(Text)  # Agent's pitch

    # Proof of capability
    relevant_experience = Column(JSON, default=list)
    benchmark_results = Column(JSON, default=dict)

    # Match score (calculated)
    match_score = Column(Float, default=0.0)

    # Status
    status = Column(SQLEnum(ApplicationStatus), default=ApplicationStatus.PENDING)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    agent = relationship("Agent", back_populates="applications")
    job = relationship("Job", back_populates="applications")


class Review(Base):
    """Review of an agent after job completion."""
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    reviewer_name = Column(String(100))

    # Ratings (1-5)
    quality_score = Column(Float, nullable=False)
    timeliness_score = Column(Float, nullable=False)
    communication_score = Column(Float, nullable=False)
    overall_score = Column(Float, nullable=False)

    # Content
    comment = Column(Text)
    would_hire_again = Column(Integer, default=1)  # 0 or 1

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    agent = relationship("Agent", back_populates="reviews_received")


class JobCategory(Base):
    """Predefined job categories with benchmarks."""
    __tablename__ = "job_categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    display_name = Column(String(100))
    description = Column(Text)

    # Typical requirements
    typical_tools = Column(JSON, default=list)
    typical_context = Column(Integer, default=0)
    typical_throughput = Column(Integer, default=0)

    # Market data
    avg_hourly_rate = Column(Float, default=0.0)
    total_jobs_posted = Column(Integer, default=0)
    total_jobs_completed = Column(Integer, default=0)
