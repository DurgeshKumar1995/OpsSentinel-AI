# OpsSentinel AI datasets

This directory contains the 2,000-line HDFS, BGL, Apache, OpenSSH, Linux, and
ZooKeeper samples from
[Loghub](https://github.com/logpai/loghub), plus generated JSONL splits.

`devops_knowledge.jsonl` contains original, MIT-licensed diagnostic knowledge written
for this project. Its 20 scenarios cover Kubernetes, CI/CD, deployments,
infrastructure as code, containers, cloud APIs, networking, TLS, observability,
databases, caches, messaging, and SRE. Each record separates symptoms, likely causes,
safe diagnostic checks, and mutation cautions. It is retrieval context—not permission
to execute production changes.

Loghub permits these datasets for research or academic work subject to attribution.
Keep `loghub/LICENSE` with any copy or distribution and cite the ISSRE 2023 paper in
`loghub/CITATION`. Confirm separate commercial-use rights before using this data in a
commercially deployed product.

The generated records are suitable for retrieval and evaluation, not direct training
of production-action behavior. BGL anomaly labels come from the source. HDFS sample
records are treated as normal because the 2K structured sample does not include the
block-level anomaly ground truth from the full HDFS v1 archive.
Apache, OpenSSH, Linux, and ZooKeeper records are explicitly marked `unlabeled`; their
severity fields and event templates remain useful retrieval evidence, but the project
does not invent anomaly labels for them.

Rebuild and index:

```bash
./venv/bin/python scripts/prepare_loghub_dataset.py
./venv/bin/python scripts/index_dataset.py
```

Splits are deterministic: 70% train, 15% validation, and 15% test. Never index the
validation or test splits; they are reserved for measuring retrieval/classification.
The original DevOps knowledge file is fully indexed because it is a curated reference
collection rather than evaluation data.
