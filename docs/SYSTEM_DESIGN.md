# LogLens AI - System Design & Architecture Audit

**Status:** Draft for pre-investment technical due diligence
**Author:** Engineering
**Date:** 2026-09-19
**Scope:** Full `src/loglens` package, root scripts, packaging, CI/CD, DevOps
**Version audited:** 0.8.2 (commit on `main` after the file-type + LLM-provider refactor)

---

## 1. Executive summary

LogLens AI is a local-first, privacy-oriented log anomaly-detection CLI and SDK. The
core product works: it ingests logs from files/stdin/HTTP/commands, parses them into a
common model, embeds them (TF-IDF or MiniLM), clusters and scores anomalies with a rule
engine plus an optional supervised head, and can produce a terminal view, an HTML report,
and an LLM root-cause analysis. It ships as a wheel with a bundled model, has a real test
suite (147 tests), CI with accuracy gates, and a clean multi-stage non-root Docker image.

That is the good news, and it is genuinely a solid foundation. The audit below is written
to the standard an acquirer's engineers will apply: **is this codebase safe to build a
team and a roadmap on?** Today the honest answer is "not yet, but the gap is closable in
a well-defined set of phases." The problems are concentrated, not diffuse:

- **Two parallel implementations of the core pipeline** (the classic `parser → embeddings
  → detector` path and the `turbo` path) that use different maskers, different severity
  weights, and different anomaly thresholds. The same log can score differently depending
  on which flag the user passed.
- **Two god-functions** carry most of the logic: `detector.detect()` (~316 lines) and the
  CLI `analyze` command (~370 lines). Both interleave orchestration, domain logic, model
  I/O, and presentation, which makes them hard to test and risky to change.
- **Layering is inverted in places** - the lightweight streaming detector imports the
  top-level façade, dragging numpy/LLM/output into a component that should be small.
- **Several silent or invisible failures**, including a verified rendering bug (zero-width
  spaces baked into HTML/SVG tag names) that means charts and RCA bullet lists **do not
  render at all**, and a silent model-load fallback that downgrades detection quality with
  no signal to the user.
- **Investor-visible hygiene gaps:** two heavy dependencies (`hdbscan`, `umap-learn`) are
  still declared but unused - they pull `numba`/`llvmlite` into every install for nothing;
  lint runs but cannot fail the build; there is no type-check gate; the `LICENSE` file is
  an 11-byte stub.
- **"Written by AI" tells** that a diligence reviewer will notice: invisible unicode in
  source, leftover `# audit XX-01` scaffold comments, emoji in library code, empty
  docstring placeholders, marketing copy inside a benchmark function, and duplicated
  constants.

None of these are fatal. The purpose of this document is to (a) record the current
architecture honestly, (b) enumerate the findings with file:line evidence, and (c) define
a target architecture and a phased migration that leaves the codebase clean, consistent,
single-responsibility, and ready for heavy development - in an order that de-risks each
step behind the existing test suite.

### Verdict at a glance

| Dimension | Today | After migration |
|---|---|---|
| Correctness (one input → one result) | ⚠ two divergent pipelines | ✅ one core, one result |
| Testability | ⚠ god-functions | ✅ small, pure units |
| Layering | ⚠ inverted deps, CLI bypasses SDK | ✅ strict one-way deps |
| Silent failures | ⚠ several, one broken renderer | ✅ observable, logged |
| Dependency weight | ⚠ dead heavy deps | ✅ minimal, declared |
| Quality gates | ⚠ advisory only | ✅ enforced (phased) |
| "Looks hand-engineered" | ⚠ AI tells present | ✅ clean, idiomatic |

---

## 2. Current architecture (as-is)

### 2.1 Component map

