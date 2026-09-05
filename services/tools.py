"""Validated mock or authenticated HTTP adapters for operational tools."""

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config.settings import settings


def _validate_service(service_name: str) -> None:
    if service_name not in settings.service_allowlist:
        raise ValueError(f"Service '{service_name}' is not in ALLOWED_SERVICES")


def _live_request(url: str, method: str, body: dict | None = None, request_id: str | None = None) -> dict:
    headers = {"Accept": "application/json", "Authorization": f"Bearer {settings.tool_api_token}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if request_id:
        headers["Idempotency-Key"] = request_id
    try:
        with urlopen(
            Request(url, data=data, headers=headers, method=method),
            timeout=settings.tool_timeout_seconds,
        ) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError(f"Operational API returned HTTP {response.status}")
            value = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError("Operational API request failed") from error
    if not isinstance(value, dict):
        raise RuntimeError("Operational API returned an invalid response")
    return value


def fetch_logs(service_name: str, window_minutes: int) -> dict[str, Any]:
    """Mock execution to fetch logs from a monitoring service."""
    _validate_service(service_name)
    if settings.tool_mode == "live":
        if not settings.monitoring_api_url:
            raise RuntimeError("Live monitoring API is not configured")
        query = urlencode({"service": service_name, "window_minutes": window_minutes})
        return _live_request(f"{settings.monitoring_api_url.rstrip('/')}?{query}", "GET")
    if service_name == "auth-service":
        return {"logs": ["500 Internal Server Error: Database Connection Timeout at /login"]}
    return {"logs": ["200 OK: All system checks normal"]}

def restart_service(service_name: str, reason: str, request_id: str | None = None) -> dict[str, Any]:
    """Mock execution to restart a microservice instance."""
    _validate_service(service_name)
    if settings.tool_mode == "live":
        if not settings.orchestration_api_url:
            raise RuntimeError("Live orchestration API is not configured")
        return _live_request(
            settings.orchestration_api_url,
            "POST",
            {"service_name": service_name, "reason": reason},
            request_id=request_id,
        )
    return {
        "status": "SUCCESS",
        "message": f"Service '{service_name}' successfully restarted. Reason: {reason}"
    }
