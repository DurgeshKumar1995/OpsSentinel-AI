"""Index the prepared training split into OpsSentinel AI semantic knowledge memory."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import settings
from services.embeddings import create_embedder
from services.memory import LearningStore

LOG_DATASET = ROOT / "data/datasets/processed/loghub_train.jsonl"
DEVOPS_DATASET = ROOT / "data/datasets/devops_knowledge.jsonl"


def records():
    for path in (LOG_DATASET, DEVOPS_DATASET):
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                yield json.loads(line)


def document_content(record: dict) -> str:
    if "expected" in record:
        return (
            f"Log event template: {record['input']}. "
            f"Observed classification: {record['expected']['classification']}. "
            f"Severity: {record['expected']['severity']}."
        )
    return (
        f"DevOps topic: {record['topic']}. Scenario: {record['title']}. "
        f"Symptoms: {'; '.join(record['symptoms'])}. "
        f"Likely causes: {'; '.join(record['likely_causes'])}. "
        f"Safe diagnostics: {'; '.join(record['diagnostics'])}. "
        f"Safety note: {record['safety']}"
    )


def index() -> tuple[int, int]:
    store = LearningStore(embedder=create_embedder(settings))
    indexed = skipped = 0
    for record in records():
        metadata = record.get("metadata")
        if metadata is None:
            metadata = {
                "id": record["id"],
                "topic": record["topic"],
                "license": "MIT",
            }
        if store.index_document(record["source"], document_content(record), metadata):
            indexed += 1
        else:
            skipped += 1
    return indexed, skipped


if __name__ == "__main__":
    indexed, skipped = index()
    print(json.dumps({"indexed": indexed, "skipped": skipped}, indent=2))