```
                         ┌───────────────────────────────────────┐
   Interface layer       │  cli.py (Typer, 8 commands, ~815 LOC)  │
                         └───────────────┬───────────────────────┘
                                         │ reaches directly into 13 modules
                                         │ (bypasses the SDK facade)
                         ┌───────────────▼───────────────────────┐
   "SDK" facade          │  api.py  analyze()/analyze_entries()   │
   (used by SDK users,   │  + AnalysisResult (AI methods patched  │
    bypassed by CLI)     │    on at import time)                  │
                         └──────┬───────────────────────┬─────────┘
                                │                        │
      ┌─────────────────────────▼──────┐   ┌────────────▼───────────────┐
      │  pipeline/ (classic path)       │   │  pipeline/turbo.py          │
      │  ingestion → parser →           │   │  (parallel RE-IMPLEMENTATION│
      │  embeddings → run → detector →  │   │   of parse+template+score)  │
      │  grouping                       │   │                             │
      └───────────────┬─────────────────┘   └─────────────────────────────┘
                      │
   Runtime/           │        ┌──────────────┐   ┌──────────────┐
   integrations   ────┼───────►│ live.py      │   │ monitor.py   │
                      │        │ (streaming)  │   │ handler.py   │
                      │        └──────┬───────┘   │ alerts.py    │
                      │               │ imports api.py (inversion)│
                      ▼               ▼           └──────────────┘
   Infra adapters   llm/ (transport/config/providers/client/rca)
                    output/ (html_report.py, report.py, terminal.py)
```

### 2.2 End-to-end data flow (classic path)

1. **Validate** - `pipeline/filetype.check_source()` rejects binaries/dirs/known non-text
   extensions before reading.
2. **Ingest** - `ingestion.get_reader()` picks a reader (file/stdin/http/command);
   `stream_lines()` yields lines asynchronously.
3. **Parse** - `parser.StreamParser` detects a format, extracts fields into `LogEntry`,
   folds multiline stack traces, and normalizes cloud JSON (AWS/GCP/Azure).
4. **Embed** - `run.run()` builds an engine (`EmbeddingEngine` TF-IDF, or
   `DeepEmbeddingEngine` MiniLM), fits synonyms + vectorizer, and (template mode) embeds
   one representative per template and scatters the vector to members.
5. **Detect** - `detector.detect()` re-builds a template registry, clusters template-mean
   vectors with DBSCAN, computes signals (rarity, bursts, floods, recurring, novelty,
   keyword hits), runs a ~100-line additive scoring loop, thresholds, and assembles groups.
6. **Group/serve** - results are sorted and grouped; `output/*` renders HTML/terminal, and
   `llm/rca.py` optionally generates a root-cause narrative.

The **turbo path** (`--turbo`) does **not** go through steps 3–5. It re-implements parsing,
template masking, and scoring inside `turbo.py` using multiprocessing.

### 2.3 File-by-file responsibility (condensed)

| Module | LOC | Responsibility | Notes |
|---|---|---|---|
| `cli.py` | 815 | Typer app, 8 commands | god-command `analyze`; bypasses `api.py` |
| `pipeline/detector.py` | 609 | clustering + scoring | god-function `detect()` |
| `pipeline/parser.py` | 507 | parse + cloud-JSON + streaming | ≥4 responsibilities |
| `api.py` | 294 | SDK facade | import-time monkey-patching |
| `pipeline/benchmark.py` | 289 | eval + grid + supervised head | undeclared `joblib` import |
| `pipeline/synonyms.py` | 276 | synonym learning + cache | fingerprint-keyed shared cache |
| `pipeline/embeddings.py` | 241 | TF-IDF engine + features | own severity/keyword maps |
| `pipeline/turbo.py` | 212 | parallel scanner | parallel re-implementation |
| `alerts.py` | 203 | Slack/Teams/Email + dispatch | unsynchronized dispatcher |
| `output/html_report.py` | 187 | HTML report + charts + md | **ZWSP rendering bug** |
| `live.py` | 180 | streaming detector | imports `api.py` (inversion) |
| `monitor.py` | 164 | lifecycle + alerting + RCA | 4 responsibilities |
| `llm/*` | ~470 | LLM transport/providers/rca | clean (recently refactored) |

---

## 3. Audit findings

Severity: **P0** ship-blocker / **P1** high / **P2** medium / **P3** low. Every item has
file:line evidence and has been spot-verified against the source.

### 3.1 P0 - Correctness & user-visible defects

- **Broken HTML/SVG rendering - invisible U+200B in tag names.**
  `output/html_report.py` emits `<​ul>`, `<​/ul>`, `<​rect …>`,
  `<​line …>` at lines 27, 32, 43, 62, 84, 89. Browsers cannot parse a tag whose name
  begins with a zero-width space, so **the RCA bullet lists, every bar-chart rectangle, and
  the histogram threshold line silently fail to render**. Verified: 16 source lines contain
  U+200B (also in `turbo.py` and `grouping.py` mask tokens - see 3.3). This is the single
  most embarrassing thing an auditor could find, because it's invisible in a diff.

