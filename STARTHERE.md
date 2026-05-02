# STARTHERE.md - Coding Assistant Bootstrap Guide

> This file is designed for coding assistants. If you are a human, see [README.md](README.md).

## Quick Bootstrap

```bash
git clone https://github.com/GreyforgeLabs/service-cartographer.git && cd service-cartographer && ./scripts/setup.sh
```

## What This Project Does

`service-cartographer` is a read-only CLI that inventories local workflow surfaces: systemd units, cron jobs, wrapper scripts, Git repositories, and environment files. It emits JSON, Markdown, or CSV so maintainers can make explicit keep, review, or retire decisions.

## Project Structure

```text
src/service_cartographer/
  cli.py          command line entry point
  collectors.py   read-only system collectors
  classifier.py   keep/review/retire hint logic
  formatters.py   JSON, Markdown, and CSV renderers
  privacy.py      redaction helpers
tests/            pytest suite
scripts/setup.sh  idempotent setup and verification
```

## Setup Prerequisites

- Python 3.11 or newer
- `git` for repository scanning
- Linux with `systemctl` and `crontab` for full host scans

## Installation Steps

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Verification

```bash
pytest
ruff check src/service_cartographer/*.py tests/*.py
service-cartographer scan --systemd-scope off --no-cron --repo-root . --format json
```

## Key Entry Points

- CLI: `service-cartographer scan`
- Package entry point: `service_cartographer.cli:main`
- Collector functions: `service_cartographer.collectors`

## Configuration

The tool is CLI-configured. Use `--repo-root`, `--wrapper-dir`, `--env-root`, `--unit-dir`, and `--focus` to scope scans. It does not require secrets or environment variables.

## Common Tasks

```bash
# Run tests
pytest

# Lint
ruff check src/service_cartographer/*.py tests/*.py

# Build package
python -m build

# Local Markdown report
service-cartographer scan --format markdown --output report.md
```
