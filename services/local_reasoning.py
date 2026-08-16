"""Zero-LLM fast paths for simple, read-only operational checks."""

import re

from config.settings import settings
from services.tools import fetch_logs

READ_ONLY_TERMS = ("log", "health", "status", "check", "monitor")
COMPLEX_TERMS = (
    "architecture", "design", "diagram", "pipeline", "ci/cd", "github actions",
    "argo cd", "canary", "rollback", "container registry", "security controls",
    "deployment flow", "production-ready", "strategy", "explain",
)


def try_local_readonly_answer(query: str) -> dict | None:
    """Answer an unambiguous service check locally; return None for LLM routing."""
    normalized = query.lower()
    # Long-form plans and designs can contain words such as "monitoring" and a
    # service name, but they are not simple health checks.
    if len(query.split()) > 35 or any(term in normalized for term in COMPLEX_TERMS):
        return None
    if not any(term in normalized for term in READ_ONLY_TERMS):
        return None
    service = next(
        (name for name in settings.service_allowlist if name.lower() in normalized), None
    )
    if not service:
        return None
    window_match = re.search(r"\b(\d{1,3})\s*(?:minute|min)s?\b", normalized)
    window = min(int(window_match.group(1)), 120) if window_match else 15
    try:
        evidence = fetch_logs(service, window)
    except (ValueError, NotImplementedError):
        return None
    logs = [str(item) for item in evidence.get("logs", [])]
    unhealthy = any(
        marker in " ".join(logs).lower()
        for marker in ("error", "timeout", "failed", "unhealthy", "500")
    )
    if unhealthy:
        message = (
            f"Finding: {service} is unhealthy in the last {window} minutes.\n\n"
            f"Evidence: {'; '.join(logs)}\n\n"
            "Recommended next step: inspect the failing dependency and connection settings. "
            "No production change was made; any restart or mutation still requires approval."
        )
    else:
        message = (
            f"Finding: {service} is healthy in the last {window} minutes.\n\n"
            f"Evidence: {'; '.join(logs)}\n\n"
            "Recommended next step: continue monitoring. No production change was made."
        )
    return {"message": message, "service": service, "window_minutes": window}
