"""Autonomous agent runner for job marketplace simulation."""
import random
import threading
import time
import logging
from datetime import datetime
from enum import Enum
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Agent, Job, Application, Review, JobStatus, ApplicationStatus, AgentStatus, TrustLevel
from app.agents.matcher import calculate_match_score, rank_jobs_for_agent
from app.agents.reputation import update_agent_reputation
from app.services.llm_client import llm_client
from app.config import settings

logger = logging.getLogger(__name__)


# ============ Agent Personas ============

EMPLOYER_PERSONAS = [
    {
        "name": "TechStartup",
        "display_name": "TechStartup Inc.",
        "model": "employer",
        "bio": "Fast-growing SaaS company always looking for AI help with support and content.",
        "budget_range": (30, 150),
        "preferred_categories": ["support", "content", "code"],
        "post_frequency": 0.4,  # Probability of posting a job each cycle
    },
    {
        "name": "DataCorp",
        "display_name": "DataCorp Analytics",
        "model": "employer",
        "bio": "Data analytics firm needing research and analysis tasks done.",
        "budget_range": (50, 300),
        "preferred_categories": ["research", "analysis", "data"],
        "post_frequency": 0.3,
    },
    {
        "name": "ContentAgency",
        "display_name": "Creative Content Agency",
        "model": "employer",
        "bio": "Digital marketing agency with constant content needs.",
        "budget_range": (20, 100),
        "preferred_categories": ["content"],
        "post_frequency": 0.5,
    },
]

WORKER_PERSONAS = [
    {
        "name": "SupportPro",
        "display_name": "SupportPro AI",
        "model": "llama-3.2-7b",
        "context_window": 32000,
        "tools": ["email", "crm", "chat"],
        "throughput": {"support": 500, "data": 150},
        "accuracy_scores": {"support": 0.94, "data": 0.88},
        "specializations": ["support"],
        "hourly_rate": 8.0,
        "bio": "Specialized customer support agent with high throughput.",
        "apply_tendency": 0.7,
        "preferred_categories": ["support"],
    },
    {
        "name": "ResearchBot",
        "display_name": "ResearchBot Claude",
        "model": "claude-3-haiku",
        "context_window": 200000,
        "tools": ["web_search", "document_analysis", "summarization"],
        "throughput": {"research": 40, "analysis": 25},
        "accuracy_scores": {"research": 0.97, "analysis": 0.95},
        "specializations": ["research", "analysis"],
        "hourly_rate": 15.0,
        "bio": "Premium research agent for deep analysis tasks.",
        "apply_tendency": 0.5,
        "preferred_categories": ["research", "analysis"],
    },
    {
        "name": "CodeHelper",
        "display_name": "CodeHelper GPT",
        "model": "gpt-4o-mini",
        "context_window": 128000,
        "tools": ["code_exec", "git", "testing"],
        "throughput": {"code": 15, "data": 80},
        "accuracy_scores": {"code": 0.91, "data": 0.93},
        "specializations": ["code", "data"],
        "hourly_rate": 12.0,
        "bio": "Versatile coding assistant for development tasks.",
        "apply_tendency": 0.6,
        "preferred_categories": ["code", "data"],
    },
    {
        "name": "ContentWriter",
        "display_name": "ContentWriter Pro",
        "model": "llama-3.2-13b",
        "context_window": 64000,
        "tools": ["web_search", "seo_analysis"],
        "throughput": {"content": 20},
        "accuracy_scores": {"content": 0.87},
        "specializations": ["content"],
        "hourly_rate": 10.0,
        "bio": "SEO-optimized content creation specialist.",
        "apply_tendency": 0.8,
        "preferred_categories": ["content"],
    },
    {
        "name": "DataCruncher",
        "display_name": "DataCruncher AI",
        "model": "mistral-7b",
        "context_window": 32000,
        "tools": ["data_processing", "spreadsheet", "visualization"],
        "throughput": {"data": 200, "analysis": 30},
        "accuracy_scores": {"data": 0.96, "analysis": 0.89},
        "specializations": ["data", "analysis"],
        "hourly_rate": 9.0,
        "bio": "High-speed data processing and transformation.",
        "apply_tendency": 0.65,
        "preferred_categories": ["data", "analysis"],
    },
]

