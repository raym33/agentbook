"""Messages API routes - Chat between company and agent."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Header, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Job, Company, AgentNode, Message, MessageType, JobStatus
from app.schemas import MessageSend, MessageOut
from app.services.auth import get_current_company

router = APIRouter(prefix="/messages", tags=["messages"])


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

@router.post("/job/{job_id}/company", response_model=MessageOut)
def company_send_message(
    job_id: int,
    data: MessageSend,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db)
):
    """Company sends a message to the agent working on a job."""
    job = db.get(Job, job_id)
    if not job or job.company_id != company.id:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status not in [JobStatus.IN_PROGRESS, JobStatus.PENDING_REVIEW]:
        raise HTTPException(status_code=400, detail="Job must be in progress to send messages")

    if not job.hired_agent_id:
        raise HTTPException(status_code=400, detail="No agent hired for this job yet")

    # Validate message type
    try:
        msg_type = MessageType(data.message_type)
    except ValueError:
        msg_type = MessageType.TEXT

    message = Message(
        job_id=job_id,
        from_company_id=company.id,
        message_type=msg_type,
        content=data.content,
        attachments=data.attachments,
        read_by_company=True,  # Sender has read it
        read_by_agent=False,
    )
    db.add(message)
    db.commit()
    db.refresh(message)

    return _message_to_out(message, db)


@router.get("/job/{job_id}/company", response_model=list[MessageOut])
def company_get_messages(
    job_id: int,
    since: datetime | None = None,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db)
):
    """Company gets all messages for a job."""
    job = db.get(Job, job_id)
    if not job or job.company_id != company.id:
        raise HTTPException(status_code=404, detail="Job not found")

    query = db.query(Message).filter(Message.job_id == job_id)
    if since:
        query = query.filter(Message.created_at > since)

    messages = query.order_by(Message.created_at.asc()).all()

    # Mark as read by company
    for msg in messages:
        if not msg.read_by_company:
            msg.read_by_company = True
    db.commit()

    return [_message_to_out(msg, db) for msg in messages]


@router.post("/job/{job_id}/company/instruction", response_model=MessageOut)
def company_send_instruction(
    job_id: int,
    data: MessageSend,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db)
):
    """Company sends additional instructions to the agent."""
    job = db.get(Job, job_id)
    if not job or job.company_id != company.id:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status not in [JobStatus.IN_PROGRESS, JobStatus.PENDING_REVIEW]:
        raise HTTPException(status_code=400, detail="Job must be in progress")

    message = Message(
        job_id=job_id,
        from_company_id=company.id,
        message_type=MessageType.INSTRUCTION,
        content=data.content,
        attachments=data.attachments,
        read_by_company=True,
        read_by_agent=False,
    )
    db.add(message)
    db.commit()
    db.refresh(message)

    return _message_to_out(message, db)


# ============ Agent endpoints ============

@router.post("/job/{job_id}/agent", response_model=MessageOut)
def agent_send_message(
    job_id: int,
    data: MessageSend,
    agent: AgentNode = Depends(get_agent_from_key),
    db: Session = Depends(get_db)
):
    """Agent sends a message to the company."""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.hired_agent_id != agent.id:
        raise HTTPException(status_code=403, detail="Not hired for this job")

    if job.status not in [JobStatus.IN_PROGRESS, JobStatus.PENDING_REVIEW]:
        raise HTTPException(status_code=400, detail="Job must be in progress")

    try:
        msg_type = MessageType(data.message_type)
    except ValueError:
        msg_type = MessageType.TEXT

    message = Message(
        job_id=job_id,
        from_agent_id=agent.id,
        message_type=msg_type,
        content=data.content,
        attachments=data.attachments,
        read_by_company=False,
        read_by_agent=True,
    )
    db.add(message)
    db.commit()
    db.refresh(message)

    return _message_to_out(message, db)


@router.get("/job/{job_id}/agent", response_model=list[MessageOut])
def agent_get_messages(
    job_id: int,
    since: datetime | None = None,
    agent: AgentNode = Depends(get_agent_from_key),
    db: Session = Depends(get_db)
):
    """Agent gets all messages for a job."""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.hired_agent_id != agent.id:
        raise HTTPException(status_code=403, detail="Not hired for this job")

    query = db.query(Message).filter(Message.job_id == job_id)
    if since:
        query = query.filter(Message.created_at > since)

    messages = query.order_by(Message.created_at.asc()).all()

    # Mark as read by agent
    for msg in messages:
        if not msg.read_by_agent:
            msg.read_by_agent = True
    db.commit()

    return [_message_to_out(msg, db) for msg in messages]


@router.post("/job/{job_id}/agent/question", response_model=MessageOut)
def agent_ask_question(
    job_id: int,
    data: MessageSend,
    agent: AgentNode = Depends(get_agent_from_key),
    db: Session = Depends(get_db)
):
    """Agent asks a clarifying question."""
    job = db.get(Job, job_id)
    if not job or job.hired_agent_id != agent.id:
        raise HTTPException(status_code=404, detail="Job not found or not hired")

    message = Message(
        job_id=job_id,
        from_agent_id=agent.id,
        message_type=MessageType.QUESTION,
        content=data.content,
        attachments=data.attachments,
        read_by_company=False,
        read_by_agent=True,
    )
    db.add(message)
    db.commit()
    db.refresh(message)

    return _message_to_out(message, db)


@router.get("/job/{job_id}/agent/unread", response_model=list[MessageOut])
def agent_get_unread(
    job_id: int,
    agent: AgentNode = Depends(get_agent_from_key),
    db: Session = Depends(get_db)
):
    """Agent gets only unread messages (new instructions)."""
    job = db.get(Job, job_id)
    if not job or job.hired_agent_id != agent.id:
        raise HTTPException(status_code=404, detail="Job not found or not hired")

    messages = db.query(Message).filter(
        Message.job_id == job_id,
        Message.read_by_agent == False,
        Message.from_company_id != None
    ).order_by(Message.created_at.asc()).all()

    return [_message_to_out(msg, db) for msg in messages]


def _message_to_out(message: Message, db: Session) -> MessageOut:
    """Convert message model to output schema."""
    sender_name = None
    if message.from_company_id:
        company = db.get(Company, message.from_company_id)
        sender_name = company.name if company else "Company"
    elif message.from_agent_id:
        agent = db.get(AgentNode, message.from_agent_id)
        sender_name = agent.name if agent else "Agent"

    return MessageOut(
        id=message.id,
        job_id=message.job_id,
        from_company_id=message.from_company_id,
        from_agent_id=message.from_agent_id,
        message_type=message.message_type.value if message.message_type else "text",
        content=message.content,
        attachments=message.attachments or [],
        read_by_company=message.read_by_company,
        read_by_agent=message.read_by_agent,
        created_at=message.created_at,
        sender_name=sender_name,
    )
