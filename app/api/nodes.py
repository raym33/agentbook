"""
API endpoints for contributor node management.

This module handles:
- Node registration and authentication
- Heartbeat mechanism to track active nodes
- Task distribution to nodes
- Node statistics and monitoring
"""

import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Agent, ContributorNode, Post, Comment, Group
from app.schemas import (
    NodeRegister,
    NodeRegisterResponse,
    NodeHeartbeat,
    NodeHeartbeatResponse,
    NodeTaskResponse,
    NodeOut,
    NodeStats,
)

router = APIRouter(prefix="/nodes", tags=["nodes"])

# In-memory storage for API keys (in production, use secure storage)
# Maps node_id -> hashed_api_key
_node_api_keys: dict[str, str] = {}

# Pending tasks queue (in production, use Redis or similar)
_pending_tasks: dict[str, dict] = {}


def _hash_key(key: str) -> str:
    """Hash an API key for storage."""
    return hashlib.sha256(key.encode()).hexdigest()


def _verify_node(node_id: str, api_key: str, db: Session) -> ContributorNode:
    """Verify node credentials and return the node."""
    node = db.query(ContributorNode).filter(ContributorNode.node_id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    # Check API key
    stored_hash = _node_api_keys.get(node_id)
    if not stored_hash or stored_hash != _hash_key(api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")

    if node.status == "banned":
        raise HTTPException(status_code=403, detail="Node is banned")

    return node


@router.post("/register", response_model=NodeRegisterResponse)
def register_node(payload: NodeRegister, db: Session = Depends(get_db)):
    """
    Register a new contributor node.

    Returns a node_id and api_key that must be used for all subsequent requests.
    """
    # Generate unique node ID and API key
    node_id = secrets.token_hex(16)
    api_key = secrets.token_urlsafe(32)

    # Create node
    node = ContributorNode(
        node_id=node_id,
        name=payload.name,
        description=payload.description,
        llm_backend=payload.llm_backend,
        model_name=payload.model_name,
        callback_url=payload.callback_url,
        status="pending",  # Needs manual approval or auto-approve
    )

    db.add(node)
    db.commit()
    db.refresh(node)

    # Store hashed API key
    _node_api_keys[node_id] = _hash_key(api_key)

    # Auto-activate for now (in production, require verification)
    node.status = "active"
    node.is_verified = True
    db.commit()

    return NodeRegisterResponse(
        node_id=node_id,
        api_key=api_key,
        status="active",
        message="Node registered successfully. Save your API key - it cannot be recovered!",
    )


@router.post("/heartbeat", response_model=NodeHeartbeatResponse)
def node_heartbeat(payload: NodeHeartbeat, db: Session = Depends(get_db)):
    """
    Send a heartbeat to keep the node active and optionally receive a task.

    Should be called every 30 seconds to maintain active status.
    """
    node = _verify_node(payload.node_id, payload.api_key, db)

    # Update heartbeat
    node.last_heartbeat = datetime.utcnow()
    node.status = payload.status if payload.status in ("active", "busy", "paused") else "active"
    db.commit()

    # Check for pending tasks if node is active
    task = None
    has_task = False

    if payload.status == "active" and payload.current_load < 0.8:
        # Look for a task for this node
        task_id = f"{node.node_id}:{datetime.utcnow().timestamp()}"
        task = _pending_tasks.pop(node.node_id, None)
        if task:
            has_task = True

    return NodeHeartbeatResponse(
        status="ok",
        has_task=has_task,
        task=task,
    )


@router.post("/task/complete")
def complete_task(payload: NodeTaskResponse, db: Session = Depends(get_db)):
    """
    Report task completion with results.
    """
    node = _verify_node(payload.node_id, payload.api_key, db)

    if not payload.success:
        # Log the error but don't penalize for now
        return {"status": "error_logged", "task_id": payload.task_id}

    # Update node stats
    node.total_tokens_used += payload.tokens_used
    node.last_contribution = datetime.utcnow()

    # Process the result based on task type
    result = payload.result or {}
    task_type = result.get("task_type", "")

    if task_type == "generate_post" and "title" in result and "content" in result:
        # Create the post
        post = Post(
            title=result["title"],
            content=result["content"],
            author_id=result["agent_id"],
            group_id=result["group_id"],
        )
        db.add(post)
        node.total_posts += 1

        # Update agent stats
        agent = db.get(Agent, result["agent_id"])
        if agent:
            agent.posts_created += 1

    elif task_type == "generate_comment" and "content" in result:
        # Create the comment
        comment = Comment(
            content=result["content"],
            author_id=result["agent_id"],
            post_id=result["post_id"],
            parent_comment_id=result.get("parent_comment_id"),
        )
        db.add(comment)
        node.total_comments += 1

        # Update agent stats
        agent = db.get(Agent, result["agent_id"])
        if agent:
            agent.comments_created += 1

    db.commit()

    return {"status": "completed", "task_id": payload.task_id}


@router.get("/", response_model=list[NodeOut])
def list_nodes(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """List all registered nodes (public info only)."""
    query = db.query(ContributorNode)
    if status:
        query = query.filter(ContributorNode.status == status)
    return query.order_by(ContributorNode.created_at.desc()).all()


@router.get("/stats", response_model=NodeStats)
def get_network_stats(db: Session = Depends(get_db)):
    """Get overall network statistics."""
    # Count nodes
    total_nodes = db.query(ContributorNode).count()

    # Active nodes (heartbeat in last 5 minutes)
    five_min_ago = datetime.utcnow() - timedelta(minutes=5)
    active_nodes = db.query(ContributorNode).filter(
        ContributorNode.last_heartbeat >= five_min_ago,
        ContributorNode.status == "active",
    ).count()

    # Content stats
    total_agents = db.query(Agent).count()
    total_posts = db.query(Post).count()
    total_comments = db.query(Comment).count()

    # Models in use
    models = db.query(ContributorNode.model_name).distinct().all()
    models_in_use = [m[0] for m in models]

    return NodeStats(
        total_nodes=total_nodes,
        active_nodes=active_nodes,
        total_agents=total_agents,
        total_posts=total_posts,
        total_comments=total_comments,
        models_in_use=models_in_use,
    )


@router.post("/{node_id}/agents", response_model=dict)
def create_node_agent(
    node_id: str,
    name: str,
    persona: str = "member",
    bio: str | None = None,
    x_api_key: str = Header(...),
    db: Session = Depends(get_db),
):
    """
    Create an agent that belongs to this node.

    The agent will be controlled by the node's LLM.
    """
    node = _verify_node(node_id, x_api_key, db)

    # Check if agent name exists
    if db.query(Agent).filter(Agent.name == name).first():
        raise HTTPException(status_code=409, detail="Agent name already exists")

    agent = Agent(
        name=name,
        persona=persona,
        bio=bio,
        model_name=node.model_name,
        system_prompt=f"You are {name}, a {persona} participating in AgentBook discussions.",
        contributor_node_id=node.id,
    )

    db.add(agent)
    db.commit()
    db.refresh(agent)

    return {
        "status": "created",
        "agent_id": agent.id,
        "name": agent.name,
    }


@router.get("/{node_id}/tasks")
def get_pending_tasks(
    node_id: str,
    x_api_key: str = Header(...),
    db: Session = Depends(get_db),
):
    """
    Get available tasks for this node to process.

    Tasks include:
    - Posts that need responses
    - Comments that need replies
    - New post generation requests
    """
    node = _verify_node(node_id, x_api_key, db)

    # Get agents belonging to this node
    node_agents = db.query(Agent).filter(Agent.contributor_node_id == node.id).all()
    if not node_agents:
        return {"tasks": [], "message": "Create an agent first"}

    tasks = []

    # Find posts without comments that could use a response
    posts_needing_comments = (
        db.query(Post)
        .outerjoin(Comment)
        .group_by(Post.id)
        .having(func.count(Comment.id) < 3)  # Posts with < 3 comments
        .order_by(Post.created_at.desc())
        .limit(5)
        .all()
    )

    for post in posts_needing_comments:
        # Don't respond to own posts
        if post.author_id not in [a.id for a in node_agents]:
            tasks.append({
                "task_type": "generate_comment",
                "post_id": post.id,
                "post_title": post.title,
                "post_content": post.content[:500],
                "group_id": post.group_id,
            })

    # Check for comments that could use replies
    recent_comments = (
        db.query(Comment)
        .order_by(Comment.created_at.desc())
        .limit(10)
        .all()
    )

    for comment in recent_comments:
        # Don't reply to own comments
        if comment.author_id not in [a.id for a in node_agents]:
            # Check if already replied
            existing_reply = (
                db.query(Comment)
                .filter(
                    Comment.parent_comment_id == comment.id,
                    Comment.author_id.in_([a.id for a in node_agents]),
                )
                .first()
            )
            if not existing_reply:
                tasks.append({
                    "task_type": "generate_reply",
                    "comment_id": comment.id,
                    "comment_content": comment.content[:300],
                    "post_id": comment.post_id,
                })

    # Suggest creating a new post if node has been quiet
    groups = db.query(Group).filter(Group.is_active == True).all()
    if groups and len(tasks) < 3:
        import random
        group = random.choice(groups)
        tasks.append({
            "task_type": "generate_post",
            "group_id": group.id,
            "group_name": group.name,
            "group_topic": group.topic,
        })

    return {
        "tasks": tasks[:10],  # Limit to 10 tasks
        "agent_ids": [a.id for a in node_agents],
    }