- **Silent model-load downgrade.** `cli.py:327-329` catches *all* exceptions during
  bundled-model discovery and sets `model_path = ""`, silently falling back to unsupervised
  detection with no log or user message. A corrupt or permission-denied model degrades
  detection quality invisibly.

### 3.2 P1 - Architecture (the structural core of this phase and the SRP phase)

- **Two parallel pipelines that can disagree.** The classic path and `turbo.py` are
  independent implementations of parse + template + score. Concretely they diverge:
  - **Severity→weight maps disagree numerically across four modules:** `SEVERITY_BASE`
    ERROR=0.55 (`detector.py:39`), `LEVEL_MAP` ERROR=0.75 (`embeddings.py:22`),
    `_SEVERITY_WEIGHT` ERROR=0.8 (`turbo.py:99`).
  - **Anomaly threshold differs:** `score >= flag_threshold` (`detector.py:524`) vs
    `Template.is_anomaly = score >= 0.5` (`turbo.py:113`).
  - **Three template maskers** (`templates.py`, `turbo.py`, `grouping.py`) with different
    regexes and different tokens - and two of them use U+200B tokens, so their template
    keys can **never** equal the canonical ones.
- **God-functions.**
  - `detector.detect()` (`detector.py:271-587`, ~316 lines) performs ≥10 jobs (registry
    build, clustering, outlier stats, burst/flood/recurring/chronic/novelty detection, the
    scoring loop, thresholding, group + pattern assembly).
  - CLI `analyze` (`cli.py:146-514`, ~370 lines) interleaves arg parsing, source
    validation, ingestion, engine selection, **model I/O**, incident detection, grouping,
    RCA, HTML, and Rich rendering.
- **Layer inversions.**
  - `live.py` (a low-level streaming component) imports `loglens.api` (the top-level
    façade), transitively pulling numpy + output + LLM into it (`live.py:10,15-17`).
  - `api.py` (SDK) imports `output.html_report` (`api.py:17`) - presentation inside the API.
  - `cli.py` **reimplements** the pipeline instead of calling `api.py`, so there are two
    orchestration paths to maintain.
- **Two inverted severity conventions coexist:** `detector.LEVEL_SEVERITY` (0 = worst) vs
  `api._LEVEL_WEIGHT` (7 = worst, `api.py:20-24`). No single source of truth for level
  metadata - at least five duplicate level/color/emoji maps across the codebase.
- **Undeclared data-model contract.** `detector.detect()` writes `e.anomaly_score` /
  `e.anomaly_reasons` onto `LogEntry` (`detector.py:526-528`), but `LogEntry` (`models.py`)
  declares neither; `grouping.py` reads them back via `getattr`. The contract lives only in
  side effects.
- **Import-time monkey-patching of the primary public type.** `AnalysisResult.rca/ask/
  save_html/save_rca` are attached at import (`api.py:259-295`), not defined in the class -
  breaks introspection and IDE discovery, and makes the class body look incomplete.

### 3.3 P1/P2 - Silent & invisible failures (inventory)

| Location | What's hidden | Severity |
|---|---|---|
| `html_report.py:27…89` | charts + RCA lists don't render (U+200B) | P0 |
| `cli.py:327-329` | corrupt model → silent unsupervised downgrade | P0 |
| `worker.py:46` | all per-entry processing errors → counted, `debug` only | P1 |
| `handler.py:66-67` | `on_anomaly` failure during flush silently discarded | P1 |
| `benchmark_labeled.py:9-12` | broad `except` disables `--sweep` silently | P2 |
| `synonyms.py:187-188` | corrupt synonym cache swallowed, no log | P2 |
| `monitor.py:95-96,139-140,146-147` | dropped anomalies / stop() errors, silent | P2 |
| `ingestion/command.py:110-111` | `proc.wait()` errors on kill path swallowed | P2 |
| `templates.py:74/85/96` | unparseable timestamps → `None`, no trace | P3 |

(Several `except` sites were already upgraded to `logger.debug/warning` in an in-flight
branch - `live.py`, `alerts.py`, `parser.py`, `turbo.py`, `monitor.ai_rca_line`. That work
folds into Phase 0.)

### 3.4 P1/P2 - Redundancy & dead code

