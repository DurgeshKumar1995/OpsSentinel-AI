"""OpsSentinel AI HTTP application."""

import base64
import hashlib
import hmac
import json
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessage
from openai import OpenAIError
from pydantic import BaseModel, Field

from config.settings import settings
from graph.workflow import get_graph_builder
from services.agent_logic import analyze_uploaded_logs
from services.audit import AuditLogger
from services.auth import Principal, principal_from_request, require_role
from services.domain import (
    OUT_OF_SCOPE_MESSAGE,
    PROJECT_IMPROVEMENT_MESSAGE,
    PROJECT_INFO_MESSAGE,
    is_devops_follow_up,
    is_devops_request,
    is_project_improvement_request,
    is_project_info_request,
    project_guide_step_message,
    project_info_follow_up_step,
    requested_restart_action,
)
from services.embeddings import create_embedder
from services.local_reasoning import try_local_readonly_answer
from services.memory import LearningStore, Lesson
from services.security import inspect_prompt, redact_secrets
from services.tools import restart_service
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
    application.state.agent = get_graph_builder().compile()
    application.state.embedder = create_embedder(settings)
    application.state.memory = LearningStore(embedder=application.state.embedder)
    application.state.visual_generator = VisualGenerator(settings)
    logger.info("application_started env=%s tool_mode=%s", settings.app_env, settings.tool_mode)
    yield
    logger.info("application_stopped")


class IncidentRequest(BaseModel):
    message: str = Field(min_length=3, max_length=settings.max_input_chars)
    thread_id: str | None = Field(default=None, min_length=3, max_length=100)


class UploadedLogRequest(BaseModel):
    message: str = Field(min_length=3, max_length=settings.max_input_chars)
    filename: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=settings.max_uploaded_log_chars)
    thread_id: str | None = Field(default=None, min_length=3, max_length=100)


class ApprovalRequest(BaseModel):
    approved: bool
    approval_token: str = Field(min_length=20, max_length=500)


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


APPROVAL_SECRET = (
    settings.approval_signing_secret.encode("utf-8")
    if settings.approval_signing_secret
    else secrets.token_bytes(32)
)


