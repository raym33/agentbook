"""Jobs API routes."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db import get_db
from app.models import Job, Company, Application, AgentNode, Review, JobStatus, PaymentStatus, ApplicationStatus, TrustLevel
from app.schemas import JobCreate, JobOut, JobWithCompany, ApplicationOut, DeliverableReview
from app.services.auth import get_current_company
from app.services.escrow import EscrowService
from app.services.matching import calculate_match_score

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/", response_model=JobOut)
def create_job(
    data: JobCreate,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db)
):
    """Create a new job posting."""
    # Validate trust level
    try:
        trust_level = TrustLevel(data.min_trust_level)
    except ValueError:
        trust_level = TrustLevel.NEW

    job = Job(
        company_id=company.id,
        title=data.title,
        description=data.description,
        category=data.category,
        deliverables=data.deliverables,
        required_tools=data.required_tools,
        min_context=data.min_context,
        min_accuracy=data.min_accuracy,
        min_trust_level=trust_level,
        budget=data.budget,
        deadline=data.deadline,
        status=JobStatus.DRAFT,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Update company stats
    company.jobs_posted += 1
    db.commit()

    return _job_to_out(job, db)


@router.post("/{job_id}/publish", response_model=JobOut)
def publish_job(
    job_id: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db)
):
    """Publish a job and escrow the budget."""
    job = db.get(Job, job_id)
    if not job or job.company_id != company.id:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.DRAFT:
        raise HTTPException(status_code=400, detail="Job is not in draft status")

    # Check balance
    if company.balance < job.budget:
        raise HTTPException(status_code=400, detail="Insufficient balance")

    # Escrow funds
    escrow = EscrowService(db)
    escrow.deposit_to_escrow(job, company)

    # Publish
    job.status = JobStatus.OPEN
    job.published_at = datetime.utcnow()
    db.commit()

    return _job_to_out(job, db)


@router.get("/", response_model=list[JobWithCompany])
def list_jobs(
    status: str | None = None,
    category: str | None = None,
    min_budget: float | None = None,
    max_budget: float | None = None,
    limit: int = Query(default=50, le=100),
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """List available jobs (public endpoint)."""
    query = db.query(Job).filter(Job.status == JobStatus.OPEN)

    if category:
        query = query.filter(Job.category == category)
    if min_budget:
        query = query.filter(Job.budget >= min_budget)
    if max_budget:
        query = query.filter(Job.budget <= max_budget)

    jobs = query.order_by(Job.created_at.desc()).offset(offset).limit(limit).all()

    result = []
    for job in jobs:
        out = _job_to_out(job, db)
        company = db.get(Company, job.company_id)
        result.append(JobWithCompany(
            **out.model_dump(),
            company_name=company.name if company else "Unknown"
        ))

    return result


@router.get("/my", response_model=list[JobOut])
def my_jobs(
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db)
):
    """Get all jobs posted by current company."""
    jobs = db.query(Job).filter(Job.company_id == company.id).order_by(Job.created_at.desc()).all()
    return [_job_to_out(job, db) for job in jobs]


@router.get("/{job_id}", response_model=JobWithCompany)
def get_job(job_id: int, db: Session = Depends(get_db)):
    """Get a specific job."""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    out = _job_to_out(job, db)
    company = db.get(Company, job.company_id)
    return JobWithCompany(
        **out.model_dump(),
        company_name=company.name if company else "Unknown"
    )


@router.get("/{job_id}/applications", response_model=list[ApplicationOut])
def get_applications(
    job_id: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db)
):
    """Get all applications for a job (company only)."""
    job = db.get(Job, job_id)
    if not job or job.company_id != company.id:
        raise HTTPException(status_code=404, detail="Job not found")

    applications = db.query(Application).filter(Application.job_id == job_id).order_by(Application.match_score.desc()).all()

    result = []
    for app in applications:
        agent = db.get(AgentNode, app.agent_id)
        out = ApplicationOut.model_validate(app)
        if agent:
            out.agent = agent
        result.append(out)

    return result


@router.post("/{job_id}/hire/{application_id}")
def hire_agent(
    job_id: int,
    application_id: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db)
):
    """Hire an agent from their application."""
    job = db.get(Job, job_id)
    if not job or job.company_id != company.id:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.OPEN:
        raise HTTPException(status_code=400, detail="Job is not open for hiring")

    application = db.get(Application, application_id)
    if not application or application.job_id != job_id:
        raise HTTPException(status_code=404, detail="Application not found")

    # Accept application
    application.status = ApplicationStatus.ACCEPTED

    # Reject others
    db.query(Application).filter(
        Application.job_id == job_id,
        Application.id != application_id
    ).update({"status": ApplicationStatus.REJECTED})

    # Update job
    job.status = JobStatus.IN_PROGRESS
    job.hired_agent_id = application.agent_id
    job.started_at = datetime.utcnow()

    db.commit()

    return {"message": "Agent hired successfully", "agent_id": application.agent_id}


@router.post("/{job_id}/review")
def review_deliverable(
    job_id: int,
    review_data: DeliverableReview,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db)
):
    """Review and approve/reject the agent's deliverable."""
    job = db.get(Job, job_id)
    if not job or job.company_id != company.id:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.PENDING_REVIEW:
        raise HTTPException(status_code=400, detail="Job is not pending review")

    agent = db.get(AgentNode, job.hired_agent_id)
    if not agent:
        raise HTTPException(status_code=400, detail="Hired agent not found")

    if review_data.approved:
        # Complete job
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.utcnow()

        # Release payment
        escrow = EscrowService(db)
        escrow.release_to_agent(job, agent)

        # Update stats
        company.jobs_completed += 1
        agent.jobs_completed += 1

        # Create review
        overall = (review_data.quality_score + review_data.timeliness_score + review_data.communication_score) / 3
        review = Review(
            agent_id=agent.id,
            job_id=job_id,
            company_id=company.id,
            quality_score=review_data.quality_score,
            timeliness_score=review_data.timeliness_score,
            communication_score=review_data.communication_score,
            overall_score=overall,
            comment=review_data.feedback,
        )
        db.add(review)

        # Update agent rating
        reviews = db.query(Review).filter(Review.agent_id == agent.id).all()
        if reviews:
            agent.rating = sum(r.overall_score for r in reviews) / len(reviews)

        # Update trust level
        if agent.jobs_completed >= 50 and agent.rating >= 4.5:
            agent.trust_level = TrustLevel.ELITE
        elif agent.jobs_completed >= 20 and agent.rating >= 4.0:
            agent.trust_level = TrustLevel.TRUSTED
        elif agent.jobs_completed >= 5 and agent.rating >= 3.5:
            agent.trust_level = TrustLevel.VERIFIED

        db.commit()
        return {"message": "Job completed and payment released", "payment": job.budget}
    else:
        # Request revision or dispute
        job.status = JobStatus.IN_PROGRESS  # Back to in progress for revision
        db.commit()
        return {"message": "Revision requested", "feedback": review_data.feedback}


def _job_to_out(job: Job, db: Session) -> JobOut:
    """Convert job model to output schema."""
    app_count = db.query(func.count(Application.id)).filter(Application.job_id == job.id).scalar() or 0

    return JobOut(
        id=job.id,
        company_id=job.company_id,
        title=job.title,
        description=job.description,
        category=job.category,
        deliverables=job.deliverables,
        required_tools=job.required_tools or [],
        min_context=job.min_context,
        min_accuracy=job.min_accuracy,
        min_trust_level=job.min_trust_level.value if job.min_trust_level else "new",
        budget=job.budget,
        payment_status=job.payment_status.value if job.payment_status else "pending",
        status=job.status.value if job.status else "draft",
        hired_agent_id=job.hired_agent_id,
        application_count=app_count,
        created_at=job.created_at,
        deadline=job.deadline,
    )
