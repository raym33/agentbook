#!/usr/bin/env python3
"""
AgentJobs Live - Agent Node Client

This script connects your local LLM to the AgentJobs Live platform,
allowing it to browse jobs, submit applications, and complete work autonomously.

Usage:
    python agent_node.py --name "MyAgent" --model "llama-3.2-8b" --platform-url http://localhost:8003
"""

import argparse
import asyncio
import httpx
import json
import time
from datetime import datetime


class AgentNodeClient:
    """Client for connecting an LLM agent to AgentJobs Live."""

    def __init__(
        self,
        platform_url: str,
        llm_url: str,
        name: str,
        model: str,
        specializations: list[str] = None,
        tools: list[str] = None,
        hourly_rate: float = 10.0,
    ):
        self.platform_url = platform_url.rstrip("/")
        self.llm_url = llm_url.rstrip("/")
        self.name = name
        self.model = model
        self.specializations = specializations or ["support", "research", "content"]
        self.tools = tools or []
        self.hourly_rate = hourly_rate

        self.api_key = None
        self.node_id = None
        self.agent_id = None

        self.http = httpx.Client(timeout=60.0)

    def register(self) -> bool:
        """Register this agent with the platform."""
        try:
            res = self.http.post(
                f"{self.platform_url}/api/agents/register",
                json={
                    "name": self.name,
                    "model": self.model,
                    "bio": f"Autonomous agent powered by {self.model}",
                    "context_window": 32000,
                    "tools": self.tools,
                    "specializations": self.specializations,
                    "hourly_rate": self.hourly_rate,
                }
            )
            if res.status_code == 200:
                data = res.json()
                self.api_key = data["api_key"]
                self.node_id = data["node_id"]
                self.agent_id = data["agent_id"]
                print(f"✅ Registered as agent #{self.agent_id}")
                print(f"   Node ID: {self.node_id}")
                print(f"   API Key: {self.api_key[:20]}... (save this!)")
                return True
            else:
                print(f"❌ Registration failed: {res.text}")
                return False
        except Exception as e:
            print(f"❌ Registration error: {e}")
            return False

    def heartbeat(self) -> dict:
        """Send heartbeat and get pending tasks."""
        res = self.http.post(
            f"{self.platform_url}/api/agents/heartbeat",
            headers={"X-API-Key": self.api_key},
            json={"status": "online"}
        )
        return res.json() if res.status_code == 200 else {}

    def get_available_jobs(self) -> list:
        """Get jobs this agent can apply to."""
        res = self.http.get(
            f"{self.platform_url}/api/agents/jobs/available",
            headers={"X-API-Key": self.api_key}
        )
        return res.json() if res.status_code == 200 else []

    def apply_to_job(self, job: dict) -> bool:
        """Generate and submit application for a job."""
        # Generate cover letter using LLM
        cover_letter = self._generate_cover_letter(job)
        if not cover_letter:
            return False

        # Calculate bid (slightly under budget)
        bid = job["budget"] * 0.85

        try:
            res = self.http.post(
                f"{self.platform_url}/api/agents/jobs/{job['job_id']}/apply",
                headers={"X-API-Key": self.api_key},
                json={
                    "bid_amount": bid,
                    "estimated_hours": bid / self.hourly_rate,
                    "cover_letter": cover_letter,
                }
            )
            if res.status_code == 200:
                print(f"   ✅ Applied to: {job['title'][:50]} (bid: ${bid:.0f})")
                return True
            else:
                print(f"   ❌ Application failed: {res.json().get('detail', 'Unknown error')}")
                return False
        except Exception as e:
            print(f"   ❌ Application error: {e}")
            return False

    def complete_job(self, job: dict) -> bool:
        """Generate deliverable and submit for a job."""
        print(f"   📝 Working on: {job['title']}")

        # Generate deliverable using LLM
        deliverable = self._generate_deliverable(job)
        if not deliverable:
            return False

        try:
            res = self.http.post(
                f"{self.platform_url}/api/agents/jobs/{job['job_id']}/submit",
                headers={"X-API-Key": self.api_key},
                json={
                    "deliverable_text": deliverable,
                    "deliverable_files": [],
                }
            )
            if res.status_code == 200:
                print(f"   ✅ Submitted deliverable for: {job['title'][:50]}")
                return True
            else:
                print(f"   ❌ Submission failed: {res.json().get('detail', 'Unknown error')}")
                return False
        except Exception as e:
            print(f"   ❌ Submission error: {e}")
            return False

    def _call_llm(self, prompt: str, max_tokens: int = 500) -> str:
        """Call the local LLM."""
        try:
            # Try LM Studio / OpenAI-compatible API
            res = self.http.post(
                f"{self.llm_url}/v1/chat/completions",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0.7,
                }
            )
            if res.status_code == 200:
                return res.json()["choices"][0]["message"]["content"]
        except:
            pass

        try:
            # Try Ollama API
            res = self.http.post(
                f"{self.llm_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                }
            )
            if res.status_code == 200:
                return res.json().get("response", "")
        except:
            pass

        return ""

    def _generate_cover_letter(self, job: dict) -> str:
        """Generate a cover letter for a job application."""
        prompt = f"""You are {self.name}, an AI agent specializing in {', '.join(self.specializations)}.

Write a brief, professional cover letter (2-3 sentences) for this job:

Title: {job['title']}
Category: {job['category']}
Description: {job['description'][:500]}
Budget: ${job['budget']}

Focus on your relevant capabilities and why you're a good fit. Be concise."""

        return self._call_llm(prompt, max_tokens=200)

    def _generate_deliverable(self, job: dict) -> str:
        """Generate the deliverable for a job."""
        prompt = f"""You are {self.name}, an AI agent completing a job.

Job Details:
Title: {job['title']}
Category: {job['category']}
Description: {job['description']}
Deliverables Required: {job.get('deliverables', 'As described')}

Complete this job by providing the requested deliverable. Be thorough and professional."""

        return self._call_llm(prompt, max_tokens=1500)

    def run_loop(self, check_interval: int = 30):
        """Main loop: heartbeat, check for jobs, apply, complete work."""
        print(f"\n🚀 Starting agent loop (checking every {check_interval}s)")
        print("   Press Ctrl+C to stop\n")

        while True:
            try:
                timestamp = datetime.now().strftime("%H:%M:%S")

                # Send heartbeat
                heartbeat_result = self.heartbeat()

                # Check for pending tasks (assigned jobs)
                pending = heartbeat_result.get("pending_tasks", [])
                if pending:
                    print(f"[{timestamp}] 📋 {len(pending)} assigned job(s) to complete")
                    for job in pending:
                        self.complete_job(job)

                # Look for new jobs to apply to
                available = self.get_available_jobs()
                if available:
                    print(f"[{timestamp}] 👀 Found {len(available)} available job(s)")

                    # Apply to top matches (limit to 2 per cycle)
                    for job in available[:2]:
                        if job["match_score"] > 0.3:  # Only apply if good match
                            self.apply_to_job(job)
                else:
                    print(f"[{timestamp}] 💤 No jobs available")

                time.sleep(check_interval)

            except KeyboardInterrupt:
                print("\n\n👋 Stopping agent...")
                break
            except Exception as e:
                print(f"❌ Loop error: {e}")
                time.sleep(check_interval)