- **Dead heavy dependencies still declared:** `hdbscan>=0.8.33` and `umap-learn>=0.5.6`
  (`pyproject.toml`) - **verified unused** (0 imports in `src/`); the code uses sklearn
  `DBSCAN`. `umap-learn` pulls `numba`+`llvmlite` (~180 MB) into every install for nothing.
- **Duplicated logic:** ingestion loop and engine-selection copy-pasted between `analyze`
  and `ask`; "rebuild LogEntry list for RCA" copy-pasted 3×; RCA render logic in 3 places;
  incident heuristic in 2 places; two full HTML renderers with duplicate SVG chart engines
  (`html_report.py` vs `report.py`); duplicate merge block in `turbo.scan_file`.
- **Dead code:** `run.run_turbo()` (never called), `grouping.group_summaries()` (imported,
  never invoked), factory shims `get_engine/get_deep_engine/get_learner`, `ENGINE_VERSION`
  (unread, declared twice), `Anomaly.severity` property + its inverted map (no references),
  `LogLensHandler.anomalies` (populated, never read, unbounded), unused imports
  (`benchmark.py` `extract_features`, `run.py` `List`, `turbo.py` `field`).
- **Undeclared runtime imports:** `joblib` (`benchmark.py:9`) and `psutil` (`turbo.py:44`)
  are used but not declared (rely on transitive/optional availability).

### 3.5 P2 - Platform-agnosticity

- **Turbo multiprocessing assumes fork.** `mp.Pool` forks on Linux but **spawns** on macOS
  (3.8+) and Windows; the broad fallback (`turbo.py`) degrades to serial **silently** - the
  "turbo" claim evaporates off-Linux with no warning surfaced.
- **Byte-offset vs text-mode chunk drift** (`turbo.py`): chunk boundaries computed on binary
  offsets but re-derived in text mode with `errors="replace"`; non-UTF-8/CRLF input can
  overlap or drop lines → double-counted or missing entries.
- **`sys.excepthook` / `atexit` / daemon-thread globals** (`monitor.py`): only main-thread
  crashes are captured (no `threading.excepthook`); repeated `init()` calls stack hooks; the
  drain thread is never `join()`ed.
- **Inconsistent decode error policy:** `errors="replace"` in readers vs `errors="ignore"`
  in `benchmark.load_labeled`; no BOM/encoding detection; emoji in output strings can raise
  `UnicodeEncodeError` on non-UTF-8 stdout/SMTP.
- **`datetime.now()` (local, naive)** for report timestamps and syslog year backfill -
  non-deterministic, TZ-dependent.

### 3.6 P1 - Security & robustness (investor-relevant)

- **PII/secrets shipped to third-party LLMs with no redaction.** `llm/rca.py` and
  `monitor.ai_rca_line` send raw log content (tokens, emails, IPs, stack traces) to
  OpenAI/Groq/Azure. The context builder claims "privacy-conscious" but only truncates.
- **SSRF via unvalidated webhook URLs.** `alerts.py` `urlopen`s whatever is in
  `LOGLENS_SLACK_WEBHOOK`/`LOGLENS_TEAMS_WEBHOOK` with no scheme/host allow-list.
- **SMTP creds can go cleartext** when `use_tls=False`; `LLMConfig.api_key` has no
  `repr=False`, so it can leak into logs/`repr`.
- **Unsynchronized `AlertDispatcher`** shared across the worker thread and the main-thread
  excepthook → data race on cooldown/rate-limit state.

### 3.7 P1/P2 - DevOps & tooling

- **Lint is theatrical:** ruff runs with `continue-on-error: true` **and** `|| true`, and
  there is **no ruff config**. **No mypy** anywhere despite a fully-typed codebase. No
  coverage gate. No pre-commit. No `.editorconfig`/`CONTRIBUTING.md`/`SECURITY.md`.
- **`LICENSE` is an 11-byte stub** ("MIT License" with no body/copyright) - a real IP gap.
- **Missing `py.typed`** - downstream type-checkers get no benefit from the hints.
- **CI/release:** floating (non-SHA) action pins; `release.yml` pushes to `main` directly;
  Docker Hub description step points at `./DOCKER.md` (file is at `docs/DOCKER.md`) → fails
  every tagged release; repo URL differs between `pyproject.toml` and `Dockerfile`.
- **`.gitignore` bug:** malformed line `benchmarks/*.logdatasets/` means `benchmarks/*.log`
  isn't ignored - which is why `benchmarks/BGL_2k.log` (317 KB, re-downloaded in CI) is
  committed.

