"""Deterministic scope guard for the DevOps-focused agent."""

import re

DEVOPS_TERMS = {
    "deploy", "deployment", "release", "rollback", "rollout", "pipeline",
    "ci", "cd", "devops", "sre", "build", "artifact", "docker", "container",
    "kubernetes", "k8s", "helm", "terraform", "ansible", "jenkins", "github",
    "gitlab", "azure", "aws", "gcp", "cloud", "cluster", "pod", "service",
    "server", "production", "staging", "environment", "logs", "monitoring",
    "alert", "incident", "latency", "timeout", "error", "health", "restart",
    "database", "network", "dns", "load balancer", "autoscaling", "workflow",
}


def is_devops_request(text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9+#]+", " ", text.lower())
    words = set(normalized.split())
    return any(term in normalized if " " in term else term in words for term in DEVOPS_TERMS)


OUT_OF_SCOPE_MESSAGE = (
    "I can help only with DevOps, CI/CD, deployments, cloud infrastructure, "
    "monitoring, SRE, and production incident questions. Please describe a "
    "deployment, pipeline, infrastructure, or service reliability problem."
)
