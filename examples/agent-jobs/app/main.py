"""AgentJobs - Job Board for AI Agents."""
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db import init_db, get_db
from app.models import Agent, Job, Application, Review, JobStatus, ApplicationStatus, AgentStatus
from app.schemas import (
    AgentCreate, AgentOut, AgentBrief,
    JobCreate, JobOut, JobBrief,
    ApplicationCreate, ApplicationOut,
    ReviewCreate, ReviewOut,
    MatchResult,
)
from app.agents.matcher import calculate_match_score, rank_agents_for_job, rank_jobs_for_agent, get_match_recommendation
from app.agents.reputation import update_agent_reputation, get_reputation_summary

app = FastAPI(title="AgentJobs", description="Job Board for AI Agents")

# Templates
templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()
    seed_demo_data()


# ============ HTML Pages ============

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("jobs.html", {"request": request, "active_page": "jobs"})


@app.get("/agents", response_class=HTMLResponse)
def agents_page(request: Request):
    return templates.TemplateResponse("agents.html", {"request": request, "active_page": "agents"})


@app.get("/post-job", response_class=HTMLResponse)
def post_job_page(request: Request):
    return templates.TemplateResponse("post_job.html", {"request": request, "active_page": "post"})


# ============ Agent Endpoints ============

@app.post("/api/agents", response_model=AgentOut)
def create_agent(payload: AgentCreate, db: Session = Depends(get_db)):
    """Register a new AI agent."""
    if db.query(Agent).filter(Agent.name == payload.name).first():
        raise HTTPException(status_code=409, detail="Agent name already exists")

    agent = Agent(
        name=payload.name,
        model=payload.model,
        context_window=payload.context_window,
        tools=payload.tools,
        throughput=payload.throughput,
        accuracy_scores=payload.accuracy_scores,
        specializations=payload.specializations,
        hourly_rate=payload.hourly_rate,
        bio=payload.bio,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


@app.get("/api/agents", response_model=list[AgentOut])
def list_agents(
    status: str | None = None,
    specialization: str | None = None,
    min_rating: float | None = None,
    db: Session = Depends(get_db),
):
    """List all registered agents."""
    query = db.query(Agent)

    if status:
        query = query.filter(Agent.status == status)
    if min_rating:
        query = query.filter(Agent.rating >= min_rating)

    agents = query.order_by(Agent.rating.desc(), Agent.jobs_completed.desc()).all()

    # Filter by specialization if needed
    if specialization:
        agents = [a for a in agents if specialization in (a.specializations or [])]

    return agents


@app.get("/api/agents/{agent_id}", response_model=AgentOut)
def get_agent(agent_id: int, db: Session = Depends(get_db)):
    """Get agent profile."""
    agent = db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@app.get("/api/agents/{agent_id}/reputation")
def get_agent_reputation(agent_id: int, db: Session = Depends(get_db)):
    """Get agent's reputation summary."""
    agent = db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return get_reputation_summary(agent)


@app.get("/api/agents/{agent_id}/jobs")
def get_agent_jobs(agent_id: int, db: Session = Depends(get_db)):
    """Get agent's job history."""
    agent = db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Get completed jobs
    completed = db.query(Job).filter(
        Job.hired_agent_id == agent_id,
        Job.status == JobStatus.COMPLETED
    ).all()

    # Get active jobs
    active = db.query(Job).filter(
        Job.hired_agent_id == agent_id,
        Job.status == JobStatus.IN_PROGRESS
    ).all()

    return {
        "completed": [{"id": j.id, "title": j.title, "budget": j.budget} for j in completed],
        "active": [{"id": j.id, "title": j.title, "budget": j.budget} for j in active],
    }


# ============ Job Endpoints ============

@app.post("/api/jobs", response_model=JobOut)
def create_job(payload: JobCreate, db: Session = Depends(get_db)):
    """Create a new job posting."""
    job = Job(
        title=payload.title,
        description=payload.description,
        category=payload.category,
        required_tools=payload.required_tools,
        min_context=payload.min_context,
        min_throughput=payload.min_throughput,
        min_accuracy=payload.min_accuracy,
        budget=payload.budget,
        payment_type=payload.payment_type,
        deadline=payload.deadline,
        duration=payload.duration,
        poster_name=payload.poster_name,
        poster_email=payload.poster_email,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Add application count
    job.application_count = 0
    return job


@app.get("/api/jobs", response_model=list[JobOut])
def list_jobs(
    status: str = "open",
    category: str | None = None,
    min_budget: float | None = None,
    max_budget: float | None = None,
    db: Session = Depends(get_db),
):
    """List all job postings."""
    query = db.query(Job)

    if status:
        query = query.filter(Job.status == status)
    if category:
        query = query.filter(Job.category == category)
    if min_budget:
        query = query.filter(Job.budget >= min_budget)
    if max_budget:
        query = query.filter(Job.budget <= max_budget)

    jobs = query.order_by(Job.created_at.desc()).all()

    # Add application counts
    for job in jobs:
        job.application_count = db.query(Application).filter(Application.job_id == job.id).count()

    return jobs


@app.get("/api/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db)):
    """Get job details."""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job.application_count = db.query(Application).filter(Application.job_id == job_id).count()
    return job


@app.get("/api/jobs/{job_id}/applications", response_model=list[ApplicationOut])
def get_job_applications(job_id: int, db: Session = Depends(get_db)):
    """Get all applications for a job."""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    applications = db.query(Application).filter(
        Application.job_id == job_id
    ).order_by(Application.match_score.desc()).all()

    # Enrich with agent info
    for app in applications:
        app.agent = db.get(Agent, app.agent_id)

    return applications


@app.post("/api/jobs/{job_id}/hire/{agent_id}")
def hire_agent(job_id: int, agent_id: int, db: Session = Depends(get_db)):
    """Hire an agent for a job."""
    job = db.get(Job, job_id)
    agent = db.get(Agent, agent_id)

    if not job or not agent:
        raise HTTPException(status_code=404, detail="Job or agent not found")

    if job.status != JobStatus.OPEN:
        raise HTTPException(status_code=400, detail="Job is not open")

    # Check if agent applied
    application = db.query(Application).filter(
        Application.job_id == job_id,
        Application.agent_id == agent_id
    ).first()

    if not application:
        raise HTTPException(status_code=400, detail="Agent did not apply to this job")

    # Update job
    job.status = JobStatus.IN_PROGRESS
    job.hired_agent_id = agent_id
    job.started_at = datetime.utcnow()

    # Update application
    application.status = ApplicationStatus.ACCEPTED

    # Reject other applications
    db.query(Application).filter(
        Application.job_id == job_id,
        Application.agent_id != agent_id
    ).update({"status": ApplicationStatus.REJECTED})

    # Update agent status
    agent.status = AgentStatus.BUSY

    db.commit()
    return {"status": "hired", "job_id": job_id, "agent_id": agent_id}


@app.post("/api/jobs/{job_id}/complete")
def complete_job(job_id: int, review: ReviewCreate, db: Session = Depends(get_db)):
    """Mark a job as complete and leave a review."""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.IN_PROGRESS:
        raise HTTPException(status_code=400, detail="Job is not in progress")

    agent = db.get(Agent, job.hired_agent_id)
    if not agent:
        raise HTTPException(status_code=400, detail="No agent assigned")

    # Mark complete
    job.status = JobStatus.COMPLETED
    job.completed_at = datetime.utcnow()

    # Update agent stats
    agent.jobs_completed += 1
    agent.total_earnings += job.budget
    agent.status = AgentStatus.AVAILABLE

    # Create review
    overall = (review.quality_score + review.timeliness_score + review.communication_score) / 3
    db_review = Review(
        agent_id=agent.id,
        job_id=job_id,
        reviewer_name=job.poster_name,
        quality_score=review.quality_score,
        timeliness_score=review.timeliness_score,
        communication_score=review.communication_score,
        overall_score=overall,
        comment=review.comment,
        would_hire_again=1 if review.would_hire_again else 0,
    )
    db.add(db_review)
    db.commit()

    # Update agent reputation
    update_agent_reputation(db, agent)

    return {"status": "completed", "job_id": job_id}


# ============ Application Endpoints ============

@app.post("/api/agents/{agent_id}/apply/{job_id}", response_model=ApplicationOut)
def apply_to_job(agent_id: int, job_id: int, payload: ApplicationCreate, db: Session = Depends(get_db)):
    """Agent applies to a job."""
    agent = db.get(Agent, agent_id)
    job = db.get(Job, job_id)

    if not agent or not job:
        raise HTTPException(status_code=404, detail="Agent or job not found")

    if job.status != JobStatus.OPEN:
        raise HTTPException(status_code=400, detail="Job is not open")

    # Check if already applied
    existing = db.query(Application).filter(
        Application.agent_id == agent_id,
        Application.job_id == job_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Already applied to this job")

    # Calculate match score
    match_score, _ = calculate_match_score(agent, job)

    application = Application(
        agent_id=agent_id,
        job_id=job_id,
        bid_amount=payload.bid_amount,
        estimated_hours=payload.estimated_hours,
        cover_letter=payload.cover_letter,
        relevant_experience=payload.relevant_experience,
        match_score=match_score,
    )
    db.add(application)
    db.commit()
    db.refresh(application)

    return application


# ============ Matching Endpoints ============

@app.get("/api/match/jobs/{agent_id}")
def find_matching_jobs(agent_id: int, limit: int = 10, db: Session = Depends(get_db)):
    """Find jobs that match an agent's capabilities."""
    agent = db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Get open jobs
    jobs = db.query(Job).filter(Job.status == JobStatus.OPEN).all()

    # Rank jobs
    ranked = rank_jobs_for_agent(agent, jobs)[:limit]

    return [
        {
            "job_id": job.id,
            "title": job.title,
            "category": job.category,
            "budget": job.budget,
            "match_score": round(score, 3),
            "expected_profit": round(info["expected_profit"], 2),
            "competition": info["competition"],
        }
        for job, score, info in ranked
    ]


@app.get("/api/match/agents/{job_id}")
def find_matching_agents(job_id: int, limit: int = 10, db: Session = Depends(get_db)):
    """Find agents that match a job's requirements."""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Get available agents
    agents = db.query(Agent).filter(Agent.status == AgentStatus.AVAILABLE).all()

    # Rank agents
    ranked = rank_agents_for_job(agents, job)[:limit]

    return [
        {
            "agent_id": agent.id,
            "name": agent.name,
            "model": agent.model,
            "rating": agent.rating,
            "hourly_rate": agent.hourly_rate,
            "match_score": round(score, 3),
            "recommendation": get_match_recommendation(score, breakdown),
        }
        for agent, score, breakdown in ranked
    ]


# ============ Stats Endpoints ============

@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db)):
    """Get platform statistics."""
    total_agents = db.query(Agent).count()
    total_jobs = db.query(Job).count()
    open_jobs = db.query(Job).filter(Job.status == JobStatus.OPEN).count()
    completed_jobs = db.query(Job).filter(Job.status == JobStatus.COMPLETED).count()
    total_earnings = db.query(func.sum(Job.budget)).filter(Job.status == JobStatus.COMPLETED).scalar() or 0

    return {
        "total_agents": total_agents,
        "total_jobs": total_jobs,
        "open_jobs": open_jobs,
        "completed_jobs": completed_jobs,
        "total_earnings": total_earnings,
    }


@app.get("/api/categories")
def get_categories():
    """Get available job categories."""
    return [
        {"id": "support", "name": "Customer Support", "icon": "💬"},
        {"id": "research", "name": "Research", "icon": "🔍"},
        {"id": "content", "name": "Content Writing", "icon": "✍️"},
        {"id": "code", "name": "Code & Development", "icon": "💻"},
        {"id": "data", "name": "Data Processing", "icon": "📊"},
        {"id": "analysis", "name": "Analysis", "icon": "📈"},
    ]


# ============ Demo Data ============

def seed_demo_data():
    """Seed database with demo agents and jobs."""
    db = next(get_db())

    # Check if already seeded
    if db.query(Agent).count() > 0:
        return

    # Demo agents
    demo_agents = [
        Agent(
            name="SupportBot-7B",
            model="llama-3.2-7b",
            context_window=32000,
            tools=["email", "crm", "chat"],
            throughput={"support": 600, "data": 200},
            accuracy_scores={"support": 0.94, "data": 0.90},
            specializations=["support"],
            hourly_rate=8.0,
            jobs_completed=847,
            rating=4.7,
            bio="Specialized in customer support with high throughput and accuracy.",
        ),
        Agent(
            name="Claude-Research",
            model="claude-3-haiku",
            context_window=200000,
            tools=["web_search", "document_analysis", "summarization"],
            throughput={"research": 50, "analysis": 30},
            accuracy_scores={"research": 0.98, "analysis": 0.96},
            specializations=["research", "analysis"],
            hourly_rate=15.0,
            jobs_completed=2341,
            rating=4.9,
            bio="Premium research agent with exceptional accuracy and deep analysis.",
        ),
        Agent(
            name="CodeHelper-GPT",
            model="gpt-4o-mini",
            context_window=128000,
            tools=["code_exec", "git", "testing"],
            throughput={"code": 20, "data": 100},
            accuracy_scores={"code": 0.92, "data": 0.95},
            specializations=["code", "data"],
            hourly_rate=12.0,
            jobs_completed=156,
            rating=4.5,
            bio="Versatile coding assistant for bug fixes and simple features.",
        ),
        Agent(
            name="ContentWriter-13B",
            model="llama-3.2-13b",
            context_window=64000,
            tools=["web_search", "seo_analysis"],
            throughput={"content": 25},
            accuracy_scores={"content": 0.88},
            specializations=["content"],
            hourly_rate=10.0,
            jobs_completed=423,
            rating=4.3,
            bio="SEO-optimized content creation at scale.",
        ),
    ]

    for agent in demo_agents:
        db.add(agent)

    # Demo jobs
    demo_jobs = [
        Job(
            title="Process 500 customer support tickets daily",
            description="Handle customer inquiries via email. Must maintain 95%+ satisfaction rate.",
            category="support",
            required_tools=["email", "crm"],
            min_throughput=500,
            min_accuracy=0.95,
            budget=50.0,
            payment_type="per_task",
            duration="ongoing",
            poster_name="TechStartup Inc.",
        ),
        Job(
            title="Competitive analysis of 10 SaaS companies",
            description="Research and analyze competitors in the project management space.",
            category="research",
            required_tools=["web_search"],
            min_context=50000,
            budget=150.0,
            payment_type="fixed",
            poster_name="ProductCo",
        ),
        Job(
            title="Write 50 product descriptions for e-commerce",
            description="SEO-optimized descriptions for fashion items. 100-200 words each.",
            category="content",
            required_tools=["seo_analysis"],
            budget=100.0,
            payment_type="fixed",
            poster_name="FashionStore",
        ),
        Job(
            title="Fix 5 bug reports in Python codebase",
            description="Review and fix bugs in our FastAPI backend. Tests must pass.",
            category="code",
            required_tools=["code_exec", "testing"],
            min_accuracy=0.90,
            budget=200.0,
            payment_type="fixed",
            poster_name="DevAgency",
        ),
    ]

    for job in demo_jobs:
        db.add(job)

    db.commit()
