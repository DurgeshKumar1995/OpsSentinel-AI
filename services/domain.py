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
    "gateway", "api gateway", "load balancer", "vpc", "subnet", "routing", "tls",
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
