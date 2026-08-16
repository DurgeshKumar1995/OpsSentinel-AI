"""SafeOps HTTP application."""

import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.memory import MemorySaver
from openai import OpenAIError
from pydantic import BaseModel, Field

from config.settings import settings
from graph.workflow import get_graph_builder
from services.agent_logic import execute_tools
from services.audit import AuditLogger
from services.domain import OUT_OF_SCOPE_MESSAGE, is_devops_request
from services.embeddings import create_embedder
from services.local_reasoning import try_local_readonly_answer
from services.memory import LearningStore, Lesson
from services.rate_limit import RateLimiter
from services.security import inspect_prompt, redact_secrets
from services.usage import summarize_usage, zero_usage
from services.visuals import VisualGenerator

logger = logging.getLogger("safeops")
audit = AuditLogger(settings.audit_log_path)


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Create runtime dependencies at startup and release references at shutdown."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    application.state.agent = get_graph_builder().compile(checkpointer=MemorySaver())
    application.state.embedder = create_embedder(settings)
    application.state.memory = LearningStore(embedder=application.state.embedder)
    application.state.rate_limiter = RateLimiter(
        settings.rate_limit_requests, settings.rate_limit_window_seconds
    )
    application.state.visual_generator = VisualGenerator(settings)
    logger.info("application_started env=%s tool_mode=%s", settings.app_env, settings.tool_mode)
    yield
    logger.info("application_stopped")


class IncidentRequest(BaseModel):
    message: str = Field(min_length=3, max_length=settings.max_input_chars)
    thread_id: str | None = Field(default=None, min_length=3, max_length=100)


class ApprovalRequest(BaseModel):
    approved: bool


class FeedbackRequest(BaseModel):
    service_name: str = Field(min_length=1, max_length=200)
    symptom: str = Field(min_length=3, max_length=2000)
    resolution: str = Field(min_length=3, max_length=4000)
    rating: int = Field(ge=1, le=5)
    operator_approved: bool = False


class VisualRequest(BaseModel):
    request: str = Field(min_length=3, max_length=settings.max_input_chars)
    answer: str = Field(min_length=3, max_length=5000)


def _config(thread_id: str):
    return {"configurable": {"thread_id": thread_id}}


def _flow(*steps: tuple[str, str, str]) -> list[dict[str, str]]:
    """Build a stable, user-visible explanation of how an answer was produced."""
    return [
        {"id": step_id, "label": label, "status": status}
        for step_id, label, status in steps
    ]


def _response(thread_id: str, state: dict) -> dict:
    last = state["messages"][-1]
    calls = getattr(last, "tool_calls", []) or []
    pending = next((call for call in calls if call["name"] == "restart_service"), None)
    status = "approval_required" if pending else "completed"
    usage = summarize_usage(
        state.get("messages", []), settings.openai_model,
        settings.model_input_price_per_million,
        settings.model_output_price_per_million,
    )
    return {
        "thread_id": thread_id,
        "status": status,
        "message": getattr(last, "content", ""),
        "pending_action": pending,
        "source": "tools",
        "learned": False,
        "usage": usage,
        "flow": _flow(
            ("request", "Request received", "complete"),
            ("guard", "Security and DevOps scope checked", "complete"),
            ("memory", "Learned memory checked", "complete"),
            ("evidence", "Dataset and diagnostic evidence reviewed", "complete"),
            (
                "approval",
                "Human approval required" if pending else "No risky action pending",
                "active" if pending else "complete",
            ),
            ("answer", "Final answer", "waiting" if pending else "complete"),
        ),
    }


def _track(memory: LearningStore, query: str, response: dict) -> dict:
    """Attach zero usage when no model ran and persist the request total."""
    response.setdefault("usage", zero_usage())
    memory.record_usage(
        response["thread_id"], redact_secrets(query),
        response.get("source", "workflow"), response["usage"]
    )
    return response


def _contains_risky_action(state: dict) -> bool:
    return any(
        call.get("name") == "restart_service"
        for message in state.get("messages", [])
        for call in (getattr(message, "tool_calls", []) or [])
    )


app = FastAPI(
    title="SafeOps Incident Agent",
    version="1.0.0",
    description="Human-supervised incident diagnosis with reviewed outcome learning.",
    docs_url="/developer/docs",
    redoc_url="/developer/redoc",
    lifespan=lifespan,
)
WEB_DIR = Path(__file__).parent / "web"
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", include_in_schema=False)
def homepage():
    """Serve the operator-friendly incident workspace."""
    return FileResponse(WEB_DIR / "index.html")