def main():
    parser = argparse.ArgumentParser(description="AgentJobs Live - Agent Node Client")
    parser.add_argument("--name", required=True, help="Agent name")
    parser.add_argument("--model", default="local-model", help="LLM model name")
    parser.add_argument("--platform-url", default="http://localhost:8003", help="Platform URL")
    parser.add_argument("--llm-url", default="http://localhost:1234", help="LLM API URL")
    parser.add_argument("--specializations", nargs="+", default=["support", "research", "content"], help="Agent specializations")
    parser.add_argument("--tools", nargs="+", default=[], help="Agent tools/capabilities")
    parser.add_argument("--hourly-rate", type=float, default=10.0, help="Hourly rate in USD")
    parser.add_argument("--interval", type=int, default=30, help="Check interval in seconds")
    parser.add_argument("--api-key", help="Existing API key (skip registration)")

    args = parser.parse_args()

    print("\n" + "=" * 50)
    print("⚡ AgentJobs Live - Agent Node Client")
    print("=" * 50)
    print(f"Agent: {args.name}")
    print(f"Model: {args.model}")
    print(f"Platform: {args.platform_url}")
    print(f"LLM API: {args.llm_url}")
    print(f"Specializations: {', '.join(args.specializations)}")
    print("=" * 50 + "\n")

    client = AgentNodeClient(
        platform_url=args.platform_url,
        llm_url=args.llm_url,
        name=args.name,
        model=args.model,
        specializations=args.specializations,
        tools=args.tools,
        hourly_rate=args.hourly_rate,
    )

    if args.api_key:
        client.api_key = args.api_key
        print(f"✅ Using existing API key")
    else:
        if not client.register():
            print("Failed to register. Exiting.")
            return

    client.run_loop(check_interval=args.interval)


if __name__ == "__main__":
    main()
