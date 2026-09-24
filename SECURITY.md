# Security Policy

## Supported versions

LogLens AI is pre-1.0. Security fixes are applied to the latest released
version on PyPI and the `main` branch. Older versions are not maintained.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Report privately via GitHub's [private vulnerability reporting](https://github.com/LoglensAI/LogLens-AI/security/advisories/new)
(Security → Report a vulnerability), or email the maintainer at
`pr8101999@gmail.com` with the subject line `LogLens AI security`.

Please include:

- a description of the issue and its impact,
- steps to reproduce (a minimal example if possible),
- affected version(s).

We aim to acknowledge reports within 5 business days and to provide a
remediation timeline after triage.

## Data-handling notes for users

LogLens AI is designed to run **locally**. Detection never leaves your machine.
Two features send data off-box only when you explicitly enable them:

- **AI root-cause analysis (`--rca`, `ask`)** sends a truncated digest of
  anomalous log lines to the LLM provider you configure (OpenAI / Azure / Groq).
  Log content can contain secrets or PII; review before enabling in production.
- **Alerting** (Slack / Teams / email) posts anomaly summaries to the
  destinations you configure via environment variables.

API keys, webhook URLs, and SMTP credentials are read from environment
variables (or a local `.env`) and are never written to disk by LogLens.