@app.get("/docs", include_in_schema=False)
def old_docs_redirect():
    """Send old documentation bookmarks to the user application."""
    return RedirectResponse(url="/", status_code=307)


@app.get("/health")
def health():
    return {"status": "ok", "environment": settings.app_env, "tool_mode": settings.tool_mode}


@app.get("/ready")
def readiness(request: Request):
    try:
        request.app.state.memory.relevant("readiness", limit=1)
    except OSError as error:
        raise HTTPException(status_code=503, detail="Persistence unavailable") from error
    return {"status": "ready"}


@app.post("/incidents")
def create_incident(payload: IncidentRequest, request: Request):
    agent = request.app.state.agent
    memory = request.app.state.memory
    rate_limiter = request.app.state.rate_limiter
    client_key = request.client.host if request.client else "unknown"
    if not rate_limiter.allow(client_key):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait and try again.")
    thread_id = payload.thread_id or str(uuid4())
    audit.write("incident_received", thread_id=thread_id, client=client_key)
    security = inspect_prompt(payload.message)
    if not security.allowed:
        audit.write("incident_blocked", thread_id=thread_id, reason="security_guard")
        return _track(memory, payload.message, {
            "thread_id": thread_id,
            "status": "security_blocked",
            "message": security.reason,
            "pending_action": None,
            "source": "security_guard",
            "learned": False,
            "flow": _flow(
                ("request", "Request received", "complete"),
                ("guard", "Prompt-injection security check", "blocked"),
                ("answer", "Request safely blocked", "complete"),
            ),
        })
    if not is_devops_request(payload.message):
        audit.write("incident_blocked", thread_id=thread_id, reason="scope_guard")
        return _track(memory, payload.message, {
            "thread_id": thread_id,
            "status": "out_of_scope",
            "message": OUT_OF_SCOPE_MESSAGE,
            "pending_action": None,
            "source": "scope_guard",
            "learned": False,
            "flow": _flow(
                ("request", "Request received", "complete"),
                ("guard", "DevOps scope check", "blocked"),
                ("answer", "Scope guidance returned", "complete"),
            ),
        })
    recalled = memory.recall_safe_response(payload.message)
    if recalled is None:
        recalled = memory.recall_similar_response(
            payload.message, threshold=settings.semantic_memory_threshold
        )
    if recalled:
        audit.write("incident_completed", thread_id=thread_id, source="learned_memory")
        return _track(memory, payload.message, {
            "thread_id": thread_id,
            "status": "completed",
            "message": recalled.response,
            "pending_action": None,
            "source": "learned_memory",
            "learned": True,
            "memory_uses": recalled.uses,
            "similarity": recalled.similarity,
            "flow": _flow(
                ("request", "Request received", "complete"),
                ("guard", "Security and DevOps scope checked", "complete"),
                ("memory", "Matching learned answer found", "complete"),
                ("tools", "Diagnostic tools skipped", "skipped"),
                ("answer", "Learned answer returned", "complete"),
            ),
        })
    local_answer = try_local_readonly_answer(payload.message)
    if local_answer:
        response = {
            "thread_id": thread_id,
            "status": "completed",
            "message": local_answer["message"],
            "pending_action": None,
            "source": "local_tools",
            "learned": False,
            "usage": zero_usage(),
            "flow": _flow(
                ("request", "Request received", "complete"),
                ("guard", "Security and DevOps scope checked", "complete"),
                ("route", "Local read-only route selected", "complete"),
                ("tools", "Diagnostic evidence fetched locally", "complete"),
                ("ai", "External AI call skipped", "skipped"),
                ("answer", "Evidence-based answer returned", "complete"),
            ),
        }
        memory.remember_safe_response(payload.message, response["message"])
        audit.write("incident_completed", thread_id=thread_id, source="local_tools")
        return _track(memory, payload.message, response)
    state = agent.invoke(
        {"messages": [("user", payload.message)], "hitl_approved": False, "agent_steps": 0},
        config=_config(thread_id),
    )
    response = _response(thread_id, state)
    if response["status"] == "completed" and not _contains_risky_action(state):
        memory.remember_safe_response(payload.message, response["message"])
    audit.write("incident_result", thread_id=thread_id, status=response["status"], source="tools")
    return _track(memory, payload.message, response)


