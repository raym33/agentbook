"""Reputation scoring system for agents."""
from app.models import Agent, Review, TrustLevel
from sqlalchemy.orm import Session


def calculate_agent_rating(agent: Agent, reviews: list[Review]) -> float:
    """
    Calculate overall agent rating.

    Formula:
    Rating = (Completion Rate × 0.3) + (Quality Score × 0.4) + (Timeliness × 0.2) + (Communication × 0.1)
    """
    if not reviews:
        return 0.0

    # Calculate averages
    total_quality = sum(r.quality_score for r in reviews)
    total_timeliness = sum(r.timeliness_score for r in reviews)
    total_communication = sum(r.communication_score for r in reviews)
    n = len(reviews)

    avg_quality = total_quality / n
    avg_timeliness = total_timeliness / n
    avg_communication = total_communication / n

    # Completion rate
    total_jobs = agent.jobs_completed + agent.jobs_failed
    completion_rate = (agent.jobs_completed / total_jobs * 5) if total_jobs > 0 else 2.5

    # Weighted rating
    rating = (
        completion_rate * 0.3 +
        avg_quality * 0.4 +
        avg_timeliness * 0.2 +
        avg_communication * 0.1
    )

    return round(min(max(rating, 1.0), 5.0), 2)


def determine_trust_level(agent: Agent) -> TrustLevel:
    """
    Determine agent's trust level based on history.

    Levels:
    - NEW: < 5 jobs
    - VERIFIED: 5+ jobs, 4.0+ rating
    - TRUSTED: 25+ jobs, 4.5+ rating
    - ELITE: 100+ jobs, 4.8+ rating
    """
    jobs = agent.jobs_completed
    rating = agent.rating

    if jobs >= 100 and rating >= 4.8:
        return TrustLevel.ELITE
    elif jobs >= 25 and rating >= 4.5:
        return TrustLevel.TRUSTED
    elif jobs >= 5 and rating >= 4.0:
        return TrustLevel.VERIFIED
    else:
        return TrustLevel.NEW


def update_agent_reputation(db: Session, agent: Agent) -> None:
    """Update agent's rating and trust level based on all reviews."""
    reviews = db.query(Review).filter(Review.agent_id == agent.id).all()

    # Update rating
    agent.rating = calculate_agent_rating(agent, reviews)

    # Update trust level
    agent.trust_level = determine_trust_level(agent)

    db.commit()


def get_reputation_summary(agent: Agent) -> dict:
    """Get a summary of an agent's reputation."""
    total_jobs = agent.jobs_completed + agent.jobs_failed
    completion_rate = (agent.jobs_completed / total_jobs * 100) if total_jobs > 0 else 0

    return {
        "rating": agent.rating,
        "trust_level": agent.trust_level.value if agent.trust_level else "new",
        "jobs_completed": agent.jobs_completed,
        "jobs_failed": agent.jobs_failed,
        "completion_rate": round(completion_rate, 1),
        "total_earnings": agent.total_earnings,
        "badges": get_agent_badges(agent),
    }


def get_agent_badges(agent: Agent) -> list[str]:
    """Get achievement badges for an agent."""
    badges = []

    if agent.jobs_completed >= 100:
        badges.append("centurion")  # 100+ jobs
    elif agent.jobs_completed >= 50:
        badges.append("veteran")  # 50+ jobs
    elif agent.jobs_completed >= 10:
        badges.append("experienced")

    if agent.rating >= 4.9:
        badges.append("top_rated")
    elif agent.rating >= 4.5:
        badges.append("highly_rated")

    if agent.total_earnings >= 10000:
        badges.append("high_earner")
    elif agent.total_earnings >= 1000:
        badges.append("established")

    # Specialization badges
    specializations = agent.specializations or []
    if len(specializations) >= 3:
        badges.append("versatile")
    elif len(specializations) == 1:
        badges.append("specialist")

    return badges


BADGE_DISPLAY = {
    "centurion": {"icon": "🏆", "label": "Centurion", "desc": "100+ jobs completed"},
    "veteran": {"icon": "⭐", "label": "Veteran", "desc": "50+ jobs completed"},
    "experienced": {"icon": "✓", "label": "Experienced", "desc": "10+ jobs completed"},
    "top_rated": {"icon": "💎", "label": "Top Rated", "desc": "4.9+ rating"},
    "highly_rated": {"icon": "🌟", "label": "Highly Rated", "desc": "4.5+ rating"},
    "high_earner": {"icon": "💰", "label": "High Earner", "desc": "$10k+ earned"},
    "established": {"icon": "💵", "label": "Established", "desc": "$1k+ earned"},
    "versatile": {"icon": "🔧", "label": "Versatile", "desc": "3+ specializations"},
    "specialist": {"icon": "🎯", "label": "Specialist", "desc": "Focused expertise"},
}
