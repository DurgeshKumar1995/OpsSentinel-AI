# Contributing

Thank you for improving SafeOps.

## Development

1. Create a virtual environment with Python 3.11 or newer.
2. Install `requirements-dev.txt` and copy `.env.example` to `.env`.
3. Keep `TOOL_MODE=mock` for local development and tests.
4. Make focused changes with tests for behavior and safety boundaries.
5. Run the checks below before opening a pull request.

```bash
python -m unittest discover -v -p 'test*.py'
ruff check .
pip-audit -r requirements.txt
```

Never include secrets, proprietary logs, customer data, generated databases, or
audit output in a pull request. New mutating tools must be allowlisted,
schema-validated, idempotent, auditable, and protected by explicit human
approval. Changes to prompts, routing, memory, or tool behavior should include
evaluation cases demonstrating that safety and answer quality did not regress.
