"""Deterministic scope guard for the DevOps-focused agent."""

import re

# Terms are grouped to make the scope guard easy to extend as the DevOps surface
# evolves. Multi-word entries are matched as phrases; single words are matched as
# complete normalized tokens to avoid accidental substring matches.
DEVOPS_TERMS = {
    # DevOps practices and delivery lifecycle
    "devops", "devsecops", "sre", "platform engineering", "gitops",
    "continuous integration", "continuous delivery", "continuous deployment",
    "ci", "cd", "ci cd", "pipeline", "workflow", "build", "test automation",
    "release", "release management", "deploy", "deployment", "rollout",
    "rollback", "blue green", "blue green deployment", "canary", "feature flag",
    "artifact", "artifact repository", "version control", "source control",
    "branching strategy", "trunk based development",

    # Infrastructure, configuration, and automation
    "automation", "automation tool", "configuration", "configuration management",
    "infrastructure", "infrastructure as code", "iac", "provisioning",
    "orchestration", "immutable infrastructure", "desired state", "runbook",
    "playbook", "terraform", "opentofu", "pulumi", "cloudformation", "ansible",
    "chef", "puppet", "saltstack", "vagrant", "packer",

    # Containers and orchestration
    "container", "containers", "containerization", "docker", "dockerfile",
    "docker compose", "kubernetes", "k8s", "kubectl", "kubeconfig", "kubeadm",
    "kubelet", "kube proxy", "api server", "control plane", "cluster", "node",
    "pod", "pods", "crashloopbackoff", "imagepullbackoff", "pending pod",
    "port forward", "rollout status", "context", "resource quota", "limit range",
    "deployment controller", "statefulset", "daemonset", "replicaset", "namespace",
    "ingress", "service mesh", "helm", "helm chart", "kustomize", "operator",
    "openshift", "rancher", "istio", "linkerd", "container registry",

    # Cloud and compute platforms
    "cloud", "cloud computing", "public cloud", "private cloud", "hybrid cloud",
    "multi cloud", "aws", "azure", "gcp", "google cloud", "digitalocean",
    "openstack", "server", "servers", "virtual machine", "vm", "vmware",
    "serverless", "lambda", "cloud run", "function as a service", "faas",
    "production", "staging", "environment", "environments", "sandbox",

    # CI/CD and repository tooling
    "jenkins", "github", "github actions", "gitlab", "gitlab ci", "bitbucket",
    "circleci", "travis ci", "teamcity", "bamboo", "azure devops", "argo cd",
    "argocd", "flux", "tekton", "spinnaker", "nexus", "artifactory",

    # Observability and incident response
    "observability", "monitoring", "logging", "log", "logs", "metric", "metrics",
    "trace", "traces", "tracing", "telemetry", "dashboard", "alert", "alerts",
    "alerting", "incident", "incidents", "incident management", "on call",
    "postmortem", "root cause", "root cause analysis", "rca", "mttr", "mttd",
    "prometheus", "grafana", "datadog", "splunk", "elk", "elasticsearch",
    "logstash", "kibana", "opentelemetry", "new relic", "pagerduty",

    # Reliability, performance, and operations
    "reliability", "availability", "scalability", "resilience", "high availability",
    "fault tolerance", "disaster recovery", "backup", "restore", "capacity planning",
    "autoscaling", "auto scaling", "load balancing", "load balancer", "health check",
    "uptime", "downtime", "latency", "throughput", "timeout", "error", "errors",
    "failure", "outage", "bottleneck", "performance", "restart", "recovery",
    "service level objective", "service level indicator", "service level agreement",
    "slo", "sli", "sla", "error budget", "chaos engineering",

    # Networking, data services, and security operations
    "network", "networking", "dns", "cdn", "proxy", "reverse proxy", "firewall",
    "gateway", "api gateway", "vpc", "subnet", "routing", "tls",
    "ssl", "certificate", "secret management", "secrets management", "vault",
    "iam", "rbac", "least privilege", "supply chain security", "image scanning",
    "vulnerability scanning", "policy as code", "compliance", "database", "cache",
    "message queue", "kafka", "rabbitmq", "redis", "migration", "schema migration",
    "microservice", "microservices", "service", "services",
}

