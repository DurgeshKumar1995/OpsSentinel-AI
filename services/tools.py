"""Tool adapters. Mock mode is explicit and production startup forbids it."""

from typing import Any

from config.settings import settings


def _validate_service(service_name: str) -> None:
    if service_name not in settings.service_allowlist:
        raise ValueError(f"Service '{service_name}' is not in ALLOWED_SERVICES")


def fetch_logs(service_name: str, window_minutes: int) -> dict[str, Any]:
    """Mock execution to fetch logs from a monitoring service."""
    _validate_service(service_name)
    if settings.tool_mode != "mock":
        raise NotImplementedError("Configure a live monitoring adapter before using TOOL_MODE=live")
    if service_name == "auth-service":
        return {"logs": ["500 Internal Server Error: Database Connection Timeout at /login"]}
    return {"logs": ["200 OK: All system checks normal"]}

def restart_service(service_name: str, reason: str) -> dict[str, Any]:
    """Mock execution to restart a microservice instance."""
    _validate_service(service_name)
    if settings.tool_mode != "mock":
        raise NotImplementedError("Configure a live orchestration adapter before using TOOL_MODE=live")
    return {
        "status": "SUCCESS",
        "message": f"Service '{service_name}' successfully restarted. Reason: {reason}"
    }
