"""
Signal-Foundry — Unified FastAPI Application.

Single entry point serving all three tasks:
- Task 1: CI/CD Skills Engine (/api/v1/skills/...)
- Task 2: Browser Automation Agent (/api/v1/browser/...)
- Task 3: SEC 10-K Extraction (/api/v1/sec/...)

Plus: dashboard, health checks, metrics, and model selection.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.config import get_settings
from src.llm_provider import list_available_models
from src.shared.cost_tracker import get_cost_tracker
from src.shared.logger import generate_trace_id, get_logger, setup_logging
from src.shared.schemas import HealthResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    settings = get_settings()
    setup_logging(settings.log_level)
    logger = get_logger("main")
    logger.info("application_starting", environment=settings.environment)
    yield
    logger.info("application_shutting_down")


app = FastAPI(
    title="Signal-Foundry",
    description=(
        "Evaluation-first AI systems: Claude Skills for CI/CD, "
        "browser automation agent, and SEC 10-K extraction pipeline."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_static_dir = os.path.join(_base_dir, "static")
_templates_dir = os.path.join(_base_dir, "templates")

if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

templates = Jinja2Templates(directory=_templates_dir) if os.path.isdir(_templates_dir) else None


# --- Middleware: Trace ID injection ---
@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    """Inject trace ID into every request for end-to-end tracing."""
    trace_id = generate_trace_id()
    request.state.trace_id = trace_id
    response = await call_next(request)
    response.headers["X-Trace-ID"] = trace_id
    return response


# --- Core Routes ---


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Health check endpoint for Zeabur and monitoring."""
    settings = get_settings()
    return HealthResponse(environment=settings.environment)


@app.get("/api/v1/models", tags=["System"])
async def list_models():
    """List all available LLM models with their providers."""
    return {"models": list_available_models()}


@app.get("/metrics", tags=["System"])
async def get_metrics():
    """Get aggregated cost and performance metrics."""
    tracker = get_cost_tracker()
    return tracker.get_session_summary()


@app.get("/", response_class=HTMLResponse, tags=["UI"])
async def dashboard(request: Request):
    """Main dashboard — links to all three task UIs."""
    models = list_available_models()
    if templates:
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "models": models,
            },
        )
    # Fallback if templates not yet created
    return HTMLResponse(
        content="""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Signal-Foundry</title>
            <style>
                body { font-family: 'Inter', system-ui, sans-serif; max-width: 800px;
                       margin: 0 auto; padding: 2rem; background: #0f172a; color: #e2e8f0; }
                h1 { background: linear-gradient(135deg, #3b82f6, #8b5cf6);
                     -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
                .task-card { background: #1e293b; border: 1px solid #334155;
                             border-radius: 12px; padding: 1.5rem; margin: 1rem 0;
                             transition: transform 0.2s, box-shadow 0.2s; }
                .task-card:hover { transform: translateY(-2px);
                                   box-shadow: 0 8px 25px rgba(59,130,246,0.15); }
                a { color: #60a5fa; text-decoration: none; }
                .status { color: #22c55e; font-size: 0.875rem; }
                .badge { display: inline-block; padding: 2px 8px; border-radius: 4px;
                         font-size: 0.75rem; background: #3b82f6; color: white; }
            </style>
        </head>
        <body>
            <h1>🔧 Signal-Foundry</h1>
            <p>Evaluation-first AI systems for CI/CD, browser automation, and SEC extraction.</p>

            <div class="task-card">
                <h3>📋 Task 1: CI/CD Skills Engine</h3>
                <p>GitHub CI/CD workflows as reusable Claude Skills</p>
                <span class="badge">Skills</span>
                <a href="/api/v1/skills/docs">API Docs →</a>
                <span class="status">● Ready</span>
            </div>

            <div class="task-card">
                <h3>🌐 Task 2: Browser Automation Agent</h3>
                <p>Self-healing browser automation with natural language</p>
                <span class="badge">Agent</span>
                <a href="/api/v1/browser/docs">API Docs →</a>
                <span class="status">● Ready</span>
            </div>

            <div class="task-card">
                <h3>📊 Task 3: SEC 10-K Extraction</h3>
                <p>Hybrid rule+LLM structured extraction from SEC filings</p>
                <span class="badge">Pipeline</span>
                <a href="/api/v1/sec/docs">API Docs →</a>
                <span class="status">● Ready</span>
            </div>

            <hr style="border-color: #334155; margin: 2rem 0;">
            <p style="font-size: 0.875rem;">
                <a href="/health">Health</a> ·
                <a href="/metrics">Metrics</a> ·
                <a href="/api/v1/models">Models</a> ·
                <a href="/docs">API Docs</a>
            </p>
        </body>
        </html>
        """,
        status_code=200,
    )


# --- Task Routers (will be imported as modules are built) ---

# Task 1: CI/CD Skills
try:
    from src.task1_cicd.router import router as task1_router
    app.include_router(task1_router, prefix="/api/v1/skills", tags=["Task 1: CI/CD Skills"])
except ImportError:
    pass

# Task 2: Browser Agent
try:
    from src.task2_browser.router import router as task2_router
    app.include_router(task2_router, prefix="/api/v1/browser", tags=["Task 2: Browser Agent"])
except ImportError:
    pass

# Task 3: SEC 10-K
try:
    from src.task3_sec.router import router as task3_router
    app.include_router(task3_router, prefix="/api/v1/sec", tags=["Task 3: SEC 10-K"])
except ImportError:
    pass
