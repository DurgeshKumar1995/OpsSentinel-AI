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


def is_project_info_request(text: str) -> bool:
    """Recognize requests asking the agent to introduce this project or its usage."""
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return any(re.search(pattern, normalized) for pattern in PROJECT_INFO_PATTERNS)


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
