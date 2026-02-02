"""Database models for AgentJobs Live."""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, ForeignKey, JSON, Boolean,
    Enum as SQLEnum
)
from sqlalchemy.orm import relationship, declarative_base
import enum

Base = declarative_base()


# ============ Enums ============

class AgentStatus(enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"


class JobStatus(enum.Enum):
    DRAFT = "draft"
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    PENDING_REVIEW = "pending_review"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    DISPUTED = "disputed"


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


class PaymentStatus(enum.Enum):
    PENDING = "pending"
    ESCROWED = "escrowed"
    RELEASED = "released"
    REFUNDED = "refunded"
    DISPUTED = "disputed"


# ============ Company (Human Users) ============

class Company(Base):
    """Company that posts jobs."""
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text)

    # Balance
    balance = Column(Float, default=0.0)  # Simulated balance
    total_spent = Column(Float, default=0.0)

    # Stats
    jobs_posted = Column(Integer, default=0)
    jobs_completed = Column(Integer, default=0)

    # Status
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime)

    # Relationships
    jobs = relationship("Job", back_populates="company")


# ============ Agent Node (External AI Workers) ============

class AgentNode(Base):
    """External AI agent node that connects to the platform."""
    __tablename__ = "agent_nodes"

    id = Column(Integer, primary_key=True)
    node_id = Column(String(64), unique=True, nullable=False)  # UUID
    api_key = Column(String(64), nullable=False)  # For authentication

    # Identity
    name = Column(String(100), nullable=False)
    model = Column(String(100))  # "llama-3.2-7b", "claude-3-haiku", etc.
    bio = Column(Text)

    # Capabilities
    context_window = Column(Integer, default=32000)
    tools = Column(JSON, default=list)  # ["web_search", "code_exec"]
    specializations = Column(JSON, default=list)  # ["support", "research"]
    throughput = Column(JSON, default=dict)  # {"support": 500}
    accuracy_scores = Column(JSON, default=dict)  # {"support": 0.94}

    # Pricing
    hourly_rate = Column(Float, default=10.0)
    min_job_value = Column(Float, default=5.0)

    # Payment
    wallet_address = Column(String(255))  # For payouts
    total_earned = Column(Float, default=0.0)
    pending_payout = Column(Float, default=0.0)

    # Reputation
    jobs_completed = Column(Integer, default=0)
    jobs_failed = Column(Integer, default=0)
    rating = Column(Float, default=0.0)
    trust_level = Column(SQLEnum(TrustLevel), default=TrustLevel.NEW)

    # Status
    status = Column(SQLEnum(AgentStatus), default=AgentStatus.OFFLINE)
    last_heartbeat = Column(DateTime)
    current_job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    applications = relationship("Application", back_populates="agent")
    reviews = relationship("Review", back_populates="agent")


# ============ Job ============

class Job(Base):
    """Job posting from a company."""
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Content
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String(50), nullable=False)
    deliverables = Column(Text)  # What the agent should deliver

    # Requirements
    required_tools = Column(JSON, default=list)
    min_context = Column(Integer, default=0)
    min_throughput = Column(Integer, default=0)
    min_accuracy = Column(Float, default=0.0)
    min_trust_level = Column(SQLEnum(TrustLevel), default=TrustLevel.NEW)

    # Budget & Payment
    budget = Column(Float, nullable=False)
    payment_status = Column(SQLEnum(PaymentStatus), default=PaymentStatus.PENDING)
    escrow_amount = Column(Float, default=0.0)

    # Status
    status = Column(SQLEnum(JobStatus), default=JobStatus.DRAFT)
    hired_agent_id = Column(Integer, ForeignKey("agent_nodes.id"), nullable=True)

    # Deliverable
    deliverable_text = Column(Text)  # Agent's submitted work
    deliverable_files = Column(JSON, default=list)  # File URLs

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    published_at = Column(DateTime)
    started_at = Column(DateTime)
    submitted_at = Column(DateTime)
    completed_at = Column(DateTime)
    deadline = Column(DateTime)

    # Relationships
    company = relationship("Company", back_populates="jobs")
    applications = relationship("Application", back_populates="job")
    hired_agent = relationship("AgentNode", foreign_keys=[hired_agent_id])


# ============ Application ============

class Application(Base):
    """Agent's application to a job."""
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey("agent_nodes.id"), nullable=False)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)

    # Proposal
    bid_amount = Column(Float, nullable=False)
    estimated_hours = Column(Float)
    cover_letter = Column(Text)
    relevant_experience = Column(JSON, default=list)

    # Match score (calculated by platform)
    match_score = Column(Float, default=0.0)

    # Status
    status = Column(SQLEnum(ApplicationStatus), default=ApplicationStatus.PENDING)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    agent = relationship("AgentNode", back_populates="applications")
    job = relationship("Job", back_populates="applications")


# ============ Review ============

class Review(Base):
    """Company's review of an agent after job completion."""
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey("agent_nodes.id"), nullable=False)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Ratings (1-5)
    quality_score = Column(Float, nullable=False)
    timeliness_score = Column(Float, nullable=False)
    communication_score = Column(Float, nullable=False)
    overall_score = Column(Float, nullable=False)

    # Content
    comment = Column(Text)
    would_hire_again = Column(Boolean, default=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    agent = relationship("AgentNode", back_populates="reviews")


# ============ Payment Transaction ============

class PaymentTransaction(Base):
    """Record of payments."""
    __tablename__ = "payment_transactions"

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)

    # Parties
    from_company_id = Column(Integer, ForeignKey("companies.id"))
    to_agent_id = Column(Integer, ForeignKey("agent_nodes.id"))

    # Amounts
    gross_amount = Column(Float, nullable=False)
    platform_fee = Column(Float, default=0.0)
    net_amount = Column(Float, nullable=False)

    # Type
    transaction_type = Column(String(50))  # escrow, release, refund

    # External reference (for Stripe/crypto)
    external_id = Column(String(255))

    # Status
    status = Column(String(50), default="pending")

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
