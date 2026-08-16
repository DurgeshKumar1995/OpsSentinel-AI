# SafeOps public dataset

This directory contains the 2,000-line HDFS and BGL samples from
[Loghub](https://github.com/logpai/loghub), plus generated JSONL splits.

Loghub permits these datasets for research or academic work subject to attribution.
Keep `loghub/LICENSE` with any copy or distribution and cite the ISSRE 2023 paper in
`loghub/CITATION`. Confirm separate commercial-use rights before using this data in a
commercially deployed product.

The generated records are suitable for retrieval and evaluation, not direct training
of production-action behavior. BGL anomaly labels come from the source. HDFS sample
records are treated as normal because the 2K structured sample does not include the
block-level anomaly ground truth from the full HDFS v1 archive.

Rebuild and index:

```bash
./venv/bin/python scripts/prepare_loghub_dataset.py
./venv/bin/python scripts/index_dataset.py
```

Splits are deterministic: 70% train, 15% validation, and 15% test. Never index the
validation or test splits; they are reserved for measuring retrieval/classification.
