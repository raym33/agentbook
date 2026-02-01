#!/usr/bin/env bash
set -euo pipefail
export DATABASE_URL="sqlite:///./data/app.db"
export LLM_BASE_URL="${LLM_BASE_URL:-http://10.141.199.240:1234}"
export LLM_MODEL="${LLM_MODEL:-mistralai/ministral-3-14b-reasoning}"
export AGENT_LOOP_INTERVAL_SECONDS="${AGENT_LOOP_INTERVAL_SECONDS:-2}"
export MAX_AGENTS="${MAX_AGENTS:-10}"

uvicorn app.main:app --host 0.0.0.0 --port 8000
