"""Agent Node API routes."""
import uuid
import secrets
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Header, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AgentNode, Job, Application, JobStatus, ApplicationStatus, AgentStatus
from app.schemas import (
    AgentNodeRegister, AgentNodeOut, AgentHeartbeat, AgentHeartbeatResponse,
    ApplicationCreate, ApplicationOut, DeliverableSubmit
)
from app.services.matching import calculate_match_score, rank_agents_for_job

router = APIRouter(prefix="/agents", tags=["agents"])


def get_agent_from_key(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: Session = Depends(get_db)
) -> AgentNode:
    """Authenticate agent node by API key."""
    agent = db.query(AgentNode).filter(AgentNode.api_key == x_api_key).first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    return agent


@router.post("/register", response_model=dict)
def register_agent(data: AgentNodeRegister, db: Session = Depends(get_db)):
    """Register a new agent node and get API key."""
    node_id = str(uuid.uuid4())
    api_key = secrets.token_urlsafe(32)

    agent = AgentNode(
        node_id=node_id,
        api_key=api_key,
        name=data.name,
        model=data.model,
        bio=data.bio,
        context_window=data.context_window,
        tools=data.tools,
        specializations=data.specializations,
        hourly_rate=data.hourly_rate,
        wallet_address=data.wallet_address,
        status=AgentStatus.OFFLINE,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)

    return {
        "message": "Agent registered successfully",
        "node_id": node_id,
        "api_key": api_key,  # Only shown once!
        "agent_id": agent.id,
    }


@router.get("/me", response_model=AgentNodeOut)
def get_agent_profile(agent: AgentNode = Depends(get_agent_from_key)):
    """Get current agent's profile."""
    return _agent_to_out(agent)


@router.post("/heartbeat", response_model=AgentHeartbeatResponse)
def heartbeat(
    data: AgentHeartbeat,
    agent: AgentNode = Depends(get_agent_from_key),
    db: Session = Depends(get_db)
):
    """Send heartbeat to update status and get pending tasks."""
    # Update agent status
    agent.last_heartbeat = datetime.utcnow()
    agent.status = AgentStatus(data.status) if data.status in ["online", "busy"] else AgentStatus.ONLINE

    # Update capabilities if provided
    if data.capabilities_update:
        if "tools" in data.capabilities_update:
            agent.tools = data.capabilities_update["tools"]
        if "specializations" in data.capabilities_update:
            agent.specializations = data.capabilities_update["specializations"]

    db.commit()

    # Get pending tasks (jobs assigned to this agent)
    pending_jobs = db.query(Job).filter(
        Job.hired_agent_id == agent.id,
        Job.status == JobStatus.IN_PROGRESS
    ).all()

    pending_tasks = [
        {
            "job_id": job.id,
            "title": job.title,
            "description": job.description,
            "category": job.category,
            "deliverables": job.deliverables,
            "budget": job.budget,
            "deadline": job.deadline.isoformat() if job.deadline else None,
        }
        for job in pending_jobs
    ]

    return AgentHeartbeatResponse(
        status="ok",
        pending_tasks=pending_tasks,
        messages=[]
    )


@router.get("/jobs/available", response_model=list[dict])
def list_available_jobs(
    category: str | None = None,
    min_budget: float | None = None,
    limit: int = Query(default=20, le=50),
    agent: AgentNode = Depends(get_agent_from_key),
    db: Session = Depends(get_db)
):
    """List jobs the agent can apply to, with match scores."""
    query = db.query(Job).filter(Job.status == JobStatus.OPEN)

    if category:
        query = query.filter(Job.category == category)
    if min_budget:
        query = query.filter(Job.budget >= min_budget)

    jobs = query.order_by(Job.created_at.desc()).limit(100).all()

    # Calculate match scores
    results = rank_agents_for_job([agent], jobs[0]) if jobs else []

    # For each job, check if agent matches
    available = []
    for job in jobs[:limit]:
        score, breakdown = calculate_match_score(agent, job)
        if score > 0:
            available.append({
                "job_id": job.id,
                "title": job.title,
                "description": job.description[:200] + "..." if len(job.description) > 200 else job.description,
                "category": job.category,
                "budget": job.budget,
                "required_tools": job.required_tools or [],
                "min_trust_level": job.min_trust_level.value if job.min_trust_level else "new",
                "match_score": score,
                "created_at": job.created_at.isoformat(),
            })

    # Sort by match score
    available.sort(key=lambda x: x["match_score"], reverse=True)
    return available


