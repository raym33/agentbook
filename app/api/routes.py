import json
from datetime import datetime, timezone
import math

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Agent, AgentPersona, Group, Post, Comment, Vote
from app.schemas import (
    AgentCreate,
    AgentOut,
    GroupCreate,
    GroupOut,
    PostCreate,
    PostOut,
    CommentCreate,
    CommentOut,
    VoteCreate,
    PersonaCreate,
    PersonaOut,
)

router = APIRouter()


# ============ System & Dashboard Endpoints ============


@router.get("/system/health")
def system_health():
    """Get system health status including LLM backends."""
    from app.services.llm_client import llm_client

    return {
        "backends": llm_client.get_backends_status(),
        "rate_limit": {
            "requests_remaining": llm_client.rate_limiter.remaining(),
            "limit_per_minute": llm_client.rate_limiter.requests_per_minute,
        },
    }


@router.get("/agents/status")
def get_agents_status():
    """Get real-time status of all agents."""
    from app.agents.runner import agent_runner

    return agent_runner.get_status()


# ============ Persona Endpoints ============


@router.get("/personas", response_model=list[PersonaOut])
def list_personas(db: Session = Depends(get_db)):
    """List all personas."""
    return db.query(AgentPersona).order_by(AgentPersona.created_at.desc()).all()


@router.post("/personas", response_model=PersonaOut)
def create_persona(payload: PersonaCreate, db: Session = Depends(get_db)):
    """Create a new persona."""
    if db.query(AgentPersona).filter(AgentPersona.name == payload.name).first():
        raise HTTPException(status_code=409, detail="Persona name already exists")

    persona = AgentPersona(
        name=payload.name,
        display_name=payload.display_name,
        description=payload.description,
        personality_traits=json.dumps(payload.personality_traits),
        communication_style=payload.communication_style,
        expertise_areas=json.dumps(payload.expertise_areas),
        activity_level=payload.activity_level,
        response_tendency=payload.response_tendency,
        post_tendency=payload.post_tendency,
        base_system_prompt=payload.base_system_prompt,
        example_messages=json.dumps(payload.example_messages) if payload.example_messages else None,
    )
    db.add(persona)
    db.commit()
    db.refresh(persona)
    return persona


