"""Convert Loghub samples into deterministic JSONL splits for SafeOps."""

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/datasets/loghub/raw"
OUTPUT = ROOT / "data/datasets/processed"
SOURCES = {
    "hdfs": RAW / "HDFS_2k.log_structured.csv",
    "bgl": RAW / "BGL_2k.log_structured.csv",
}


def split_for(identifier: str) -> str:
    bucket = int(hashlib.sha256(identifier.encode()).hexdigest()[:8], 16) % 100
    return "train" if bucket < 70 else "validation" if bucket < 85 else "test"


def convert() -> dict[str, int]:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    handles = {
        split: (OUTPUT / f"loghub_{split}.jsonl").open("w", encoding="utf-8")
        for split in ("train", "validation", "test")
    }
    counts = {split: 0 for split in handles}
    try:
        for source, path in SOURCES.items():
            with path.open(encoding="utf-8", newline="") as stream:
                for row in csv.DictReader(stream):
                    identifier = f"{source}:{row['LineId']}"
                    split = split_for(identifier)
                    label = (
                        "anomaly" if source == "bgl" and row.get("Label") != "-"
                        else "normal"
                    )
                    record = {
                        "id": identifier,
                        "source": f"loghub/{source}",
                        "input": row["EventTemplate"],
                        "expected": {
                            "classification": label,
                            "severity": row.get("Level", "UNKNOWN"),
                            "action": "diagnose_only",
                            "approval_required": False,
                        },
                        "metadata": {
                            "event_id": row["EventId"],
                            "component": row.get("Component", ""),
                            "license": "Loghub research/academic use; cite ISSRE 2023",
                        },
                    }
                    handles[split].write(json.dumps(record, ensure_ascii=False) + "\n")
                    counts[split] += 1
    finally:
        for handle in handles.values():
            handle.close()
    return counts


if __name__ == "__main__":
    print(json.dumps(convert(), indent=2))
