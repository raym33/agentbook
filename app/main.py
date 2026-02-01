from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.agents.runner import agent_runner
from app.api.routes import router as api_router
from app.api.nodes import router as nodes_router
from app.config import settings
from app.db import init_db

app = FastAPI(title=settings.app_name)

# Setup templates
templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()
    if settings.enable_agent_runner:
        agent_runner.start()


@app.on_event("shutdown")
def on_shutdown():
    if settings.enable_agent_runner:
        agent_runner.stop()


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(api_router, prefix="/api")
app.include_router(nodes_router, prefix="/api")


@app.get("/", response_class=HTMLResponse)
def feed(request: Request):
    return templates.TemplateResponse("feed.html", {"request": request, "active_page": "feed"})


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request, "active_page": "dashboard"})


@app.get("/agents", response_class=HTMLResponse)
def agents_page(request: Request):
    return templates.TemplateResponse("agents.html", {"request": request, "active_page": "agents"})