FOLLOW_UP_PATTERNS = (
    r"\b(?:explain|expand|elaborate|clarify|describe)\s+(?:this|that|it|more|point|step|item|number|no)\b",
    r"\b(?:more|additional|further)\s+(?:detail|details|information|info)\b",
    r"\b(?:point|step|item|number|no)\s*(?:no\.?\s*)?\d+\b",
    r"\b\d+(?:st|nd|rd|th)\s+(?:point|step|item)\b",
    r"\bwhat\s+(?:does|do|is|are)\s+(?:that|this|it|those|these)\b",
    r"\b(?:that|this)\s+(?:point|step|item)\b",
    r"\b(?:in|from)\s+(?:the\s+)?(?:(?:previous|above|last|your)\s+)?(?:response|answer)\b",
    r"\b(?:you\s+)?mentioned\s+(?:above|earlier|previously|in\s+(?:the\s+)?(?:response|answer))\b",
)


def is_devops_request(text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9+#]+", " ", text.lower())
    words = set(normalized.split())
    return any(term in normalized if " " in term else term in words for term in DEVOPS_TERMS)


def is_devops_follow_up(text: str, previous_user_messages: list[str]) -> bool:
    """Recognize a referential follow-up only inside an established DevOps thread."""
    if not any(is_devops_request(message) for message in previous_user_messages):
        return False
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return any(re.search(pattern, normalized) for pattern in FOLLOW_UP_PATTERNS)


OUT_OF_SCOPE_MESSAGE = (
    "I can help only with DevOps, CI/CD, deployments, cloud infrastructure, "
    "monitoring, SRE, and production incident questions. Please describe a "
    "deployment, pipeline, infrastructure, or service reliability problem."
)


PROJECT_INFO_PATTERNS = (
    r"\b(?:explain|describe|introduce|tell me about)\s+(?:me\s+)?(?:your\s*)?self\b",
    r"\bwhat\s+(?:are you|is this (?:app|application|project|agent))\b",
    r"\bhow\s+(?:do i|to)\s+use\s+(?:you|this|this (?:app|application|project|agent)|the (?:app|application|project|agent))\b",
    r"\b(?:show|provide|give)(?: me)?\s+(?:the\s+)?(?:steps?|flow|instructions?)\s+(?:to|for|on)\s+(?:use|using)\s+(?:you|this|the (?:app|application|project|agent))\b",
)

PROJECT_IMPROVEMENT_PATTERNS = (
    r"\bwhat\s+(?:will|would|can|could)\s+(?:help|improve|make)\s+(?:this|the)\s+(?:project|app|application|agent)\b",
    r"\bhow\s+(?:can|could|should|to)\s+(?:we\s+)?improve\s+(?:this|the)\s+(?:project|app|application|agent)\b",
    r"\b(?:suggest|recommend|show)(?: me)?\s+(?:some\s+)?improvements?\s+(?:for|to)\s+(?:this|the)\s+(?:project|app|application|agent)\b",
)


def is_project_info_request(text: str) -> bool:
    """Recognize requests asking the agent to introduce this project or its usage."""
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return any(re.search(pattern, normalized) for pattern in PROJECT_INFO_PATTERNS)


def project_info_follow_up_step(text: str, previous_user_messages: list[str]) -> int | None:
    """Resolve numbered guide follow-ups only inside an established project-guide session."""
    if not any(is_project_info_request(message) for message in previous_user_messages):
        return None
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    if not any(re.search(pattern, normalized) for pattern in FOLLOW_UP_PATTERNS):
        return None
    match = re.search(
        r"\b(?:(?:point|step|item|number|no)\s*(?:no\s*)?(\d+)|(\d+)(?:st|nd|rd|th)\s+(?:point|step|item))\b",
        normalized,
    )
    if not match:
        return None
    step = int(match.group(1) or match.group(2))
    return step if 1 <= step <= 7 else None


PROJECT_GUIDE_STEPS = {
    1: (
        "Step 1 — Report: Enter the incident in Incident details. Include the service name, "
        "environment, visible symptoms, approximate start time, and recent deployment or configuration changes."
    ),
    2: (
        "Step 2 — Add evidence: Optionally attach a .log, .txt, or .json file up to 100 KB. "
        "The file is treated as untrusted evidence, checked for safety, and analyzed without enabling production actions."
    ),
    3: (
        "Step 3 — Choose a visual: Enable Create an AI architecture image when a diagram would make "
        "the incident, service dependencies, or proposed flow easier to understand. The text investigation "
        "is returned first; the supporting diagram is generated afterward. Leave it unchecked for a faster, lower-cost response."
    ),
    4: (
        "Step 4 — Investigate: Select Start investigation. OpsSentinel checks prompt safety and DevOps scope, "
        "reviews the session and approved knowledge, gathers permitted evidence, and returns findings and next steps."
    ),
    5: (
        "Step 5 — Review: Read the finding, supporting evidence, recommended next step, processing trace, "
        "model usage, and estimated cost. Treat hypotheses separately from confirmed evidence."
    ),
    6: (
        "Step 6 — Resolve: If a production mutation is proposed, review the service and reason, then approve "
        "or deny it. The action remains paused until an authorized approver explicitly decides."
    ),
    7: (
        "Step 7 — Learn: Rate and correct the resolution. Only highly rated feedback explicitly approved by "
        "an authorized operator is allowed to guide similar future investigations."
    ),
}


def project_guide_step_message(step: int) -> str:
    return PROJECT_GUIDE_STEPS[step]


def is_project_improvement_request(text: str) -> bool:
    """Recognize requests for ways to improve OpsSentinel AI itself."""
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return any(re.search(pattern, normalized) for pattern in PROJECT_IMPROVEMENT_PATTERNS)


def requested_restart_action(text: str) -> dict[str, str] | None:
    """Return an approval-gated restart proposal explicitly requested by an operator."""
    normalized = re.sub(r"[^a-z0-9_-]+", " ", text.lower()).strip()
    requests_restart = bool(re.search(r"\brestart(?:ing)?\b", normalized))
    requests_decision = bool(
        re.search(r"\b(?:propose|proposed|approve|approval|perform|execute|action)\b", normalized)
    )
    targets_live_environment = bool(re.search(r"\b(?:production|prod|live)\b", normalized))
    if not (requests_restart and requests_decision and targets_live_environment):
        return None

    service_patterns = (
        r"restart(?:ing)?\s+(?:the\s+)?([a-z0-9][a-z0-9_-]{1,79})(?:\s+(?:production|prod|live))?",
        r"([a-z0-9][a-z0-9_-]{1,79})\s+(?:service|deployment).{0,40}\brestart",
    )
    service_name = "unspecified-service"
    ignored_targets = {"a", "an", "production", "prod", "live", "service", "deployment"}
    for pattern in service_patterns:
        match = re.search(pattern, normalized)
        if match and match.group(1) not in ignored_targets:
            service_name = match.group(1)
            break
    return {
        "service_name": service_name,
        "reason": "Operator requested a production restart proposal; execution requires explicit approval.",
    }


PROJECT_IMPROVEMENT_MESSAGE = (
    "The most valuable improvements for OpsSentinel AI are:\n\n"
    "1. Real read-only integrations — connect Kubernetes, Prometheus, Grafana, and an authorized log store.\n"
    "2. Identity and access — add user authentication, role-based permissions, tenant isolation, and environment-specific policies.\n"
    "3. Better evaluations — measure diagnostic accuracy, retrieval quality, safety, latency, token usage, and cost before releasing prompt or model changes.\n"
    "4. Shared reliability services — replace in-memory checkpoints and rate limiting with durable shared services for multiple workers.\n"
    "5. Memory governance — show sources, require operator review, and support expiry, correction, and deletion of learned lessons.\n"
    "6. Observability — trace every model, retrieval, tool, approval, and failure step with dashboards and alerts.\n"
    "7. Safe remediation previews — provide dry-run plans and impact summaries before requesting approval.\n\n"
    "Best next step: implement an authenticated, read-only Kubernetes or Prometheus adapter and evaluate it against versioned incident scenarios."
)


PROJECT_INFO_MESSAGE = (
    "I’m OpsSentinel AI, a human-supervised DevOps incident-response project. "
    "I help investigate deployments, CI/CD pipelines, cloud infrastructure, monitoring alerts, "
    "logs, SRE concerns, and production incidents. I check available evidence, explain findings, "
    "and pause for your approval before any risky action.\n\n"
    "How to use this project:\n"
    "1. Report — Describe your issue in Incident details. Include the service, environment, "
    "symptoms, time window, and recent changes when known.\n"
    "2. Add evidence — Optionally upload a .log, .txt, or .json file (maximum 100 KB).\n"
    "3. Choose a visual — Select Create an AI architecture image when you want a supporting diagram.\n"
    "4. Investigate — Select Start investigation. The project checks security and scope, reviews "
    "available evidence and approved incident memory, then uses a safe local tool or the AI workflow.\n"
    "5. Review — Read the finding, evidence, recommended next step, usage details, and processing flow.\n"
    "6. Resolve — If a risky action such as a restart is proposed, approve or deny it. Nothing risky "
    "runs without explicit approval.\n"
    "7. Learn — Submit operator-approved feedback. Only approved, highly rated resolutions can guide "
    "similar future incidents.\n\n"
    "Overall flow: Report → Security and scope checks → Evidence and memory review → Investigation → "
    "Human approval when required → Result → Reviewed learning.\n\n"
    "Example: ‘Check payment-gateway logs for the last 15 minutes and explain any errors.’"
)