def _approval_token(thread_id: str, action: dict) -> str:
    """Bind a capability token to one exact pending action and incident thread."""
    payload = json.dumps(
        {
            "thread_id": thread_id, "id": action.get("id"),
            "name": action.get("name"), "args": action.get("args", {}),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(APPROVAL_SECRET, payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(signature).decode().rstrip("=")


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
        "approval_token": _approval_token(thread_id, pending) if pending else None,
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


def _track(
    memory: LearningStore, query: str, response: dict, owner_id: str | None = None
) -> dict:
    """Attach zero usage when no model ran and persist the request total."""
    response.setdefault("usage", zero_usage())
    memory.record_usage(
        response["thread_id"], redact_secrets(query),
        response.get("source", "workflow"), response["usage"]
    )
    effective_owner = owner_id or (
        hashlib.sha256(settings.operator_api_key.encode("utf-8")).hexdigest()
        if settings.app_env == "production" and settings.operator_api_key
        else "development-operator"
    )
    memory.record_session(effective_owner, redact_secrets(query), response)
    return response


def _contains_risky_action(state: dict) -> bool:
    return any(
        call.get("name") == "restart_service"
        for message in state.get("messages", [])
        for call in (getattr(message, "tool_calls", []) or [])
    )


def _rate_limit(memory: LearningStore, principal: Principal, scope: str) -> None:
    if settings.app_env != "production":
        return
    if not memory.allow_request(
        principal.owner_id, scope, settings.rate_limit_requests, settings.rate_limit_window_seconds
    ):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait and try again.")


app = FastAPI(
    title="OpsSentinel AI Incident Agent",
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


@app.get("/generated/{filename}", include_in_schema=False)
def generated_image(filename: str, request: Request):
    """Serve an image from the configured output directory without allowing traversal."""
    principal = principal_from_request(request)
    require_role(principal, "investigator", "approver", "admin")
    if not filename.startswith("devops-visual-") or not filename.endswith(".png"):
        raise HTTPException(status_code=404, detail="Image not found")
    image_path = settings.generated_image_dir / filename
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(image_path, media_type="image/png")


@app.get("/ready")
def readiness(request: Request):
    try:
        request.app.state.memory.relevant("readiness", limit=1)
    except OSError as error:
        raise HTTPException(status_code=503, detail="Persistence unavailable") from error
    checks = {"persistence": "ready", "tool_mode": settings.tool_mode}
    if settings.app_env == "production":
        checks["monitoring_adapter"] = "configured" if settings.monitoring_api_url else "missing"
        checks["orchestration_adapter"] = "configured" if settings.orchestration_api_url else "missing"
        if "missing" in checks.values():
            raise HTTPException(status_code=503, detail={"status": "not_ready", "checks": checks})
    return {"status": "ready", "checks": checks}


@app.post("/incidents")
def create_incident(
    payload: IncidentRequest,
    request: Request,
):
    agent = request.app.state.agent
    memory = request.app.state.memory
    principal = principal_from_request(request)
    require_role(principal, "investigator", "approver", "admin")
    owner_id = principal.owner_id
    _rate_limit(memory, principal, "incidents")
    client_key = request.client.host if request.client else "unknown"
    thread_id = payload.thread_id or str(uuid4())
    audit.write(
        "incident_received", thread_id=thread_id, client=client_key,
        actor=principal.subject, auth_method=principal.auth_method,
    )
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
        }, owner_id)
    if is_project_improvement_request(payload.message):
        audit.write("incident_completed", thread_id=thread_id, source="project_improvement")
        return _track(memory, payload.message, {
            "thread_id": thread_id,
            "status": "completed",
            "message": PROJECT_IMPROVEMENT_MESSAGE,
            "pending_action": None,
            "source": "project_improvement",
            "learned": False,
            "usage": zero_usage(),
            "flow": _flow(
                ("request", "Improvement question received", "complete"),
                ("guard", "Security check completed", "complete"),
                ("review", "Project priorities reviewed", "complete"),
                ("ai", "External AI call skipped", "skipped"),
                ("answer", "Prioritized improvements returned", "complete"),
            ),
        }, owner_id)
    if is_project_info_request(payload.message):
        audit.write("incident_completed", thread_id=thread_id, source="project_info")
        return _track(memory, payload.message, {
            "thread_id": thread_id,
            "status": "completed",
            "message": PROJECT_INFO_MESSAGE,
            "pending_action": None,
            "source": "project_info",
            "learned": False,
            "usage": zero_usage(),
            "flow": _flow(
                ("request", "Request received", "complete"),
                ("guard", "Security check completed", "complete"),
                ("route", "Project introduction selected", "complete"),
                ("ai", "External AI call skipped", "skipped"),
                ("answer", "Project overview and usage returned", "complete"),
            ),
        }, owner_id)
    previous_user_messages = (
        [turn[0] for turn in memory.session_context(thread_id, owner_id)]
        if payload.thread_id else []
    )
    guide_step = project_info_follow_up_step(payload.message, previous_user_messages)
    if guide_step:
        audit.write(
            "incident_completed", thread_id=thread_id, source="project_info_follow_up",
            guide_step=guide_step, actor=principal.subject,
        )
        return _track(memory, payload.message, {
            "thread_id": thread_id,
            "status": "completed",
            "message": project_guide_step_message(guide_step),
            "pending_action": None,
            "source": "project_info_follow_up",
            "learned": False,
            "usage": zero_usage(),
            "flow": _flow(
                ("request", "Follow-up received", "complete"),
                ("context", "Project guide session restored", "complete"),
                ("route", f"Guide step {guide_step} selected", "complete"),
                ("ai", "External AI call skipped", "skipped"),
                ("answer", "Step explanation returned", "complete"),
            ),
        }, owner_id)
    contextual_follow_up = is_devops_follow_up(payload.message, previous_user_messages)
    if not is_devops_request(payload.message) and not contextual_follow_up:
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
        }, owner_id)
    requested_action = requested_restart_action(payload.message)
    if requested_action:
        pending_message = AIMessage(
            content=(
                "A production restart has been prepared as a proposal only. No action has run. "
                "Review the target and reason below, then explicitly approve or deny the action."
            ),
            tool_calls=[{
                "name": "restart_service",
                "args": requested_action,
                "id": f"restart-{uuid4()}",
                "type": "tool_call",
            }],
        )
        state = {
            "messages": [("user", payload.message), pending_message],
            "hitl_approved": False,
            "agent_steps": 1,
        }
        response = _response(thread_id, state)
        response["source"] = "human_approval_gate"
        memory.register_action(thread_id, owner_id, response["pending_action"])
        audit.write(
            "action_approval_requested", thread_id=thread_id, action_id=pending_message.tool_calls[0]["id"],
            actor=principal.subject, auth_method=principal.auth_method, **requested_action,
        )
        return _track(memory, payload.message, response, owner_id)
    # A referential follow-up must be answered from this thread's conversation,
    # never from a standalone response cached for similar wording.
    recalled = None if contextual_follow_up else memory.recall_safe_response(payload.message)
    if recalled is None:
        recalled = None if contextual_follow_up else memory.recall_similar_response(
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
        }, owner_id)
    local_answer = None if contextual_follow_up else try_local_readonly_answer(payload.message)
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
        return _track(memory, payload.message, response, owner_id)
    try:
        history = []
        for prior_query, prior_response in memory.session_context(thread_id, owner_id):
            history.extend([("user", prior_query), ("assistant", prior_response)])
        state = agent.invoke({
            "messages": [*history, ("user", payload.message)],
            "hitl_approved": False,
            "agent_steps": 0,
        })
    except (OpenAIError, OSError, TimeoutError) as error:
        logger.exception("incident_ai_failed error_type=%s", type(error).__name__)
        audit.write("incident_ai_failed", thread_id=thread_id, error_type=type(error).__name__)
        raise HTTPException(status_code=502, detail="The AI service is temporarily unavailable") from error
    response = _response(thread_id, state)
    if response.get("pending_action"):
        memory.register_action(thread_id, owner_id, response["pending_action"])
    # Model-generated answers remain untrusted until reviewed by an operator.
    audit.write("incident_result", thread_id=thread_id, status=response["status"], source="tools")
    return _track(memory, payload.message, response, owner_id)