@router.get("/personas/{persona_id}", response_model=PersonaOut)
def get_persona(persona_id: int, db: Session = Depends(get_db)):
    """Get a specific persona."""
    persona = db.get(AgentPersona, persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    return persona


@router.delete("/personas/{persona_id}")
def delete_persona(persona_id: int, db: Session = Depends(get_db)):
    """Delete a persona."""
    persona = db.get(AgentPersona, persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    # Check if any agents use this persona
    agents_using = db.query(Agent).filter(Agent.persona_id == persona_id).count()
    if agents_using > 0:
        raise HTTPException(status_code=400, detail=f"Cannot delete: {agents_using} agents use this persona")

    db.delete(persona)
    db.commit()
    return {"status": "deleted"}


@router.put("/agents/{agent_id}/persona")
def assign_persona(agent_id: int, persona_id: int, db: Session = Depends(get_db)):
    """Assign a persona to an agent."""
    agent = db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    persona = db.get(AgentPersona, persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    agent.persona_id = persona_id
    agent.system_prompt = persona.base_system_prompt
    db.commit()

    return {"status": "updated", "agent_id": agent_id, "persona_id": persona_id}


# ============ Agent Endpoints ============


@router.post("/agents", response_model=AgentOut)
def create_agent(payload: AgentCreate, db: Session = Depends(get_db)):
    if db.query(Agent).filter(Agent.name == payload.name).first():
        raise HTTPException(status_code=409, detail="Agent name already exists")
    agent = Agent(
        name=payload.name,
        persona=payload.persona,
        bio=payload.bio,
        system_prompt=f"You are {payload.name}, a {payload.persona} agent.",
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


@router.get("/agents", response_model=list[AgentOut])
def list_agents(db: Session = Depends(get_db)):
    return db.query(Agent).order_by(Agent.created_at.desc()).all()


@router.post("/groups", response_model=GroupOut)
def create_group(payload: GroupCreate, db: Session = Depends(get_db)):
    if db.query(Group).filter(Group.name == payload.name).first():
        raise HTTPException(status_code=409, detail="Group name already exists")
    creator = db.get(Agent, payload.created_by_id)
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")
    group = Group(
        name=payload.name,
        topic=payload.topic,
        description=payload.description,
        created_by_id=payload.created_by_id,
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


@router.get("/groups", response_model=list[GroupOut])
def list_groups(db: Session = Depends(get_db)):
    return db.query(Group).order_by(Group.created_at.desc()).all()


@router.post("/posts", response_model=PostOut)
def create_post(payload: PostCreate, db: Session = Depends(get_db)):
    author = db.get(Agent, payload.author_id)
    group = db.get(Group, payload.group_id)
    if not author or not group:
        raise HTTPException(status_code=404, detail="Author or group not found")
    post = Post(
        title=payload.title,
        content=payload.content,
        author_id=payload.author_id,
        group_id=payload.group_id,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


@router.get("/posts", response_model=list[PostOut])
def list_posts(
    sort: str = Query("new", pattern="^(new|top|hot|discussed)$"),
    db: Session = Depends(get_db),
):
    comment_counts = (
        db.query(Comment.post_id, func.count(Comment.id).label("comment_count"))
        .group_by(Comment.post_id)
        .subquery()
    )
    query = (
        db.query(Post, func.coalesce(comment_counts.c.comment_count, 0).label("comment_count"))
        .outerjoin(comment_counts, Post.id == comment_counts.c.post_id)
    )
    if sort == "top":
        rows = query.order_by(Post.score.desc(), Post.created_at.desc()).all()
        return [row[0] for row in rows]
    if sort == "discussed":
        rows = query.order_by(desc("comment_count"), Post.created_at.desc()).all()
        return [row[0] for row in rows]
    if sort == "hot":
        rows = query.order_by(Post.created_at.desc()).all()
        now = datetime.now(timezone.utc)
        scored = []
        for post, _count in rows:
            score = post.score
            order = math.log10(max(abs(score), 1))
            sign = 1 if score > 0 else -1 if score < 0 else 0
            seconds = (now - post.created_at.replace(tzinfo=timezone.utc)).total_seconds()
            hot = sign * order + seconds / 45000
            scored.append((hot, post))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [post for _hot, post in scored]
    rows = query.order_by(Post.created_at.desc()).all()
    return [row[0] for row in rows]


@router.post("/comments", response_model=CommentOut)
def create_comment(payload: CommentCreate, db: Session = Depends(get_db)):
    author = db.get(Agent, payload.author_id)
    post = db.get(Post, payload.post_id)
    if not author or not post:
        raise HTTPException(status_code=404, detail="Author or post not found")
    parent = None
    if payload.parent_comment_id is not None:
        parent = db.get(Comment, payload.parent_comment_id)
        if not parent or parent.post_id != payload.post_id:
            raise HTTPException(status_code=400, detail="Invalid parent comment")
    comment = Comment(
        content=payload.content,
        author_id=payload.author_id,
        post_id=payload.post_id,
        parent_comment_id=payload.parent_comment_id,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@router.get("/comments", response_model=list[CommentOut])
def list_comments(
    post_id: int | None = None,
    parent_comment_id: int | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(Comment)
    if post_id is not None:
        query = query.filter(Comment.post_id == post_id)
    if parent_comment_id is not None:
        query = query.filter(Comment.parent_comment_id == parent_comment_id)
    return query.order_by(Comment.created_at.asc()).all()


@router.post("/posts/{post_id}/vote", response_model=PostOut)
def vote_post(post_id: int, payload: VoteCreate, db: Session = Depends(get_db)):
    if payload.value not in (-1, 1):
        raise HTTPException(status_code=400, detail="Vote value must be -1 or 1")
    voter = db.get(Agent, payload.voter_id)
    post = db.get(Post, post_id)
    if not voter or not post:
        raise HTTPException(status_code=404, detail="Voter or post not found")
    existing = (
        db.query(Vote)
        .filter(Vote.voter_id == payload.voter_id, Vote.post_id == post_id)
        .first()
    )
    if existing:
        delta = payload.value - existing.value
        existing.value = payload.value
    else:
        delta = payload.value
        existing = Vote(value=payload.value, voter_id=payload.voter_id, post_id=post_id)
        db.add(existing)
    post.score += delta
    db.commit()
    db.refresh(post)
    return post


@router.post("/comments/{comment_id}/vote", response_model=CommentOut)
def vote_comment(comment_id: int, payload: VoteCreate, db: Session = Depends(get_db)):
    if payload.value not in (-1, 1):
        raise HTTPException(status_code=400, detail="Vote value must be -1 or 1")
    voter = db.get(Agent, payload.voter_id)
    comment = db.get(Comment, comment_id)
    if not voter or not comment:
        raise HTTPException(status_code=404, detail="Voter or comment not found")
    existing = (
        db.query(Vote)
        .filter(Vote.voter_id == payload.voter_id, Vote.comment_id == comment_id)
        .first()
    )
    if existing:
        delta = payload.value - existing.value
        existing.value = payload.value
    else:
        delta = payload.value
        existing = Vote(value=payload.value, voter_id=payload.voter_id, comment_id=comment_id)
        db.add(existing)
    comment.score += delta
    db.commit()
    db.refresh(comment)
    return comment
