# Contributing to LogLens AI

Thanks for your interest in improving LogLens AI. This guide covers the local
setup, the quality bar, and how to get a change merged.

## Development setup

```bash
git clone https://github.com/LoglensAI/LogLens-AI.git
cd LogLens-AI
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # add ".[deep]" for the MiniLM engine
pre-commit install               # runs ruff + mypy + hygiene hooks on commit
```

## Quality bar

All checks are configured in `pyproject.toml` and mirrored in CI:

```bash
pytest -q                        # full test suite
ruff check src/ tests/           # lint
ruff format src/ tests/          # auto-format
mypy src/loglens                 # type check
```

- **Tests are required.** New behaviour needs a test; bug fixes need a
  regression test. Keep the suite green.
- **Lint and types** are advisory in CI today and will become blocking. Please
  don't add new violations - run the tools before pushing.
- **No silent failures.** Every `except` should log, re-raise, or be justified
  by a comment. Never swallow exceptions bare.
- **No invisible/unicode artifacts** in source (a test enforces this).

## Commit & PR conventions

- Keep commits focused and messages descriptive; the changelog is generated
  from history via git-cliff.
- Open a PR against `main`. CI must pass (tests + accuracy gates).
- For anything security-related, see [SECURITY.md](SECURITY.md) - do not open a
  public issue.

## Project layout

See [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md) for the architecture, the
module responsibilities, and the in-progress refactor roadmap.
