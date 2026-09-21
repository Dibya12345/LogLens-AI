# LogLens AI — Backlog

Tracked work that is deliberately deferred, with the rationale. This is a
living list; items graduate into the phased plan in `SYSTEM_DESIGN.md`.

## Product / features
- **Persistent warm process ("daemon mode").** Lazy import already cut CLI
  startup from ~1.6s to ~0.17s; a resident process to eliminate the ~1s
  scikit-learn import on every run is deferred until there's demand.
- **Compressed-file ingestion (`.gz`, `.zip`, …).** Currently rejected by the
  file-type guard with a "decompress first" hint. Native decompression later.

## Correctness (detection)
- **Full scoring unification across live / classic / turbo.** Phase 4
  consolidated the severity *tables* into `loglens.severity`, but the three
  paths still score differently by design: turbo is a fast count-based
  approximation (no embeddings) and live hard-flags severe lines for immediate
  streaming output before its periodic full rescore. Making them numerically
  identical would defeat those purposes; a unified *scoring policy* with
  golden-output regression tests is the real task and is deferred.
- **Turbo chunk-offset robustness.** `split_chunks` records byte offsets while
  `_process_range` re-derives position from `len(line.encode("utf-8"))`. For
  UTF-8/ASCII input this aligns; exotic encodings or mixed newlines could drift
  a chunk boundary and double-count or drop a line. A byte-accurate chunker is
  deferred (turbo is an approximation and the accuracy gate runs on the classic
  path).

## Enforcement gates (Phase 5) — DONE
- ✅ **ruff + mypy are now blocking** in CI (advisory `continue-on-error`
  removed).
- ✅ **Type-hardening complete** — `mypy src/loglens` is clean (0 errors), no
  blanket ignores.
- ✅ **Coverage gate** wired at `--cov-fail-under=65` (a ratchet). Raising the
  floor toward **85%** still needs more tests (see below).

## Test coverage
- Raise coverage from ~69% toward **85%** and lift the CI floor accordingly.
  The uncovered lines are concentrated in `cli.py`, `monitor.py`, deep-mode
  paths, and turbo edge cases.

## DevOps / supply chain (deferred by risk — need careful, verified changes)
- `release.yml` pushes version bumps **directly to `main`** (bypasses branch
  protection) — move to a PR-based release.
- **SHA-pin GitHub Actions** instead of floating major tags (each pin needs the
  exact upstream commit SHA verified, or a wrong pin breaks CI).
- **PyPI trusted publishing (OIDC)** instead of a long-lived API token.
- **Digest-pin Docker base images** for reproducible builds.

## Runtime / polish
- Provide `python -m loglens` (`__main__.py`).
- Remove the `hello` vanity CLI command.
