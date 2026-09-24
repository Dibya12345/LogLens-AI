# LogLens AI — Benchmark Baseline (v0.9.0)

Measured baseline for the 0.9.0 release. All numbers are reproducible with the
commands shown; this file is the regression anchor for future releases (a drop
in accuracy or throughput below these figures should fail review).

- **Environment:** Linux x86_64, Python 3.11, 4 workers
- **Dataset (accuracy):** `benchmarks/BGL_2k.log` — 2,000 real HPC log lines,
  143 human-labeled anomalies (LogHub BGL)
- **Dataset (throughput):** BGL_2k tiled to 200k / 1M lines (throughput is
  content-independent; anomaly counts on the tiled file are not meaningful)
- **Build under test:** layered architecture (Phases 6–7), all CI gates green

---

## 1. Detection accuracy (BGL_2k, 143 labeled anomalies)

```
loglens benchmark benchmarks/BGL_2k.log --format bgl --supervised
```

| Method                          | Precision | Recall |    F1 |
|---------------------------------|-----------|--------|-------|
| Rule + embeddings (unsupervised)|     0.334 |  1.000 | 0.501 |
| Supervised head (RandomForest)  |     0.902 |  0.965 | 0.932 |

- **Unsupervised** runs with zero training and catches **100% of real
  anomalies** (recall 1.000) — it never misses, at the cost of some false
  positives. This is the out-of-the-box, no-setup path.
- **Supervised** (a few seconds to train on labeled logs) reaches **F1 0.932**
  with 90% precision and 97% recall.
- CI floor: unsupervised F1 must stay ≥ 0.45 (`--min-f1 0.45`).

## 2. Throughput, latency & memory

```
loglens bench <file> --modes fast,turbo --workers 4
```

| Mode  |   Lines | Time (s) | Lines/s | Peak RAM | Notes                          |
|-------|--------:|---------:|--------:|---------:|--------------------------------|
| fast  |   2,000 |    0.32  |   6,208 |     —    | full re-clustering, embeddings |
| turbo |   2,000 |    0.10  |  20,415 |     —    | parallel count-based scan      |
| fast  | 200,000 |   24.55  |   8,147 |   911 MB | full ML pass                   |
| turbo | 200,000 |    3.81  |  52,467 |   359 MB | chunked, multiprocess          |
| turbo |1,000,000|   18.77  |  53,292 | 1,099 MB | linear scaling                 |

- **turbo sustains ~52,000 lines/s** independent of file size (200k → 1M),
  at roughly **7× the throughput and ~40% the memory of fast mode**.
- **1,000,000 log lines analyzed in ~19 seconds** on a 4-core machine.
- **CLI cold-start: ~190 ms** (lazy-import; down from ~1.6 s pre-optimization).

## 3. Test suite

```
pytest --cov=loglens
```

- **171 passed, 11 skipped**, 0 failures
- **Coverage: 69.30%** (CI floor: 65%)

## 4. Quality gates (all blocking in CI)

| Gate                          | Result                         |
|-------------------------------|--------------------------------|
| ruff (lint + format)          | clean                          |
| mypy (strict, py3.10–3.12)    | 0 errors, 45 files             |
| import-linter (architecture)  | 1 contract kept, 0 broken      |
| pytest + coverage             | 171 passed, 69.30% ≥ 65%       |
| accuracy gate (F1)            | 0.501 ≥ 0.45                   |

## 5. Feature surface (exercised end-to-end)

**CLI (8 commands):** `version`, `hello`, `analyze`, `ask`, `benchmark`,
`train`, `bench`, `watch`.
**SDK (public API):** `analyze()`, `analyze_entries()`, `analyze_async()`,
`LogLensHandler` (drop-in `logging.Handler`), `LiveDetector`, `Monitor`/`init()`.
**Ingestion:** file, stdin, URL, live command output (`watch`).
**Output:** rich terminal, standalone HTML report, markdown.
**Detection:** DBSCAN clustering + TF-IDF (+ optional MiniLM neural embeddings,
`[deep]` extra) + supervised RandomForest head + additive rule engine.
**Extras:** LLM-powered root-cause analysis (bring-your-own-key: OpenAI / Azure
/ Groq), Slack / Teams / email alerting, secret/PII redaction before any LLM
call, SSRF-guarded webhooks.

## 6. Platform-agnosticity

- Multiprocessing (`turbo`) verified under the `spawn` start method
  (macOS/Windows default), not just Linux `fork`.
- All text file I/O specifies an explicit encoding (no Windows cp1252
  corruption); CRLF input handled.
- Cross-platform cache/config via `platformdirs`; no hardcoded paths.
- Only Unix-only API used is `resource` (guarded, optional).
- Known caveat: `watch` command parsing uses POSIX `shlex`; complex quoted
  commands on Windows may need adjustment (simple commands work).