@app.post("/incidents/log-analysis")
def analyze_log_file(
    payload: UploadedLogRequest,
    request: Request,
):
    """Analyze a user-selected text log without storing the file or enabling actions."""
    memory = request.app.state.memory
    principal = principal_from_request(request)
    require_role(principal, "investigator", "approver", "admin")
    owner_id = principal.owner_id
    _rate_limit(memory, principal, "log-analysis")
    filename = Path(payload.filename).name
    if filename != payload.filename or Path(filename).suffix.lower() not in {".log", ".txt", ".json"}:
        raise HTTPException(
            status_code=400, detail="Upload a .log, .txt, or .json text file."
        )
    security = inspect_prompt(payload.message)
    if not security.allowed:
        raise HTTPException(status_code=400, detail=security.reason)
    thread_id = payload.thread_id or str(uuid4())
    safe_content = redact_secrets(payload.content.replace("\x00", ""))
    try:
        result = analyze_uploaded_logs(
            redact_secrets(payload.message), filename, safe_content
        )
    except (OpenAIError, OSError, TimeoutError) as error:
        logger.exception("log_analysis_ai_failed error_type=%s", type(error).__name__)
        audit.write("log_analysis_ai_failed", thread_id=thread_id, error_type=type(error).__name__)
        raise HTTPException(status_code=502, detail="The AI service is temporarily unavailable") from error
    # Raw logs are not retained; the redacted request and safe result are stored as a turn.
    response = {
        "thread_id": thread_id,
        "status": "completed",
        "message": getattr(result, "content", ""),
        "pending_action": None,
        "source": "uploaded_log",
        "learned": False,
        "usage": summarize_usage(
            [result], settings.openai_model,
            settings.model_input_price_per_million,
            settings.model_output_price_per_million,
        ),
        "flow": _flow(
            ("request", "Log file received", "complete"),
            ("guard", "File type, size, and security checked", "complete"),
            ("evidence", "Uploaded log evidence analyzed", "complete"),
            ("actions", "Production actions disabled", "skipped"),
            ("answer", "Findings and next steps returned", "complete"),
        ),
    }
    audit.write(
        "uploaded_log_analyzed", thread_id=thread_id, filename=filename,
        actor=principal.subject, auth_method=principal.auth_method,
    )
    return _track(memory, payload.message, response, owner_id)


