## Summary

Explain the problem and the focused change that solves it.

## Validation

- [ ] `python -m unittest discover -v -p 'test*.py'`
- [ ] `ruff check .`
- [ ] Tests or evaluation cases cover changed behavior.

## Agent and safety review

- [ ] This change does not expose secrets, private logs, databases, or generated artifacts.
- [ ] New tool inputs are allowlisted and schema-validated.
- [ ] Mutating operations remain auditable and require explicit human approval.
- [ ] Prompt, routing, retrieval, or memory changes include regression cases.
- [ ] Documentation and `.env.example` were updated when configuration changed.

## Screenshots or traces

Add sanitized evidence when the UI or agent flow changed. Remove credentials and private data.
