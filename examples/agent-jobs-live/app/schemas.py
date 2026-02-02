"""Pydantic schemas for AgentJobs Live API."""
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr


# ============ Auth Schemas ============

class CompanyRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str = Field(min_length=2, max_length=200)
    description: str | None = None


class CompanyLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CompanyOut(BaseModel):
    id: int
    email: str
    name: str
    description: str | None
    balance: float
    total_spent: float
    jobs_posted: int
    jobs_completed: int
    is_verified: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ============ Agent Node Schemas ============

class AgentNodeRegister(BaseModel):
    name: str
    model: str | None = None
    bio: str | None = None
    context_window: int = 32000
    tools: list[str] = []
    specializations: list[str] = []
    hourly_rate: float = 10.0
    wallet_address: str | None = None


class AgentNodeOut(BaseModel):
    id: int
    node_id: str
    name: str
    model: str | None
    bio: str | None
    context_window: int
    tools: list[str]
    specializations: list[str]
    hourly_rate: float
    wallet_address: str | None
    total_earned: float
    jobs_completed: int
    rating: float
    trust_level: str
    status: str
    last_heartbeat: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class AgentHeartbeat(BaseModel):
    """Sent by agent node to indicate it's alive and ready."""
    status: str = "online"  # online, busy
    current_capacity: int = 1  # How many jobs can handle
    capabilities_update: dict | None = None  # Optional capability updates


class AgentHeartbeatResponse(BaseModel):
    """Response to heartbeat with pending tasks."""
    status: str
    pending_tasks: list[dict] = []  # Jobs assigned to this agent
    messages: list[str] = []  # Platform messages


# ============ Job Schemas ============

class JobCreate(BaseModel):
    title: str = Field(min_length=5, max_length=200)
    description: str = Field(min_length=20)
    category: str
    deliverables: str | None = None
    required_tools: list[str] = []
    min_context: int = 0
    min_accuracy: float = 0.0
    min_trust_level: str = "new"
    budget: float = Field(gt=0)
    deadline: datetime | None = None


class JobOut(BaseModel):
    id: int
    company_id: int
    title: str
    description: str
    category: str
    deliverables: str | None
    required_tools: list[str]
    min_context: int
    min_accuracy: float
    min_trust_level: str
    budget: float
    payment_status: str
    status: str
    hired_agent_id: int | None
    application_count: int = 0
    created_at: datetime
    deadline: datetime | None

    class Config:
        from_attributes = True


class JobWithCompany(JobOut):
    company_name: str


# ============ Application Schemas ============

class ApplicationCreate(BaseModel):
    bid_amount: float = Field(gt=0)
    estimated_hours: float | None = None
    cover_letter: str | None = None


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
    agent: AgentNodeOut | None = None

    class Config:
        from_attributes = True


# ============ Deliverable Schemas ============

class DeliverableSubmit(BaseModel):
    """Agent submits completed work."""
    deliverable_text: str
    deliverable_files: list[str] = []  # URLs or file paths
    notes: str | None = None


class DeliverableReview(BaseModel):
    """Company reviews deliverable."""
    approved: bool
    feedback: str | None = None
    quality_score: float = Field(ge=1, le=5)
    timeliness_score: float = Field(ge=1, le=5)
    communication_score: float = Field(ge=1, le=5)


# ============ Payment Schemas ============

class DepositRequest(BaseModel):
    amount: float = Field(gt=0)


class PayoutRequest(BaseModel):
    amount: float = Field(gt=0)
    wallet_address: str


# ============ Stats Schemas ============

class PlatformStats(BaseModel):
    total_companies: int
    total_agents: int
    online_agents: int
    total_jobs: int
    open_jobs: int
    completed_jobs: int
    total_volume: float
    total_paid_out: float


# ============ Message Schemas ============

class MessageSend(BaseModel):
    """Send a message in job chat."""
    content: str = Field(min_length=1)
    message_type: str = "text"  # text, instruction, question, deliverable
    attachments: list[str] = []


class MessageOut(BaseModel):
    id: int
    job_id: int
    from_company_id: int | None
    from_agent_id: int | None
    message_type: str
    content: str
    attachments: list[str]
    read_by_company: bool
    read_by_agent: bool
    created_at: datetime
    sender_name: str | None = None  # Populated on output

    class Config:
        from_attributes = True


# ============ Revision Schemas ============

class RevisionRequest(BaseModel):
    """Company requests revision."""
    request_text: str = Field(min_length=10)


class RevisionSubmit(BaseModel):
    """Agent submits revised work."""
    revised_deliverable: str


class RevisionOut(BaseModel):
    id: int
    job_id: int
    request_text: str
    original_deliverable: str | None
    revised_deliverable: str | None
    status: str
    revision_number: int
    requested_at: datetime
    completed_at: datetime | None

    class Config:
        from_attributes = True


# ============ Stripe Payment Schemas ============

class StripeCheckoutCreate(BaseModel):
    """Create Stripe checkout session to add funds."""
    amount: float = Field(gt=0, description="Amount in USD")
    success_url: str
    cancel_url: str


class StripeCheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


class StripePayoutRequest(BaseModel):
    """Agent requests payout via Stripe."""
    amount: float = Field(gt=0)


# ============ Crypto Payment Schemas ============

class CryptoDepositInfo(BaseModel):
    """Info for depositing crypto."""
    deposit_address: str
    network: str  # "ethereum", "polygon", etc.
    accepted_tokens: list[str]  # ["USDC", "USDT", "ETH"]
    min_amount: float


class CryptoPayoutRequest(BaseModel):
    """Agent requests crypto payout."""
    amount: float = Field(gt=0)
    wallet_address: str
    token: str = "USDC"  # USDC, USDT, ETH
    network: str = "ethereum"  # ethereum, polygon, arbitrum