JOB_TEMPLATES = {
    "support": [
        ("Handle {n} customer support tickets", "Respond to customer inquiries professionally. Maintain {acc}%+ satisfaction."),
        ("Email support coverage for {hours} hours", "Monitor and respond to support emails. Fast response time required."),
        ("Live chat support shift", "Handle live chat inquiries. Must be available for real-time responses."),
    ],
    "research": [
        ("Research {topic} market trends", "Comprehensive analysis of {topic}. Include competitors, market size, trends."),
        ("Competitive analysis: {n} companies", "Deep dive into {n} competitor companies. Pricing, features, positioning."),
        ("Industry report on {topic}", "Create detailed report on {topic} industry with actionable insights."),
    ],
    "content": [
        ("Write {n} blog posts on {topic}", "SEO-optimized articles, 800-1200 words each. Include keywords."),
        ("Create {n} product descriptions", "Compelling descriptions for e-commerce. 100-200 words each."),
        ("Social media content for {n} days", "Daily posts for Twitter, LinkedIn. Engaging and on-brand."),
    ],
    "code": [
        ("Fix {n} bug reports in {lang}", "Review and fix bugs. All tests must pass."),
        ("Code review for {lang} PR", "Thorough review of pull request. Security and performance focus."),
        ("Implement {feature} feature", "Build {feature} functionality. Include tests and documentation."),
    ],
    "data": [
        ("Process {n} data records", "Clean, transform, and validate data. Output in specified format."),
        ("Data migration from {source}", "Migrate data from {source} to new system. Verify integrity."),
        ("Create data pipeline for {task}", "Automated pipeline for {task}. Include error handling."),
    ],
    "analysis": [
        ("Financial analysis of {topic}", "Analyze financial data for {topic}. Include projections."),
        ("Sentiment analysis of {n} reviews", "Analyze customer reviews. Categorize and summarize findings."),
        ("Performance metrics report", "Analyze KPIs and create actionable report with recommendations."),
    ],
}


class AgentRole(Enum):
    EMPLOYER = "employer"
    WORKER = "worker"


@dataclass
class AgentState:
    agent_id: int
    role: AgentRole
    last_action_time: float = 0
    persona: dict = None


