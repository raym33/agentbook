"""Revisions API routes - Company requests changes, agent submits revisions."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Job, Company, AgentNode, Revision, RevisionStatus, JobStatus, Message, MessageType
from app.schemas import RevisionRequest, RevisionSubmit, RevisionOut
from app.services.auth import get_current_company

router = APIRouter(prefix="/revisions", tags=["revisions"])


def get_agent_from_key(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: Session = Depends(get_db)
) -> AgentNode:
    """Authenticate agent node by API key."""
    agent = db.query(AgentNode).filter(AgentNode.api_key == x_api_key).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return agent


# ============ Company endpoints ============

@router.post("/job/{job_id}/request", response_model=RevisionOut)
def request_revision(
    job_id: int,
    data: RevisionRequest,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db)
):
    """Company requests a revision on submitted work."""
    job = db.get(Job, job_id)
    if not job or job.company_id != company.id:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.PENDING_REVIEW:
        raise HTTPException(status_code=400, detail="Job must be pending review to request revision")

    # Count existing revisions
    existing_count = db.query(Revision).filter(Revision.job_id == job_id).count()

    # Create revision request
    revision = Revision(
        job_id=job_id,
        request_text=data.request_text,
        original_deliverable=job.deliverable_text,
        status=RevisionStatus.PENDING,
        revision_number=existing_count + 1,
    )
    db.add(revision)

    # Move job back to in_progress
    job.status = JobStatus.IN_PROGRESS

    # Add system message
    message = Message(
        job_id=job_id,
        from_company_id=company.id,
        message_type=MessageType.REVISION_REQUEST,
        content=f"Revision #{existing_count + 1} requested:\n\n{data.request_text}",
        read_by_company=True,
        read_by_agent=False,
    )
    db.add(message)

    db.commit()
    db.refresh(revision)

    return RevisionOut.model_validate(revision)


@router.get("/job/{job_id}", response_model=list[RevisionOut])
def get_job_revisions(
    job_id: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db)
):
    """Get all revisions for a job."""
    job = db.get(Job, job_id)
    if not job or job.company_id != company.id:
        raise HTTPException(status_code=404, detail="Job not found")

    revisions = db.query(Revision).filter(Revision.job_id == job_id).order_by(Revision.revision_number).all()
    return [RevisionOut.model_validate(r) for r in revisions]


# ============ Agent endpoints ============

@router.get("/job/{job_id}/pending", response_model=RevisionOut | None)
def get_pending_revision(
    job_id: int,
    agent: AgentNode = Depends(get_agent_from_key),
    db: Session = Depends(get_db)
):
    """Agent checks for pending revision requests."""
    job = db.get(Job, job_id)
    if not job or job.hired_agent_id != agent.id:
        raise HTTPException(status_code=404, detail="Job not found or not hired")

    revision = db.query(Revision).filter(
        Revision.job_id == job_id,
        Revision.status == RevisionStatus.PENDING
    ).first()

    if not revision:
        return None

    # Mark as in progress
    revision.status = RevisionStatus.IN_PROGRESS
    db.commit()

    return RevisionOut.model_validate(revision)


@router.post("/job/{job_id}/submit", response_model=RevisionOut)
def submit_revision(
    job_id: int,
    data: RevisionSubmit,
    agent: AgentNode = Depends(get_agent_from_key),
    db: Session = Depends(get_db)
):
    """Agent submits revised work."""
    job = db.get(Job, job_id)
    if not job or job.hired_agent_id != agent.id:
        raise HTTPException(status_code=404, detail="Job not found or not hired")

    # Find the in-progress revision
    revision = db.query(Revision).filter(
        Revision.job_id == job_id,
        Revision.status == RevisionStatus.IN_PROGRESS
    ).first()

    if not revision:
        raise HTTPException(status_code=400, detail="No pending revision to submit")

    # Update revision
    revision.revised_deliverable = data.revised_deliverable
    revision.status = RevisionStatus.COMPLETED
    revision.completed_at = datetime.utcnow()

    # Update job deliverable
    job.deliverable_text = data.revised_deliverable
    job.status = JobStatus.PENDING_REVIEW
    job.submitted_at = datetime.utcnow()

    # Add message
    message = Message(
        job_id=job_id,
        from_agent_id=agent.id,
        message_type=MessageType.DELIVERABLE,
        content=f"Revision #{revision.revision_number} submitted.\n\nRevised deliverable:\n{data.revised_deliverable[:500]}...",
        read_by_company=False,
        read_by_agent=True,
    )
    db.add(message)

    db.commit()
    db.refresh(revision)

    return RevisionOut.model_validate(revision)


@router.get("/agent/all", response_model=list[dict])
def get_agent_revisions(
    agent: AgentNode = Depends(get_agent_from_key),
    db: Session = Depends(get_db)
):
    """Agent gets all pending revisions across all their jobs."""
    jobs = db.query(Job).filter(Job.hired_agent_id == agent.id).all()
    job_ids = [j.id for j in jobs]

    revisions = db.query(Revision).filter(
        Revision.job_id.in_(job_ids),
        Revision.status.in_([RevisionStatus.PENDING, RevisionStatus.IN_PROGRESS])
    ).all()

    return [
        {
            "revision_id": r.id,
            "job_id": r.job_id,
            "job_title": next((j.title for j in jobs if j.id == r.job_id), "Unknown"),
            "request_text": r.request_text,
            "revision_number": r.revision_number,
            "status": r.status.value,
            "requested_at": r.requested_at.isoformat(),
        }
        for r in revisions
    ]
