"""Job-Agent matching algorithm."""
from dataclasses import dataclass
from app.models import Agent, Job, TrustLevel


@dataclass
class MatchBreakdown:
    tools_score: float = 0.0
    context_score: float = 0.0
    throughput_score: float = 0.0
    accuracy_score: float = 0.0
    reputation_score: float = 0.0
    price_score: float = 0.0
    specialization_score: float = 0.0
    total: float = 0.0


TRUST_LEVEL_ORDER = [TrustLevel.NEW, TrustLevel.VERIFIED, TrustLevel.TRUSTED, TrustLevel.ELITE]


def calculate_match_score(agent: Agent, job: Job) -> tuple[float, MatchBreakdown]:
    """
    Calculate how well an agent matches a job.
    Returns (score, breakdown) where score is 0.0-1.0.
    """
    breakdown = MatchBreakdown()

    # ===== HARD REQUIREMENTS (disqualifying) =====

    # Tool compatibility (required)
    agent_tools = set(agent.tools or [])
    required_tools = set(job.required_tools or [])
    if required_tools and not required_tools.issubset(agent_tools):
        return 0.0, breakdown

    # Context window (required)
    if job.min_context and agent.context_window < job.min_context:
        return 0.0, breakdown

    # Trust level (required)
    if job.min_trust_level:
        agent_level_idx = TRUST_LEVEL_ORDER.index(agent.trust_level) if agent.trust_level in TRUST_LEVEL_ORDER else 0
        required_level_idx = TRUST_LEVEL_ORDER.index(job.min_trust_level) if job.min_trust_level in TRUST_LEVEL_ORDER else 0
        if agent_level_idx < required_level_idx:
            return 0.0, breakdown

    # ===== SOFT SCORING =====

    # Tools score (bonus for having extra tools)
    if agent_tools:
        extra_tools = len(agent_tools - required_tools)
        breakdown.tools_score = min(0.1 + (extra_tools * 0.02), 0.15)

    # Context score (bonus for larger context)
    if job.min_context and agent.context_window > job.min_context:
        context_ratio = agent.context_window / job.min_context
        breakdown.context_score = min((context_ratio - 1) * 0.1, 0.1)
    else:
        breakdown.context_score = 0.05  # Base score if no requirement

    # Throughput match
    if job.min_throughput and job.category:
        agent_throughput = (agent.throughput or {}).get(job.category, 0)
        if agent_throughput >= job.min_throughput:
            throughput_ratio = agent_throughput / job.min_throughput
            breakdown.throughput_score = min(throughput_ratio * 0.15, 0.25)

    # Accuracy match
    if job.min_accuracy and job.category:
        agent_accuracy = (agent.accuracy_scores or {}).get(job.category, 0)
        if agent_accuracy >= job.min_accuracy:
            breakdown.accuracy_score = agent_accuracy * 0.25
        elif agent_accuracy > 0:
            # Partial score if close
            breakdown.accuracy_score = (agent_accuracy / job.min_accuracy) * 0.15

    # Reputation score
    if agent.rating > 0:
        breakdown.reputation_score = (agent.rating / 5.0) * 0.20
        # Bonus for many completed jobs
        if agent.jobs_completed >= 100:
            breakdown.reputation_score += 0.05
        elif agent.jobs_completed >= 25:
            breakdown.reputation_score += 0.03

    # Price competitiveness
    if job.budget and agent.hourly_rate:
        if agent.hourly_rate <= job.budget:
            price_ratio = 1 - (agent.hourly_rate / job.budget)
            breakdown.price_score = price_ratio * 0.15

    # Specialization bonus
    if job.category and job.category in (agent.specializations or []):
        breakdown.specialization_score = 0.15

    # Calculate total
    breakdown.total = (
        breakdown.tools_score +
        breakdown.context_score +
        breakdown.throughput_score +
        breakdown.accuracy_score +
        breakdown.reputation_score +
        breakdown.price_score +
        breakdown.specialization_score
    )

    return min(breakdown.total, 1.0), breakdown


def rank_agents_for_job(agents: list[Agent], job: Job) -> list[tuple[Agent, float, MatchBreakdown]]:
    """Rank all agents by match score for a job."""
    results = []
    for agent in agents:
        score, breakdown = calculate_match_score(agent, job)
        if score > 0:
            results.append((agent, score, breakdown))

    # Sort by score descending
    results.sort(key=lambda x: x[1], reverse=True)
    return results


def rank_jobs_for_agent(agent: Agent, jobs: list[Job]) -> list[tuple[Job, float, dict]]:
    """Rank all jobs by attractiveness for an agent."""
    results = []

    for job in jobs:
        score, breakdown = calculate_match_score(agent, job)
        if score == 0:
            continue

        # Calculate expected profit
        estimated_hours = estimate_job_hours(job)
        expected_earnings = job.budget
        expected_cost = estimated_hours * agent.hourly_rate * 0.5  # Rough cost estimate
        expected_profit = expected_earnings - expected_cost

        # Competition factor
        app_count = len(job.applications) if hasattr(job, 'applications') else 0
        competition = "low" if app_count < 3 else "medium" if app_count < 8 else "high"
        competition_penalty = {"low": 0, "medium": 0.1, "high": 0.2}.get(competition, 0)

        # Adjusted score
        adjusted_score = score * (1 - competition_penalty)

        results.append((job, adjusted_score, {
            "match_score": score,
            "expected_profit": expected_profit,
            "competition": competition,
            "breakdown": breakdown.__dict__,
        }))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def estimate_job_hours(job: Job) -> float:
    """Estimate hours to complete a job based on category and description."""
    base_hours = {
        "support": 4,
        "research": 8,
        "content": 6,
        "code": 10,
        "data": 5,
        "analysis": 8,
    }.get(job.category, 6)

    # Adjust by budget (higher budget = more work expected)
    if job.budget > 100:
        base_hours *= 1.5
    elif job.budget > 50:
        base_hours *= 1.2

    return base_hours


def get_match_recommendation(score: float, breakdown: MatchBreakdown) -> str:
    """Generate a recommendation based on match score."""
    if score >= 0.8:
        return "Excellent match - highly recommended"
    elif score >= 0.6:
        return "Good match - worth considering"
    elif score >= 0.4:
        return "Moderate match - review carefully"
    elif score >= 0.2:
        return "Weak match - may struggle with requirements"
    else:
        return "Poor match - not recommended"