class AutonomousAgent:
    """An autonomous agent that can be employer or worker."""

    def __init__(self, agent: Agent, role: AgentRole, persona: dict, db: Session):
        self.agent = agent
        self.role = role
        self.persona = persona
        self.db = db

    def act(self) -> bool:
        """Perform an action based on role."""
        if self.role == AgentRole.EMPLOYER:
            return self._employer_action()
        else:
            return self._worker_action()

    def _employer_action(self) -> bool:
        """Employer posts jobs or reviews applications."""
        # Check if should post a new job
        if random.random() < self.persona.get("post_frequency", 0.3):
            return self._post_job()

        # Check pending applications on our jobs
        return self._review_applications()

    def _worker_action(self) -> bool:
        """Worker searches for jobs, applies, or completes work."""
        # Check if we have active jobs to complete
        active_job = self.db.query(Job).filter(
            Job.hired_agent_id == self.agent.id,
            Job.status == JobStatus.IN_PROGRESS
        ).first()

        if active_job:
            # 30% chance to complete the job this cycle
            if random.random() < 0.3:
                return self._complete_job(active_job)
            return False

        # Look for jobs to apply to
        if random.random() < self.persona.get("apply_tendency", 0.5):
            return self._search_and_apply()

        return False

    def _post_job(self) -> bool:
        """Employer posts a new job."""
        category = random.choice(self.persona.get("preferred_categories", ["support"]))
        templates = JOB_TEMPLATES.get(category, JOB_TEMPLATES["support"])
        title_template, desc_template = random.choice(templates)

        # Fill in template variables
        variables = {
            "n": random.choice([5, 10, 20, 50, 100]),
            "hours": random.choice([4, 8, 12]),
            "topic": random.choice(["AI", "SaaS", "fintech", "healthcare", "e-commerce"]),
            "acc": random.choice([90, 95, 98]),
            "lang": random.choice(["Python", "JavaScript", "TypeScript", "Go"]),
            "feature": random.choice(["authentication", "search", "notifications", "dashboard"]),
            "source": random.choice(["legacy system", "spreadsheets", "old API"]),
            "task": random.choice(["daily reports", "user sync", "backup"]),
        }

        title = title_template.format(**variables)
        description = desc_template.format(**variables)

        # Generate budget
        min_budget, max_budget = self.persona.get("budget_range", (50, 200))
        budget = random.randint(min_budget, max_budget)

        # Use LLM to enhance the job description
        try:
            system = f"You are {self.persona['display_name']}, posting a job for AI agents."
            prompt = f"""Create a professional job posting.

Title: {title}
Category: {category}
Budget: ${budget}
Base description: {description}

Write a clear, detailed job description (3-4 sentences). Include:
1. What needs to be done
2. Quality expectations
3. Any specific requirements

Just output the description text, nothing else."""

            enhanced_desc = llm_client.chat(system, prompt)
            description = enhanced_desc.strip()
        except Exception as e:
            logger.warning(f"LLM failed for job posting: {e}")

        # Create the job
        job = Job(
            title=title,
            description=description,
            category=category,
            budget=float(budget),
            payment_type="fixed",
            duration="one_time",
            poster_id=self.agent.id,
            poster_name=self.persona["display_name"],
            required_tools=self._get_required_tools(category),
            min_accuracy=0.85 if category in ["support", "code"] else 0.0,
        )
        self.db.add(job)
        self.db.commit()

        logger.info(f"[EMPLOYER] {self.agent.name} posted job: {title} (${budget})")
        return True

    def _get_required_tools(self, category: str) -> list:
        """Get typical required tools for a category."""
        tools_map = {
            "support": ["email", "crm"],
            "research": ["web_search"],
            "content": ["web_search"],
            "code": ["code_exec", "git"],
            "data": ["data_processing"],
            "analysis": ["document_analysis"],
        }
        return tools_map.get(category, [])

    def _review_applications(self) -> bool:
        """Review applications and hire an agent."""
        # Find our jobs with pending applications
        jobs = self.db.query(Job).filter(
            Job.poster_id == self.agent.id,
            Job.status == JobStatus.OPEN
        ).all()

        for job in jobs:
            applications = self.db.query(Application).filter(
                Application.job_id == job.id,
                Application.status == ApplicationStatus.PENDING
            ).order_by(Application.match_score.desc()).all()

            if len(applications) >= 2 or (len(applications) >= 1 and random.random() < 0.3):
                # Pick the best applicant (or use LLM to decide)
                best = applications[0]
                applicant = self.db.get(Agent, best.agent_id)

                # Hire them
                job.status = JobStatus.IN_PROGRESS
                job.hired_agent_id = best.agent_id
                job.started_at = datetime.utcnow()
                best.status = ApplicationStatus.ACCEPTED

                # Reject others
                for app in applications[1:]:
                    app.status = ApplicationStatus.REJECTED

                # Update worker status
                applicant.status = AgentStatus.BUSY

                self.db.commit()
                logger.info(f"[EMPLOYER] {self.agent.name} hired {applicant.name} for: {job.title}")
                return True

        return False

    def _search_and_apply(self) -> bool:
        """Search for matching jobs and apply."""
        # Get open jobs
        open_jobs = self.db.query(Job).filter(Job.status == JobStatus.OPEN).all()

        if not open_jobs:
            return False

        # Rank jobs by fit
        ranked = rank_jobs_for_agent(self.agent, open_jobs)

        if not ranked:
            return False

        # Filter to preferred categories
        preferred = self.persona.get("preferred_categories", [])
        if preferred:
            ranked = [(j, s, i) for j, s, i in ranked if j.category in preferred]

        if not ranked:
            return False

        # Pick a good job (weighted by score)
        job, score, info = ranked[0] if random.random() < 0.7 else random.choice(ranked[:3]) if len(ranked) >= 3 else ranked[0]

        # Check if already applied
        existing = self.db.query(Application).filter(
            Application.agent_id == self.agent.id,
            Application.job_id == job.id
        ).first()

        if existing:
            return False

        # Generate application using LLM
        try:
            system = f"""You are {self.agent.name}, an AI agent applying for jobs.
Your specializations: {', '.join(self.agent.specializations or [])}
Your rating: {self.agent.rating}/5.0
Jobs completed: {self.agent.jobs_completed}"""

            prompt = f"""Write a brief application (2-3 sentences) for this job:

Job: {job.title}
Category: {job.category}
Budget: ${job.budget}
Description: {job.description}

Explain why you're a good fit. Be specific about your capabilities.
Just output the application text."""

            cover_letter = llm_client.chat(system, prompt)
        except Exception as e:
            logger.warning(f"LLM failed for application: {e}")
            cover_letter = f"I'm well-suited for this {job.category} task with my {self.agent.jobs_completed} completed jobs and {self.agent.rating:.1f} rating."

        # Calculate bid (slightly under budget for competitiveness)
        bid = job.budget * random.uniform(0.85, 1.0)

        # Create application
        application = Application(
            agent_id=self.agent.id,
            job_id=job.id,
            bid_amount=round(bid, 2),
            cover_letter=cover_letter.strip(),
            match_score=score,
        )
        self.db.add(application)
        self.db.commit()

        logger.info(f"[WORKER] {self.agent.name} applied to: {job.title} (bid: ${bid:.2f}, score: {score:.2f})")
        return True

    def _complete_job(self, job: Job) -> bool:
        """Complete an assigned job."""
        # Generate work output using LLM
        try:
            system = f"You are {self.agent.name}, completing a job."
            prompt = f"""You just completed this job:

Job: {job.title}
Category: {job.category}
Description: {job.description}

Write a brief completion message (1-2 sentences) summarizing what you delivered."""

            completion_msg = llm_client.chat(system, prompt)
            logger.info(f"[WORKER] {self.agent.name} completed: {job.title}")
            logger.info(f"  Output: {completion_msg.strip()[:100]}...")
        except Exception as e:
            logger.warning(f"LLM failed for completion: {e}")

        # Mark job complete
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.utcnow()

        # Update agent stats
        self.agent.jobs_completed += 1
        self.agent.total_earnings += job.budget
        self.agent.status = AgentStatus.AVAILABLE

        # Auto-generate review (employer reviews worker)
        quality = random.uniform(4.0, 5.0) if random.random() < 0.8 else random.uniform(3.0, 4.0)
        timeliness = random.uniform(4.0, 5.0)
        communication = random.uniform(3.5, 5.0)
        overall = (quality + timeliness + communication) / 3

        review = Review(
            agent_id=self.agent.id,
            job_id=job.id,
            reviewer_name=job.poster_name,
            quality_score=round(quality, 1),
            timeliness_score=round(timeliness, 1),
            communication_score=round(communication, 1),
            overall_score=round(overall, 1),
            comment=f"Good work on the {job.category} task.",
            would_hire_again=1 if quality >= 4.0 else 0,
        )
        self.db.add(review)
        self.db.commit()

        # Update reputation
        update_agent_reputation(self.db, self.agent)

        return True


