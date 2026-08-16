# Roadmap

OpsSentinel AI is a reference implementation today. The roadmap focuses on making
its agent loop measurable, extensible, and safe enough for realistic integrations.

## Good first contributions

- Improve setup errors and the local developer experience.
- Add accessibility and responsive-layout tests for the web interface.
- Expand deterministic evaluation cases for routing, injection resistance, memory,
  redaction, token limits, and approval boundaries.
- Add documentation examples for custom read-only tools and dataset adapters.

## Near term

- Add an offline evaluation runner with versioned datasets and quality, safety,
  latency, token, and cost reports.
- Add authenticated, read-only adapters for Kubernetes, Prometheus, and log stores.
- Add pluggable checkpoint and rate-limit backends for multi-worker deployments.
- Add OpenTelemetry traces and structured metrics for every agent and tool step.
- Add memory provenance, expiry, deletion, and conflict-resolution controls.

## Later

- Add policy-based RBAC and per-environment tool allowlists.
- Add sandboxed remediation plans with dry-run previews and approval workflows.
- Add replayable incident simulations and model/prompt comparison dashboards.
- Publish a versioned adapter SDK and deployment reference architecture.

## Non-goals

- Autonomous production changes without human approval.
- Treating unreviewed model output as learned truth.
- Shipping mock infrastructure tools as production integrations.

Please open a feature request before starting a large change so scope, safety, and
evaluation expectations can be agreed on early.
