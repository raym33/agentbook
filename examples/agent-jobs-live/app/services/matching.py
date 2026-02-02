"""Job-Agent matching service."""
from dataclasses import dataclass
from app.models import AgentNode, Job, TrustLevel


TRUST_LEVEL_ORDER = [TrustLevel.NEW, TrustLevel.VERIFIED, TrustLevel.TRUSTED, TrustLevel.ELITE]


@dataclass
class MatchBreakdown:
    tools_score: float = 0.0
    context_score: float = 0.0
    accuracy_score: float = 0.0
    reputation_score: float = 0.0
    price_score: float = 0.0
    specialization_score: float = 0.0
    total: float = 0.0


def calculate_match_score(agent: AgentNode, job: Job) -> tuple[float, MatchBreakdown]:
    """
    Calculate how well an agent matches a job.
    Returns (score, breakdown) where score is 0.0-1.0.
    """
    breakdown = MatchBreakdown()

    # ===== HARD REQUIREMENTS (disqualifying) =====

    # Tool compatibility
    agent_tools = set(agent.tools or [])
    required_tools = set(job.required_tools or [])
    if required_tools and not required_tools.issubset(agent_tools):
        return 0.0, breakdown

    # Context window
    if job.min_context and agent.context_window < job.min_context:
        return 0.0, breakdown

    # Trust level
    if job.min_trust_level:
        try:
            agent_level_idx = TRUST_LEVEL_ORDER.index(agent.trust_level) if agent.trust_level else 0
            required_level = TrustLevel(job.min_trust_level) if isinstance(job.min_trust_level, str) else job.min_trust_level
            required_level_idx = TRUST_LEVEL_ORDER.index(required_level)
            if agent_level_idx < required_level_idx:
                return 0.0, breakdown
        except (ValueError, AttributeError):
            pass

    # ===== SOFT SCORING =====

    # Tools score (bonus for extra tools)
    if agent_tools:
        extra_tools = len(agent_tools - required_tools)
        breakdown.tools_score = min(0.1 + (extra_tools * 0.02), 0.15)

    # Context score
    if job.min_context and agent.context_window > job.min_context:
        context_ratio = agent.context_window / job.min_context
        breakdown.context_score = min((context_ratio - 1) * 0.1, 0.1)
    else:
        breakdown.context_score = 0.05

    # Accuracy match
    if job.min_accuracy and job.category:
        agent_accuracy = (agent.accuracy_scores or {}).get(job.category, 0)
        if agent_accuracy >= job.min_accuracy:
            breakdown.accuracy_score = agent_accuracy * 0.25
        elif agent_accuracy > 0:
            breakdown.accuracy_score = (agent_accuracy / job.min_accuracy) * 0.15

    # Reputation score
    if agent.rating > 0:
        breakdown.reputation_score = (agent.rating / 5.0) * 0.25
        if agent.jobs_completed >= 100:
            breakdown.reputation_score += 0.05
        elif agent.jobs_completed >= 25:
            breakdown.reputation_score += 0.03

    # Price competitiveness
    if job.budget and agent.hourly_rate:
        # Estimate hours based on category
        estimated_hours = {"support": 4, "research": 8, "content": 6, "code": 10, "data": 5, "analysis": 8}.get(job.category, 6)
        estimated_cost = agent.hourly_rate * estimated_hours
        if estimated_cost <= job.budget:
            price_ratio = 1 - (estimated_cost / job.budget)
            breakdown.price_score = price_ratio * 0.15

    # Specialization bonus
    if job.category and job.category in (agent.specializations or []):
        breakdown.specialization_score = 0.15

    # Calculate total
    breakdown.total = (
        breakdown.tools_score +
        breakdown.context_score +
        breakdown.accuracy_score +
        breakdown.reputation_score +
        breakdown.price_score +
        breakdown.specialization_score
    )

    return min(breakdown.total, 1.0), breakdown


def rank_agents_for_job(agents: list[AgentNode], job: Job) -> list[tuple[AgentNode, float, MatchBreakdown]]:
    """Rank all agents by match score for a job."""
    results = []
    for agent in agents:
        if agent.status.value == "offline":
            continue
        score, breakdown = calculate_match_score(agent, job)
        if score > 0:
            results.append((agent, score, breakdown))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def find_matching_jobs(agent: AgentNode, jobs: list[Job]) -> list[tuple[Job, float]]:
    """Find jobs that match an agent's capabilities."""
    results = []
    for job in jobs:
        score, _ = calculate_match_score(agent, job)
        if score > 0:
            results.append((job, score))

    results.sort(key=lambda x: x[1], reverse=True)
    return results
