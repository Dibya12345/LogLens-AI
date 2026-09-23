# LogLens AI - GitHub Action

Run LogLens on your CI logs to surface and explain anomalies, and optionally
**fail the build** when a real incident shows up. Everything runs on the runner -
your logs never leave it.

It produces:
- a **job summary** (incident table in the Actions run),
- inline **annotations** on the run, and
- a **non-zero exit** (via `fail-on`) that fails the job.

## Usage

```yaml
name: build
on: [push, pull_request]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # your build/test - capture its output
      - name: Build
        run: |
          set +e
          your-build-command 2>&1 | tee build.log
          exit ${PIPESTATUS[0]}

      # analyze the log; fail the job on any ERROR-or-worse anomaly
      - name: LogLens
        if: always()          # run even if the build step failed
        uses: LoglensAI/LogLens-AI@v0.10.0
        with:
          source: build.log
          fail-on: error       # critical | error | warning | fatal | any
          mode: fast           # fast | turbo | deep
```

## Inputs

| Input | Default | Description |
|-------|---------|-------------|
| `source` | *(required)* | Path to the log file to analyze. |
| `fail-on` | `""` | Fail the job if an anomaly is this severity or worse (`critical` / `error` / `warning` / `fatal` / `any`). Empty = report only. |
| `mode` | `fast` | Detection mode: `fast`, `turbo`, or `deep`. |
| `version` | latest | Pin a `loglensai` version, e.g. `0.10.0`. |
| `python-version` | `3.12` | Python version to run on. |

## Notes

- Use `if: always()` so LogLens still analyzes the log when the build step fails -
  that's exactly when you want the root cause surfaced.
- `fail-on` empty (the default) makes the Action **advisory** - it posts the
  summary and annotations but never fails the job. Turn on gating when you trust it.
- The Action wraps the same `loglens analyze --format json` CLI, so behavior matches
  what you get locally.