@app.post("/incidents/{thread_id}/approval")
def decide_action(thread_id: str, payload: ApprovalRequest, request: Request):
    agent = request.app.state.agent
    config = _config(thread_id)
    snapshot = agent.get_state(config)
    if not snapshot.values or not snapshot.values.get("messages"):
        raise HTTPException(status_code=404, detail="Incident thread not found")
    state = snapshot.values
    calls = getattr(state["messages"][-1], "tool_calls", []) or []
    if not any(call["name"] == "restart_service" for call in calls):
        raise HTTPException(status_code=409, detail="No restart is awaiting approval")
    if not payload.approved:
        audit.write("action_decided", thread_id=thread_id, approved=False)
        response = {
            "thread_id": thread_id,
            "status": "denied",
            "message": "Action denied; no mutation executed.",
            "source": "operator_decision",
            "usage": summarize_usage(
                state.get("messages", []), settings.openai_model,
                settings.model_input_price_per_million,
                settings.model_output_price_per_million,
            ),
            "flow": _flow(
                ("request", "Incident investigated", "complete"),
                ("approval", "Risky action denied by operator", "blocked"),
                ("answer", "No production change made", "complete"),
            ),
        }
        query = next((str(m.content) for m in state["messages"] if m.type == "human"), "")
        return _track(request.app.state.memory, query, response)

    tool_result = execute_tools(state)
    final = agent.invoke(
        {"messages": tool_result["messages"], "hitl_approved": True}, config=config
    )
    audit.write("action_decided", thread_id=thread_id, approved=True)
    response = _response(thread_id, final)
    query = next((str(m.content) for m in final["messages"] if m.type == "human"), "")
    return _track(request.app.state.memory, query, response)


@app.get("/usage")
def usage_history(
    request: Request, limit: int = 50, x_admin_key: str | None = Header(default=None)
):
    """List recent per-request token usage and estimated cost."""
    if not settings.usage_admin_key:
        raise HTTPException(status_code=503, detail="Usage history is disabled")
    if not x_admin_key or not secrets.compare_digest(x_admin_key, settings.usage_admin_key):
        raise HTTPException(status_code=401, detail="Invalid admin key")
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
    records = request.app.state.memory.recent_usage(limit)
    return {
        "records": records,
        "estimated_total_usd": round(
            sum(record["estimated_cost_usd"] for record in records), 8
        ),
    }


@app.post("/feedback", status_code=201)
def submit_feedback(payload: FeedbackRequest, request: Request):
    memory = request.app.state.memory
    for value in (payload.service_name, payload.symptom, payload.resolution):
        if not inspect_prompt(value).allowed:
            raise HTTPException(status_code=400, detail="Feedback contains unsafe instruction-like content.")
    lesson_id = memory.record(
        Lesson(
            payload.service_name,
            redact_secrets(payload.symptom),
            redact_secrets(payload.resolution),
            payload.rating,
        ),
        approved=payload.operator_approved,
    )
    audit.write("feedback_recorded", feedback_id=lesson_id, approved=payload.operator_approved)
    return {
        "id": lesson_id,
        "learned": payload.operator_approved and payload.rating >= 4,
        "message": "Only operator-approved, highly rated feedback is used in future incidents.",
    }


@app.post("/visuals", status_code=201)
def create_visual(payload: VisualRequest, request: Request):
    """Generate an optional image after a safe DevOps answer is available."""
    for value in (payload.request, payload.answer):
        security = inspect_prompt(value)
        if not security.allowed:
            raise HTTPException(status_code=400, detail=security.reason)
    if not is_devops_request(payload.request):
        raise HTTPException(status_code=400, detail=OUT_OF_SCOPE_MESSAGE)
    generator = request.app.state.visual_generator
    if not generator.available:
        raise HTTPException(
            status_code=503,
            detail="Image generation requires IMAGE_GENERATION_ENABLED=true and OPENAI_API_KEY.",
        )
    try:
        image_url = generator.generate(
            redact_secrets(payload.request), redact_secrets(payload.answer)
        )
    except (RuntimeError, OpenAIError, ValueError) as error:
        logger.exception("visual_generation_failed error_type=%s", type(error).__name__)
        audit.write("visual_generation_failed", error_type=type(error).__name__)
        raise HTTPException(status_code=502, detail="Image generation failed") from error
    audit.write("visual_generated", image_url=image_url)
    return {"status": "completed", "image_url": image_url, "model": settings.image_model}