class AgentRunner:
    """Runs autonomous agents in background."""

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._agents: dict[int, AgentState] = {}

    def start(self):
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("AgentRunner started")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("AgentRunner stopped")

    def _run_loop(self):
        # Initial setup
        self._setup_agents()

        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as e:
                logger.error(f"AgentRunner error: {e}")

            self._stop_event.wait(settings.agent_cycle_interval)

    def _setup_agents(self):
        """Ensure all personas exist as agents in DB."""
        db = SessionLocal()
        try:
            # Create employer agents
            for persona in EMPLOYER_PERSONAS:
                agent = db.query(Agent).filter(Agent.name == persona["name"]).first()
                if not agent:
                    agent = Agent(
                        name=persona["name"],
                        model=persona["model"],
                        bio=persona["bio"],
                        context_window=0,
                        tools=[],
                        status=AgentStatus.AVAILABLE,
                    )
                    db.add(agent)
                    db.commit()
                    db.refresh(agent)

                self._agents[agent.id] = AgentState(
                    agent_id=agent.id,
                    role=AgentRole.EMPLOYER,
                    persona=persona,
                )

            # Create worker agents
            for persona in WORKER_PERSONAS:
                agent = db.query(Agent).filter(Agent.name == persona["name"]).first()
                if not agent:
                    agent = Agent(
                        name=persona["name"],
                        model=persona["model"],
                        bio=persona["bio"],
                        context_window=persona["context_window"],
                        tools=persona["tools"],
                        throughput=persona["throughput"],
                        accuracy_scores=persona["accuracy_scores"],
                        specializations=persona["specializations"],
                        hourly_rate=persona["hourly_rate"],
                        status=AgentStatus.AVAILABLE,
                    )
                    db.add(agent)
                    db.commit()
                    db.refresh(agent)

                self._agents[agent.id] = AgentState(
                    agent_id=agent.id,
                    role=AgentRole.WORKER,
                    persona=persona,
                )

            logger.info(f"Setup {len(self._agents)} agents ({len(EMPLOYER_PERSONAS)} employers, {len(WORKER_PERSONAS)} workers)")

        finally:
            db.close()

    def _tick(self):
        """Run one cycle of agent actions."""
        db = SessionLocal()
        try:
            # Shuffle to randomize action order
            agent_ids = list(self._agents.keys())
            random.shuffle(agent_ids)

            for agent_id in agent_ids:
                state = self._agents[agent_id]
                agent = db.get(Agent, agent_id)

                if not agent:
                    continue

                # Create autonomous agent and let it act
                autonomous = AutonomousAgent(agent, state.role, state.persona, db)

                try:
                    autonomous.act()
                except Exception as e:
                    logger.error(f"Agent {agent.name} action failed: {e}")

                # Small delay between agents
                time.sleep(1)

        finally:
            db.close()

    def get_status(self) -> dict:
        """Get current status of all agents."""
        db = SessionLocal()
        try:
            status = {
                "running": self._thread and self._thread.is_alive(),
                "agents": [],
            }

            for agent_id, state in self._agents.items():
                agent = db.get(Agent, agent_id)
                if agent:
                    status["agents"].append({
                        "id": agent.id,
                        "name": agent.name,
                        "role": state.role.value,
                        "status": agent.status.value if agent.status else "unknown",
                        "jobs_completed": agent.jobs_completed,
                        "rating": agent.rating,
                    })

            return status
        finally:
            db.close()


agent_runner = AgentRunner()
