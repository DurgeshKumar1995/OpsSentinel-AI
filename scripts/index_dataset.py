"""Index the prepared training split into SafeOps semantic knowledge memory."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import settings
from services.embeddings import create_embedder
from services.memory import LearningStore

DATASET = ROOT / "data/datasets/processed/loghub_train.jsonl"


def index() -> tuple[int, int]:
    store = LearningStore(embedder=create_embedder(settings))
    indexed = skipped = 0
    with DATASET.open(encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            content = (
                f"Log event template: {record['input']}. "
                f"Observed classification: {record['expected']['classification']}. "
                f"Severity: {record['expected']['severity']}."
            )
            if store.index_document(record["source"], content, record["metadata"]):
                indexed += 1
            else:
                skipped += 1
    return indexed, skipped


if __name__ == "__main__":
    indexed, skipped = index()
    print(json.dumps({"indexed": indexed, "skipped": skipped}, indent=2))