### 3.8 P2 - "Looks AI-generated" tells (perception risk in diligence)

Invisible U+200B in source; leftover scaffold comments `# audit DE-04`, `# audit S-01`,
`(audit S-06)`; emoji embedded in library code and alert payloads; empty docstring
placeholders (blank first line, no docstring) across `api.py`/`live.py`/`monitor.py`;
marketing copy hard-coded into `speedbench.to_markdown` ("compare to Splunk/Hadoop…");
duplicated `ENGINE_VERSION` constant; `_lock2` with no `_lock1`; trailing whitespace on
value lines. Individually cosmetic; collectively they read as machine-generated and will
draw reviewer attention away from the real (good) engineering.

### 3.9 Strengths (for balance - do not regress these)

Version single-sourcing with a CI drift gate; accuracy/F1 quality gates; clean multi-stage
non-root Docker with healthcheck; 147 tests with disciplined skip-guarding; zero bare
`print()`; no committed secrets; full PyPI classifier/keyword metadata; the recently
refactored `llm/` layer (transport/config/providers/client) is already clean and is the
template for the rest of the codebase.

---

## 4. Target architecture (to-be)

### 4.1 Principles

1. **Strict, one-way dependencies.** `domain → application → interface`, with
   infrastructure behind ports. Nothing low-level imports a façade.
2. **One core, one result.** A single detection core; parallelism is an *execution
   strategy* over that core, not a second implementation.
3. **Single source of truth** for level/severity/color/emoji metadata.
4. **Explicit contracts.** Scores live on typed models, not dynamic attributes. No
   import-time patching.
5. **Ports & adapters** for ingestion, LLM, alerting, and output, so integrations are
   swappable and testable.
6. **Fail loud or fail logged** - never silent.

### 4.2 Proposed package layout

```
loglens/
  domain/            # pure, dependency-light
    models.py        # LogEntry (+ score/reasons as real fields), Anomaly, enums
    severity.py      # THE level/severity/color/emoji source of truth
    templates.py     # ONE masker + TemplateRegistry
  application/        # orchestration, no I/O framework specifics
    pipeline.py      # analyze()/analyze_entries() (the real SDK core)
    detection/       # detector split into: clustering, signals, scoring, thresholds
    streaming.py     # LiveDetector (depends on domain+application, NOT api)
  infrastructure/    # adapters behind ports
    ingestion/       # file/stdin/http/command readers (already clean)
    embeddings/      # tfidf + deep engines behind one EmbeddingEngine port
    execution/       # serial + multiprocessing executors over the ONE core
    llm/             # transport/config/providers/client/rca (already clean)
    alerting/        # slack/teams/email behind one Alerter port + one HTTP helper
    output/          # ONE report renderer + charts + terminal
  interface/
    cli.py           # thin Typer adapter over application.pipeline
    sdk (__init__)   # curated public API, no import-time side effects
```

### 4.3 Key design decisions

- **Detection core split** (SRP): `detect()` becomes a small orchestrator calling
  `clustering.py` (eps + DBSCAN), `signals.py` (burst/flood/recurring/novelty), and
  `scoring.py` (the additive rule engine, pure and unit-testable). Thresholding becomes its
  own function. Each piece is independently testable with tiny inputs.
- **Turbo becomes an executor, not a fork.** `infrastructure/execution/` provides a serial
  and a multiprocessing executor that both call the *same* `templates` masker and `scoring`
  functions. This deletes `turbo.py`'s parallel re-implementation and the divergence with
  it. Multiprocessing uses an explicit start-method and surfaces a warning when it falls
  back to serial.
- **One severity module.** `domain/severity.py` exports a single ordered enum + maps;
  every other module imports from it. Deletes the five duplicate maps and the two inverted
  conventions.
- **Typed model contract.** `LogEntry` gains `anomaly_score: float | None` and
  `anomaly_reasons: list[str]` as declared fields; the `getattr` side-channel goes away.
- **CLI over SDK.** `cli.py` calls `application.pipeline` and only does arg-parsing +
  Rich rendering. Rendering helpers (`_do_rca`, incident, grouping-to-panel) move to a
  `interface/render.py` and are reused by every command (kills the 3× RCA-render dup).