@app.post("/incidents/{thread_id}/approval")
def decide_action(thread_id: str, payload: ApprovalRequest, request: Request):
    memory = request.app.state.memory
    principal = principal_from_request(request)
    require_role(principal, "approver", "admin")
    owner_id = principal.owner_id
    _rate_limit(memory, principal, "approval")
    action = memory.latest_action(thread_id, owner_id)
    if not action or action["action_name"] != "restart_service":
        raise HTTPException(status_code=409, detail="No restart is awaiting approval")
    pending = {
        "id": action["action_id"], "name": action["action_name"], "args": action["action_args"]
    }
    expected_token = _approval_token(thread_id, pending)
    if not secrets.compare_digest(payload.approval_token, expected_token):
        audit.write(
            "action_decision_rejected", thread_id=thread_id, reason="invalid_capability",
            actor=principal.subject,
        )
        raise HTTPException(status_code=403, detail="Invalid or expired approval capability")
    action_id = action["action_id"]
    if action["status"] in {"completed", "denied"}:
        return action["result"]
    if action["status"] == "executing":
        raise HTTPException(status_code=409, detail="This action is already being executed")
    if action["status"] == "failed":
        raise HTTPException(status_code=409, detail="This action already failed; create a new proposal")
    if not payload.approved:
        audit.write(
            "action_decided", thread_id=thread_id, action_id=action_id, approved=False,
            actor=principal.subject, auth_method=principal.auth_method,
        )
        response = {
            "thread_id": thread_id,
            "status": "denied",
            "message": "Action denied; no mutation executed.",
            "source": "operator_decision",
            "usage": summarize_usage(
                [], settings.openai_model,
                settings.model_input_price_per_million,
                settings.model_output_price_per_million,
            ),
            "flow": _flow(
                ("request", "Incident investigated", "complete"),
                ("approval", "Risky action denied by operator", "blocked"),
                ("answer", "No production change made", "complete"),
            ),
        }
        context = memory.session_context(thread_id, owner_id, limit=1)
        query = context[-1][0] if context else "Denied action"
        response = _track(memory, query, response, owner_id)
        memory.finish_action(action_id, owner_id, "denied", response)
        return response

    if not memory.claim_action(action_id, owner_id):
        current = memory.get_action(action_id, owner_id)
        if current and current["status"] == "completed":
            return current["result"]
        raise HTTPException(status_code=409, detail="This action has already been decided")
    try:
        raw_result = restart_service(**action["action_args"], request_id=action_id)
    except (ValueError, RuntimeError, OSError, TimeoutError) as error:
        failure = {
            "thread_id": thread_id,
            "status": "action_failed",
            "message": "The approved action was rejected or failed; no success was recorded.",
            "pending_action": None,
            "source": "approved_tool",
            "learned": False,
            "tool_result": {"error": type(error).__name__},
            "flow": _flow(
                ("request", "Incident investigated", "complete"),
                ("approval", "Action approved by operator", "complete"),
                ("action", "Approved action failed", "blocked"),
                ("answer", "Failure recorded for review", "complete"),
            ),
        }
        memory.finish_action(action_id, owner_id, "failed", failure)
        audit.write("action_failed", thread_id=thread_id, action_id=action_id)
        raise HTTPException(status_code=502, detail=failure["message"]) from error
    audit.write(
        "action_decided", thread_id=thread_id, action_id=action_id, approved=True,
        actor=principal.subject, auth_method=principal.auth_method,
    )
    response = {
        "thread_id": thread_id,
        "status": "completed",
        "message": "The operator-approved action completed successfully.",
        "pending_action": None,
        "source": "approved_tool",
        "learned": False,
        "tool_result": raw_result,
        "flow": _flow(
            ("request", "Incident investigated", "complete"),
            ("approval", "Action approved by operator", "complete"),
            ("action", "Approved action executed once", "complete"),
            ("answer", "Verified tool result returned", "complete"),
        ),
    }
    context = memory.session_context(thread_id, owner_id, limit=1)
    query = context[-1][0] if context else "Approved action"
    response = _track(memory, query, response, owner_id)
    memory.finish_action(action_id, owner_id, "completed", response)
    return response