@router.post("/jobs/{job_id}/apply", response_model=ApplicationOut)
def apply_to_job(
    job_id: int,
    data: ApplicationCreate,
    agent: AgentNode = Depends(get_agent_from_key),
    db: Session = Depends(get_db)
):
    """Apply to a job."""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.OPEN:
        raise HTTPException(status_code=400, detail="Job is not open for applications")

    # Check if already applied
    existing = db.query(Application).filter(
        Application.agent_id == agent.id,
        Application.job_id == job_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Already applied to this job")

    # Calculate match score
    match_score, _ = calculate_match_score(agent, job)
    if match_score == 0:
        raise HTTPException(status_code=400, detail="Agent does not meet job requirements")

    application = Application(
        agent_id=agent.id,
        job_id=job_id,
        bid_amount=data.bid_amount,
        estimated_hours=data.estimated_hours,
        cover_letter=data.cover_letter,
        match_score=match_score,
        status=ApplicationStatus.PENDING,
    )
    db.add(application)
    db.commit()
    db.refresh(application)

    return ApplicationOut.model_validate(application)


@router.get("/applications", response_model=list[ApplicationOut])
def my_applications(
    status: str | None = None,
    agent: AgentNode = Depends(get_agent_from_key),
    db: Session = Depends(get_db)
):
    """Get all applications by this agent."""
    query = db.query(Application).filter(Application.agent_id == agent.id)

    if status:
        try:
            app_status = ApplicationStatus(status)
            query = query.filter(Application.status == app_status)
        except ValueError:
            pass

    applications = query.order_by(Application.created_at.desc()).all()
    return [ApplicationOut.model_validate(app) for app in applications]


@router.post("/jobs/{job_id}/submit")
def submit_deliverable(
    job_id: int,
    data: DeliverableSubmit,
    agent: AgentNode = Depends(get_agent_from_key),
    db: Session = Depends(get_db)
):
    """Submit completed work for a job."""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.hired_agent_id != agent.id:
        raise HTTPException(status_code=403, detail="Not hired for this job")

    if job.status != JobStatus.IN_PROGRESS:
        raise HTTPException(status_code=400, detail="Job is not in progress")

    # Submit deliverable
    job.deliverable_text = data.deliverable_text
    job.deliverable_files = data.deliverable_files
    job.status = JobStatus.PENDING_REVIEW
    job.submitted_at = datetime.utcnow()

    db.commit()

    return {"message": "Deliverable submitted for review", "job_id": job_id}


@router.get("/leaderboard", response_model=list[dict])
def agent_leaderboard(
    category: str | None = None,
    limit: int = Query(default=20, le=50),
    db: Session = Depends(get_db)
):
    """Public leaderboard of top agents."""
    query = db.query(AgentNode).filter(AgentNode.jobs_completed > 0)

    if category:
        query = query.filter(AgentNode.specializations.contains([category]))

    agents = query.order_by(AgentNode.rating.desc(), AgentNode.jobs_completed.desc()).limit(limit).all()

    return [
        {
            "name": agent.name,
            "model": agent.model,
            "rating": round(agent.rating, 2),
            "jobs_completed": agent.jobs_completed,
            "trust_level": agent.trust_level.value if agent.trust_level else "new",
            "specializations": agent.specializations or [],
            "total_earned": round(agent.total_earned, 2),
        }
        for agent in agents
    ]


def _agent_to_out(agent: AgentNode) -> AgentNodeOut:
    """Convert agent model to output schema."""
    return AgentNodeOut(
        id=agent.id,
        node_id=agent.node_id,
        name=agent.name,
        model=agent.model,
        bio=agent.bio,
        context_window=agent.context_window,
        tools=agent.tools or [],
        specializations=agent.specializations or [],
        hourly_rate=agent.hourly_rate,
        wallet_address=agent.wallet_address,
        total_earned=agent.total_earned,
        jobs_completed=agent.jobs_completed,
        rating=agent.rating,
        trust_level=agent.trust_level.value if agent.trust_level else "new",
        status=agent.status.value if agent.status else "offline",
        last_heartbeat=agent.last_heartbeat,
        created_at=agent.created_at,
    )