- **No import-time patching.** `AnalysisResult` methods become normal methods.
- **Ports for integrations.** One `Alerter` protocol + one shared `post_json` helper (kills
  Slack/Teams boilerplate); webhook URLs pass an allow-list; LLM context gets a redaction
  pass; `api_key` fields become `repr=False`.
- **One renderer.** Merge `report.py` into `html_report.py` (or vice-versa) with one chart
  engine and one stylesheet - after the U+200B fix.

---

## 5. Migration plan (phased, test-guarded)

Each phase is independently shippable, keeps the 147-test suite green, and is committed
separately. This ordering front-loads the cheap, high-signal wins (so the repo looks clean
immediately) and defers the invasive SRP decomposition to a phase of its own, which matches
the "professional/maintainable first, SRP next" sequence.

### Phase 0 - Safety net & hygiene (fast, low-risk)
- Remove dead deps `hdbscan`/`umap-learn`; declare `joblib`/`psutil`.
- Fix the U+200B rendering bug (all 16 sites); add a test that asserts no control/zero-width
  chars in rendered HTML and in mask tokens.
- Make every silent `except` observable (logging pass - partly done).
- Fix the silent model-load downgrade to warn the user.
- Add tooling **advisory-first**: `[tool.ruff]`, `[tool.mypy]`, coverage config, pre-commit,
  `.editorconfig`; wire ruff+mypy into CI as non-blocking. Add `py.typed`, full `LICENSE`,
  `SECURITY.md`, `CONTRIBUTING.md`. Fix `.gitignore`, remove committed `BGL_2k.log`, fix the
  Docker Hub `readme-filepath`, align repo URLs.
- Strip AI tells: scaffold comments, emoji in library code, marketing copy in `speedbench`,
  duplicate `ENGINE_VERSION`, empty docstring stubs, trailing whitespace.

### Phase 1 - Consolidation (dedupe, single sources of truth)
- Introduce `domain/severity.py`; replace all five duplicate level maps; unify the two
  inverted conventions.
- One template masker (`domain/templates.py`); delete `turbo.py`/`grouping.py` maskers.
- Collapse the two HTML renderers into one; single chart engine.
- Remove dead code (`run_turbo`, `group_summaries`, factory shims, `Anomaly.severity`,
  unbounded `handler.anomalies`, unused imports).

### Phase 2 - SRP decomposition (**the next agreed phase**)
- Split `detector.detect()` into `clustering/signals/scoring/threshold`.
- Split `cli.analyze` into thin command + `application.pipeline` calls + `interface/render`.
- Extract cloud-JSON normalization out of `parser.py` into its own module.
- Turn `turbo` into an executor over the shared core; delete the parallel re-implementation.
- Remove import-time monkey-patching; typed `LogEntry` score fields.

### Phase 3 - Layering & integrations
- Fix `live.py` → `api.py` inversion (depend on application/domain only).
- Ports & adapters for alerting (one HTTP helper, `Alerter` protocol) and embeddings.
- Move HTML rendering out of `api.py`.

### Phase 4 - Correctness & security
- Fix turbo chunk-offset drift; explicit multiprocessing start-method + visible fallback.
- Unify scoring so live/classic/turbo agree; regression-test that one input → one score.
- LLM redaction pass; webhook allow-list; `repr=False` on secrets; SMTP TLS default;
  synchronize `AlertDispatcher`.

### Phase 5 - Enforce the gates
- Flip ruff + mypy to **blocking** once the backlog is clear; add a coverage floor;
  SHA-pin GitHub Actions; consider PyPI trusted publishing (OIDC).

---

## 6. Risk register & non-goals

- **Behavioural drift risk:** unifying scoring (Phase 4) can change which lines are flagged.
  Mitigation: freeze current outputs as golden fixtures before the change; gate on the
  accuracy/F1 suite.
- **Turbo performance risk:** rebuilding turbo as an executor must not regress throughput.
  Mitigation: keep `bench` numbers as a gate.
- **Scope discipline:** this document does **not** propose new features, a daemon/persistent
  process (backlog), or `.gz` ingestion (backlog). It is about making the *existing* product
  clean, correct, and maintainable.

---

## 7. Appendix - evidence index

All findings above carry file:line references verified against `main` @ 0.8.2. The four
subsystem audits (entry points/API, pipeline core, runtime/integrations, DevOps/deps) and
the spot-verifications (U+200B scan, dependency block, live/detector scoring divergence)
are the basis for this document and can be reproduced with `grep`/`python` from the repo
root.