@app.get("/sessions")
def list_incident_sessions(
    request: Request,
    limit: int = 30,
):
    """Return redacted durable session summaries owned by this operator."""
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
    principal = principal_from_request(request)
    require_role(principal, "investigator", "approver", "admin")
    return {"sessions": request.app.state.memory.list_sessions(principal.owner_id, limit)}


@app.get("/sessions/{thread_id}")
def get_incident_session(thread_id: str, request: Request, limit: int = 30):
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
    principal = principal_from_request(request)
    require_role(principal, "investigator", "approver", "admin")
    turns = request.app.state.memory.session_turns(thread_id, principal.owner_id, limit)
    if not turns:
        raise HTTPException(status_code=404, detail="Incident session not found")
    return {"thread_id": thread_id, "turns": turns}


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
def submit_feedback(
    payload: FeedbackRequest,
    request: Request,
):
    memory = request.app.state.memory
    principal = principal_from_request(request)
    require_role(principal, "investigator", "approver", "admin")
    _rate_limit(memory, principal, "feedback")
    for value in (payload.service_name, payload.symptom, payload.resolution):
        if not inspect_prompt(value).allowed:
            raise HTTPException(status_code=400, detail="Feedback contains unsafe instruction-like content.")
    if payload.operator_approved:
        require_role(principal, "approver", "admin")
        if settings.auth_mode == "api_key" and settings.operator_api_key:
            supplied_key = request.headers.get("X-Operator-Key")
            if not supplied_key or not secrets.compare_digest(
                supplied_key, settings.operator_api_key
            ):
                raise HTTPException(status_code=403, detail="Valid operator credentials are required")
    lesson_id = memory.record(
        Lesson(
            payload.service_name,
            redact_secrets(payload.symptom),
            redact_secrets(payload.resolution),
            payload.rating,
        ),
        approved=payload.operator_approved,
    )
    audit.write(
        "feedback_recorded", feedback_id=lesson_id, approved=payload.operator_approved,
        actor=principal.subject, auth_method=principal.auth_method,
    )
    return {
        "id": lesson_id,
        "learned": payload.operator_approved and payload.rating >= 4,
        "message": "Only operator-approved, highly rated feedback is used in future incidents.",
    }


@app.post("/visuals", status_code=201)
def create_visual(payload: VisualRequest, request: Request):
    """Generate an optional image after a safe DevOps answer is available."""
    principal = principal_from_request(request)
    require_role(principal, "investigator", "approver", "admin")
    _rate_limit(request.app.state.memory, principal, "visuals")
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
    audit.write(
        "visual_generated", image_url=image_url,
        actor=principal.subject, auth_method=principal.auth_method,
    )
    return {"status": "completed", "image_url": image_url, "model": settings.image_model}
