# Security policy

## Supported versions

Security fixes are applied to the latest version on the default branch.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use GitHub's private
security advisory feature for this repository. Include reproduction steps,
affected endpoints, impact, and any suggested mitigation. Please allow a
reasonable remediation period before public disclosure.

## Deployment warning

OpsSentinel AI is a reference implementation, not a production control plane. Its
included monitoring and restart adapters are mocks. Before connecting a fork to
real infrastructure, add authenticated tool adapters, user authentication and
RBAC, tenant isolation, a shared durable checkpoint store, immutable audit
retention, TLS, and a managed secrets service.

Never commit `.env`, API keys, incident logs, prompt history, SQLite databases,
audit logs, or generated images. Rotate any credential that has appeared in a
terminal transcript, container configuration, screenshot, issue, or commit.

The `/usage` endpoint requires `X-Admin-Key` and is disabled when
`USAGE_ADMIN_KEY` is not configured. Treat its results as private because they
contain redacted user prompts and usage metadata.

Operator-approved feedback requires `X-Operator-Key`. Pending tool actions use a
capability bound to the exact thread, tool name, and arguments. These controls reduce
unauthorized mutation and memory poisoning but do not replace user authentication,
RBAC, or tenant isolation for a real deployment.
