"""Operator identity and role enforcement for API-key or trusted OIDC-proxy auth."""

import hashlib
import secrets
from dataclasses import dataclass

from fastapi import HTTPException, Request

from config.settings import settings


@dataclass(frozen=True)
class Principal:
    subject: str
    roles: frozenset[str]
    auth_method: str

    @property
    def owner_id(self) -> str:
        return hashlib.sha256(self.subject.encode()).hexdigest()


def principal_from_request(request: Request) -> Principal:
    """Resolve a caller. OIDC claims are accepted only from a shared-secret ingress."""
    if settings.app_env != "production" and not request.headers.get("X-Operator-Key"):
        return Principal("development-operator", frozenset({"admin", "approver", "investigator"}), "development")

    if settings.auth_mode == "oidc_proxy":
        proxy_secret = request.headers.get("X-OIDC-Proxy-Secret")
        if not proxy_secret or not settings.oidc_proxy_secret or not secrets.compare_digest(
            proxy_secret, settings.oidc_proxy_secret
        ):
            raise HTTPException(status_code=401, detail="Trusted identity proxy required")
        subject = request.headers.get("X-Authenticated-User", "").strip()
        roles = frozenset(
            role.strip().lower() for role in request.headers.get("X-User-Roles", "").split(",")
            if role.strip()
        )
        if not subject:
            raise HTTPException(status_code=401, detail="Authenticated user identity required")
        return Principal(subject, roles, "oidc_proxy")

    supplied = request.headers.get("X-Operator-Key")
    if not supplied or not settings.operator_api_key or not secrets.compare_digest(
        supplied, settings.operator_api_key
    ):
        raise HTTPException(status_code=401, detail="Valid operator credentials are required")
    subject = f"api-key:{hashlib.sha256(supplied.encode()).hexdigest()}"
    return Principal(subject, frozenset({"admin", "approver", "investigator"}), "api_key")


def require_role(principal: Principal, *allowed: str) -> None:
    if not principal.roles.intersection(allowed):
        raise HTTPException(status_code=403, detail="Your role does not permit this operation")
